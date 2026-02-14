"""
Stripe billing views: checkout, portal, success/cancel callbacks.
"""

from coloured_logger import Logger
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

logger = Logger(__name__)


@login_required
@require_POST
def create_checkout_session(request):
    """Create a Stripe Checkout session for the Pro plan."""
    import stripe

    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )

    price_id = settings.STRIPE_PRO_PRICE_ID
    if not price_id:
        return render(request, "pricing.html", {"error": "STRIPE_PRO_PRICE_ID not configured"})

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
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        logger.error("Stripe checkout error: %s", e)
        from django.contrib import messages

        messages.error(request, f"Checkout failed: {e}")
        return redirect(reverse("core:pricing"))


@login_required
def stripe_success(request):
    """Post-checkout success page — sync dj-stripe data."""
    import stripe

    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )

    session_id = request.GET.get("session_id")
    verified = False
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            verified = (
                session.customer == request.user.stripe_customer_id
                or str(session.client_reference_id) == str(request.user.id)
            )
            if verified:
                _sync_customer_after_checkout(request.user, session.customer)
        except Exception as e:
            logger.warning("stripe_success sync error: %s", e)

    return render(request, "stripe_success.html", {"verified": verified})


def _sync_customer_after_checkout(user, stripe_customer_id: str):
    """Sync the dj-stripe Customer and its Subscriptions from Stripe."""
    from djstripe.models import Customer

    try:
        customer, _ = Customer.objects.get_or_create(
            id=stripe_customer_id,
            defaults={"livemode": not settings.DEBUG},
        )
        if not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        import stripe

        stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
        Customer.sync_from_stripe_data(stripe_customer)

        customer.refresh_from_db()
        if not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        subs = stripe.Subscription.list(customer=stripe_customer_id, status="all", limit=10)
        from djstripe.models import Subscription

        for sub_data in subs.auto_paging_iter():
            Subscription.sync_from_stripe_data(sub_data)
    except Exception as e:
        logger.warning("_sync_customer_after_checkout error: %s", e)


def stripe_cancel(request):
    """Checkout cancelled — redirect to pricing with banner."""
    from django.contrib import messages

    messages.info(request, "Checkout cancelled. You can upgrade anytime.")
    return redirect(reverse("core:pricing"))


@login_required
@require_POST
def create_customer_portal_session(request):
    """Create a Stripe Customer Portal session."""
    import stripe

    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )

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
    import stripe

    stripe.api_key = (
        settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY
    )

    try:
        from djstripe.models import Customer, Subscription

        stripe_customer = stripe.Customer.retrieve(user.stripe_customer_id)
        customer = Customer.sync_from_stripe_data(stripe_customer)

        if not customer.subscriber:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])

        subs = stripe.Subscription.list(customer=user.stripe_customer_id, status="all", limit=10)
        for sub_data in subs.auto_paging_iter():
            Subscription.sync_from_stripe_data(sub_data)
    except Exception as e:
        logger.warning("_sync_subscription_status error: %s", e)
