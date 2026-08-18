"""
Stripe billing views: checkout, portal, success/cancel callbacks.
"""

import stripe
from coloured_logger import Logger
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from djstripe.models import Customer, Subscription

logger = Logger(__name__)


def _use_stripe_key() -> None:
    """Point the stripe client at the key for this environment.

    Called at the top of every view that talks to Stripe.  The key is set per
    call rather than once at import because ``settings.DEBUG`` is what selects
    between the test and live key, and a test that flips it with
    ``override_settings`` must change which account is charged.
    """
    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )


@login_required
@require_POST
def create_checkout_session(request):
    """Create a Stripe Checkout session for the Pro plan."""
    _use_stripe_key()

    price_id = settings.STRIPE_PRO_PRICE_ID
    if not price_id:
        # Same answer as the failure branch below: say so through `messages`
        # and send the reader back to the pricing page, which renders through
        # `core.views.pages.pricing` with its full context.  Rendering the
        # template from here gave it no plans and no comparison rows, and the
        # template has never read an `error` key, so the reader met an empty
        # grid that explained nothing.
        #
        # The reader is not told the setting name.  It means nothing to a
        # buyer, and the operator gets it from the log.
        logger.error("STRIPE_PRO_PRICE_ID is not configured; cannot start a checkout")
        messages.error(request, "Pro is not available for purchase right now.")
        return redirect(reverse("core:pricing"))

    try:
        customer_id = request.user.stripe_customer_id
        if not customer_id:
            cust = stripe.Customer.create(
                email=request.user.email,
                metadata={"django_user_id": str(request.user.id)},
            )
            customer_id = cust["id"]
            request.user.stripe_customer_id = customer_id
            request.user.save(update_fields=["stripe_customer_id"])

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            client_reference_id=str(request.user.id),
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            allow_promotion_codes=True,
            success_url=request.build_absolute_uri(reverse("core:stripe_success"))
                + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.build_absolute_uri(reverse("core:stripe_cancel")),
        )
        if checkout_session.url is None:
            raise RuntimeError("Stripe checkout session returned no redirect URL")
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        logger.error("Stripe checkout error: %s", e)
        messages.error(request, f"Checkout failed: {e}")
        return redirect(reverse("core:pricing"))


@login_required
def stripe_success(request):
    """Post-checkout success page — sync dj-stripe data."""
    _use_stripe_key()

    session_id = request.GET.get("session_id")
    verified = False
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            verified = (
                session.customer == request.user.stripe_customer_id
                or str(session.client_reference_id) == str(request.user.id)
            )
            if verified and isinstance(session.customer, str):
                _sync_customer_after_checkout(request.user, session.customer)
        except Exception as e:
            logger.warning("stripe_success sync error: %s", e)

    return render(request, "stripe_success.html", {"verified": verified})


def _sync_customer_after_checkout(user, stripe_customer_id: str):
    """Sync the dj-stripe Customer and its Subscriptions from Stripe."""
    try:
        customer, _ = Customer.objects.get_or_create(
            id=stripe_customer_id,
            defaults={"livemode": not settings.DEBUG},
        )
        if not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
        Customer.sync_from_stripe_data(stripe_customer)

        customer.refresh_from_db()
        if not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        subs = stripe.Subscription.list(customer=stripe_customer_id, status="all", limit=10)
        for sub_data in subs.auto_paging_iter():
            Subscription.sync_from_stripe_data(sub_data)
    except Exception as e:
        logger.warning("_sync_customer_after_checkout error: %s", e)


def stripe_cancel(request):
    """Checkout cancelled — redirect to pricing with banner."""
    messages.info(request, "Checkout cancelled. You can upgrade anytime.")
    return redirect(reverse("core:pricing"))


@login_required
@require_POST
def create_customer_portal_session(request):
    """Create a Stripe Customer Portal session."""
    _use_stripe_key()

    customer_id = request.user.stripe_customer_id
    if not customer_id:
        return redirect(reverse("core:pricing"))

    portal_session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=request.build_absolute_uri(reverse("core:user_settings") + "#account"),
    )
    return redirect(portal_session.url, code=303)


def _sync_subscription_status(user):
    """Re-sync dj-stripe Subscription records from Stripe for this user."""
    _use_stripe_key()

    try:
        stripe_customer = stripe.Customer.retrieve(user.stripe_customer_id)
        customer = Customer.sync_from_stripe_data(stripe_customer)

        if customer is not None and not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        subs = stripe.Subscription.list(customer=user.stripe_customer_id, status="all", limit=10)
        for sub_data in subs.auto_paging_iter():
            Subscription.sync_from_stripe_data(sub_data)
    except Exception as e:
        logger.warning("_sync_subscription_status error: %s", e)
