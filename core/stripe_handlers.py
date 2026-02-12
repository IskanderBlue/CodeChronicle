"""
dj-stripe webhook signal handlers for Customer/Subscription reconciliation.

Uses the djstripe_receiver decorator (dj-stripe 2.9+) instead of the legacy
@webhooks.handler decorator.
"""

from coloured_logger import Logger
from djstripe.event_handlers import djstripe_receiver

logger = Logger(__name__)


@djstripe_receiver("customer.subscription.created")
def handle_subscription_created(sender, event, **kwargs):
    """Reconcile Customer.subscriber with User when a subscription is created."""
    from djstripe.models import Customer

    from core.models import User

    data = event.data.get("object", {})
    stripe_customer_id = data.get("customer")
    if not stripe_customer_id:
        return

    customer = Customer.objects.filter(id=stripe_customer_id).first()
    if customer and not customer.subscriber:
        user = User.objects.filter(stripe_customer_id=stripe_customer_id).first()
        if user:
            customer.subscriber = user
            customer.save(update_fields=["subscriber"])
            logger.info("Linked dj-stripe Customer %s to User %s", stripe_customer_id, user.email)


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
