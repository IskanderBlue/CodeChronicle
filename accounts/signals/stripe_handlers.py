"""
dj-stripe webhook signal handlers for Customer/Subscription reconciliation.

Uses the djstripe_receiver decorator (dj-stripe 2.9+) instead of the legacy
@webhooks.handler decorator.
"""

from coloured_logger import Logger
from djstripe.event_handlers import djstripe_receiver
from djstripe.models import Customer

from core.models import Organization

logger = Logger(__name__)


@djstripe_receiver("customer.subscription.created")
def handle_subscription_created(sender, event, **kwargs):
    """Link the mirrored customer to the organization that is paying.

    The link comes from ``metadata.django_organization_id``, written on the
    Stripe customer when checkout created it (``web.views.billing``).  Stripe
    is asked rather than guessed at, which is the same property that lets the
    whole dj-stripe mirror be rebuilt from Stripe alone.

    A customer with no such metadata is left unlinked.  An unlinked customer
    reads as nobody's subscription, which is a state the gate already handles;
    a wrongly linked one would hand a stranger every edition.
    """
    data = event.data.get("object", {})
    stripe_customer_id = data.get("customer")
    if not stripe_customer_id:
        return

    customer = Customer.objects.filter(id=stripe_customer_id).first()
    if customer is None or customer.subscriber:
        return

    organization_id = (customer.stripe_data or {}).get("metadata", {}).get(
        "django_organization_id"
    )
    if not organization_id:
        logger.warning(
            "Stripe customer %s names no organization; leaving it unlinked",
            stripe_customer_id,
        )
        return

    organization = Organization.objects.filter(id=organization_id).first()
    if organization is None:
        logger.warning(
            "Stripe customer %s names organization %s, which does not exist",
            stripe_customer_id,
            organization_id,
        )
        return

    customer.subscriber = organization
    customer.save(update_fields=["subscriber"])
    logger.info(
        "Linked dj-stripe Customer %s to organization %s",
        stripe_customer_id,
        organization.name,
    )


@djstripe_receiver("customer.subscription.deleted")
def handle_subscription_cancelled(sender, event, **kwargs):
    """Log subscription cancellation. dj-stripe handles status update automatically."""
    data = event.data.get("object", {})
    logger.info(
        "Subscription %s cancelled for customer %s",
        data.get("id"),
        data.get("customer"),
    )


@djstripe_receiver("invoice.payment_failed")
def handle_payment_failed(sender, event, **kwargs):
    """Log payment failure for monitoring."""
    data = event.data.get("object", {})
    logger.warning(
        "Payment failed for customer %s, invoice %s",
        data.get("customer"),
        data.get("id"),
    )
