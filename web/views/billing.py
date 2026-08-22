"""Stripe billing views: checkout, portal, success and cancel callbacks.

**The subscription belongs to an organization, never to a person.**  Somebody
buying for themselves gets an organization of one, made here at checkout and
named after them; a firm buys more than one seat on the same path.  So there
is one checkout, one portal and one Stripe customer per billing entity, and
``User.has_active_subscription`` has one kind of answer to give.

``accounts.teams`` owns what an organization is and who may join it.  This module
owns only the conversation with Stripe.
"""

from typing import Any

import stripe
from coloured_logger import Logger
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from djstripe.models import Customer, Subscription

from accounts.teams import access_membership, organization_for_checkout
from core.models import Organization

logger = Logger(__name__)

#: The largest seat count a self-serve checkout accepts.  This is a **guard
#: against a typing mistake, not a sales boundary**: a silent 500-seat card
#: payment is far more likely to be a slipped keystroke than a purchase.
#:
#: It is deliberately far above any real firm, because refusing a purchase a
#: buyer is ready to make protects nobody.  Whether a firm can put four
#: figures a month on a card is the firm's constraint, and a firm that cannot
#: goes to Custom on its own.  A low ceiling would only convert a sale we
#: could have taken today into an email thread that may never close.
#:
#: Seat count is also not what separates Team from Custom.  Custom is a
#: purchase order, negotiated terms and a quote; a large firm paying by card
#: is a Team customer, and a firm of three that needs a signed agreement is a
#: Custom one.
MAX_SELF_SERVE_SEATS = 50


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


def _requested_seats(request) -> int:
    """How many seats the buyer asked for.  One when they said nothing.

    A missing, unreadable or out-of-range value becomes one seat rather than
    an error: the individual purchase is the common case and posts no field at
    all, and a checkout that refuses to start explains nothing to a buyer.
    """
    raw = (request.POST.get("seats") or "").strip()
    if not raw:
        return 1
    try:
        seats = int(raw)
    except ValueError:
        return 1
    return max(1, min(seats, MAX_SELF_SERVE_SEATS))


def _stripe_customer_for(organization: Organization, buyer) -> str:
    """The Stripe customer id for this organization, made if it is not there.

    ``metadata`` carries both ids on purpose.  It is what lets the dj-stripe
    mirror be rebuilt from Stripe alone, which is the whole reason a dropped
    table is a delay rather than a loss (see tasks/complete/team-payments.md).
    """
    existing = organization.djstripe_customers.first()
    if existing is not None:
        return existing.id

    customer = stripe.Customer.create(
        email=organization.email or buyer.email,
        name=organization.name,
        metadata={
            "django_organization_id": str(organization.id),
            "django_user_id": str(buyer.id),
        },
    )
    return customer["id"]


@login_required
@require_POST
def create_checkout_session(request):
    """Create a Stripe Checkout session for the Pro plan."""
    _use_stripe_key()

    pro_price_id = settings.STRIPE_PRO_PRICE_ID
    if not pro_price_id:
        # Same answer as the failure branch below: say so through `messages`
        # and send the reader back to the pricing page, which renders through
        # `web.views.pages.pricing` with its full context.  Rendering the
        # template from here gave it no plans and no comparison rows, and the
        # template has never read an `error` key, so the reader met an empty
        # grid that explained nothing.
        #
        # The reader is not told the setting name.  It means nothing to a
        # buyer, and the operator gets it from the log.
        logger.error("STRIPE_PRO_PRICE_ID is not configured; cannot start a checkout")
        messages.error(request, "Pro is not available for purchase right now.")
        return redirect(reverse("web:pricing"))

    # Seats.  One is the individual purchase and needs no explanation on
    # screen; more than one is a firm.
    #
    # **The first seat is Pro, and the rest are a second, cheaper price.**  A
    # firm pays the Pro figure once and the per-seat figure for every seat
    # after it, which Stripe bills as two line items on one subscription
    # rather than as one tiered price.  Two reasons, and the second is the
    # load-bearing one:
    #
    # - A firm of one is a Pro subscription, which is what it is.  Nothing has
    #   to clamp a seat count to keep somebody from buying a single discounted
    #   seat, because a single seat is priced as Pro by construction.
    # - A Stripe tiered price carries no ``unit_amount``, and Stripe omits the
    #   ``tiers`` array from the Price object unless the caller expands it, so
    #   the mirrored row `accounts.pricing` reads would have no figure in it.  The
    #   page would print no price, or the repo would have to hold a literal —
    #   which is the one thing `accounts.pricing` exists to prevent.
    #
    # ``Organization.seats_bought`` sums the quantities across items, so the
    # 1 + (seats - 1) shape answers as `seats` with no model change.
    seats = _requested_seats(request)
    # `list[Any]`, not `list[dict[...]]`: the stripe stubs declare the
    # parameter as a list of TypedDicts, and an invariant list of plain
    # dicts is not assignable to it.
    line_items: list[Any] = [{"price": pro_price_id, "quantity": 1}]
    if seats > 1:
        if not settings.STRIPE_TEAM_PRICE_ID:
            logger.error("STRIPE_TEAM_PRICE_ID is not configured; cannot sell seats")
            messages.error(request, "Team plans are not available for purchase right now.")
            return redirect(reverse("web:pricing"))
        line_items.append(
            {"price": settings.STRIPE_TEAM_PRICE_ID, "quantity": seats - 1}
        )

    try:
        organization = organization_for_checkout(
            request.user,
            name=(request.POST.get("organization_name") or "").strip(),
        )
        customer_id = _stripe_customer_for(organization, request.user)

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            client_reference_id=str(request.user.id),
            payment_method_types=["card"],
            line_items=line_items,
            mode="subscription",
            allow_promotion_codes=True,
            success_url=request.build_absolute_uri(reverse("web:stripe_success"))
                + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.build_absolute_uri(reverse("web:stripe_cancel")),
        )
        if checkout_session.url is None:
            raise RuntimeError("Stripe checkout session returned no redirect URL")
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        logger.error("Stripe checkout error: %s", e)
        messages.error(request, f"Checkout failed: {e}")
        return redirect(reverse("web:pricing"))


@login_required
def stripe_success(request):
    """Post-checkout success page — sync dj-stripe data."""
    _use_stripe_key()

    session_id = request.GET.get("session_id")
    verified = False
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            # The session names the buyer, so the buyer is who this is checked
            # against.  The customer id belongs to the organization now, and a
            # reader arriving with somebody else's session id must not be told
            # their purchase succeeded.
            verified = str(session.client_reference_id) == str(request.user.id)
            if verified and isinstance(session.customer, str):
                organization = organization_for_checkout(request.user)
                _sync_customer_after_checkout(organization, session.customer)
        except Exception as e:
            logger.warning("stripe_success sync error: %s", e)

    return render(request, "stripe_success.html", {"verified": verified})


def _sync_customer_after_checkout(organization: Organization, stripe_customer_id: str):
    """Pull the customer and its subscriptions back from Stripe, and link them.

    The link is set here rather than in the gate, because a property that
    renders a page must not write.  The webhook does the same work later; this
    is what makes the settings page correct on the first render after a
    purchase instead of on the second.
    """
    try:
        customer, _ = Customer.objects.get_or_create(
            id=stripe_customer_id,
            defaults={"livemode": not settings.DEBUG},
        )
        if not customer.subscriber:
            customer.subscriber = organization
            customer.save(update_fields=["subscriber"])

        stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
        Customer.sync_from_stripe_data(stripe_customer)

        # sync_from_stripe_data rewrites the row from the payload, which
        # carries no subscriber, so the link is set again after it runs.
        customer.refresh_from_db()
        if not customer.subscriber:
            customer.subscriber = organization
            customer.save(update_fields=["subscriber"])

        subs = stripe.Subscription.list(customer=stripe_customer_id, status="all", limit=10)
        for sub_data in subs.auto_paging_iter():
            Subscription.sync_from_stripe_data(sub_data)
    except Exception as e:
        logger.warning("_sync_customer_after_checkout error: %s", e)


def stripe_cancel(request):
    """Checkout cancelled — redirect to pricing with banner."""
    messages.info(request, "Checkout cancelled. You can upgrade anytime.")
    return redirect(reverse("web:pricing"))


@login_required
@require_POST
def create_customer_portal_session(request):
    """Open the Stripe portal for the organization this user administers.

    The portal is where a seat count changes, so it is reached by an
    administrator and not by everybody with a seat.  A member who opened it
    could cancel the firm's subscription, and that is not their decision.
    """
    _use_stripe_key()

    organization = billing_organization(request.user)
    if organization is None:
        return redirect(reverse("web:pricing"))

    customer = organization.djstripe_customers.first()
    if customer is None:
        return redirect(reverse("web:pricing"))

    portal_session = stripe.billing_portal.Session.create(
        customer=customer.id,
        return_url=request.build_absolute_uri(reverse("web:user_settings") + "#account"),
    )
    return redirect(portal_session.url, code=303)


def billing_organization(user) -> Organization | None:
    """The organization whose billing this user may open, or ``None``.

    An administrator (either administering role) manages the firm.  Everybody
    else reaches billing only for an organization of one, which is their own
    purchase and nobody else's.
    """
    for membership in user.memberships.select_related("organization"):
        if membership.is_admin or membership.organization.is_personal:
            return membership.organization
    return None


def sync_subscription_status(user):
    """Re-sync this user's organization from Stripe.

    Called on the settings page so a purchase made in another tab, or a
    cancellation made in the portal, shows on the next render rather than
    waiting for a webhook.  Never raises: a slow Stripe must not cost somebody
    their settings page.
    """
    membership = access_membership(user) or (
        user.memberships.select_related("organization").first()
    )
    if membership is None:
        return
    customer = membership.organization.djstripe_customers.first()
    if customer is None:
        return

    _use_stripe_key()
    try:
        stripe_customer = stripe.Customer.retrieve(customer.id)
        synced = Customer.sync_from_stripe_data(stripe_customer)

        if synced is not None and not synced.subscriber:
            synced.subscriber = membership.organization
            synced.save(update_fields=["subscriber"])

        subs = stripe.Subscription.list(customer=customer.id, status="all", limit=10)
        for sub_data in subs.auto_paging_iter():
            Subscription.sync_from_stripe_data(sub_data)
    except Exception as e:
        logger.warning("sync_subscription_status error: %s", e)
