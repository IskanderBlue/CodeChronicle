"""What the Pro plan costs, read from Stripe.

The price used to be a literal in the pricing view while Stripe held the real
one.  Two numbers for one fact, and only one of them takes money — so the page
could advertise a figure checkout did not charge, and nothing would fail.

This module removes the second number.  It reads the **local** dj-stripe
``Price`` row rather than calling the Stripe API: dj-stripe mirrors the price
and keeps it current through the ``price.updated`` webhook, so a change made
in the Stripe dashboard reaches the page with no deploy and no network call on
the render path.

The row is looked up by ``settings.STRIPE_PRO_PRICE_ID`` — the same setting
``core.views.billing.create_checkout_session`` passes to Stripe.  One setting
means the page and the charge cannot name different prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coloured_logger import Logger
from django.conf import settings
from djstripe.models import Price

logger = Logger(__name__)

#: What to show when the Stripe row cannot be read.  A pricing page that
#: errors because a webhook has not landed is worse than one showing a stale
#: figure, and a blank price is worse than both — so there is always a number.
FALLBACK_AMOUNT = "29"
FALLBACK_CURRENCY = "CAD"
FALLBACK_INTERVAL = "mo"

#: Stripe's interval names, shortened for display beside the figure.
INTERVAL_LABELS = {"day": "day", "week": "wk", "month": "mo", "year": "yr"}


@dataclass(frozen=True)
class ProPrice:
    """The Pro plan's price, ready to render."""

    amount: str
    #: Upper-case ISO code, e.g. "CAD".  Always shown: "$29" is ambiguous to a
    #: Canadian buyer and wrong to an American one.
    currency: str
    interval: str
    #: False when the figure is the fallback rather than Stripe's.  Lets a
    #: caller decide whether to trust it; the page still renders either way.
    from_stripe: bool


def _format_amount(unit_amount: int) -> str:
    """Stripe stores cents. Render whole dollars whole, and cents when present."""
    dollars, cents = divmod(int(unit_amount), 100)
    return f"{dollars}" if cents == 0 else f"{dollars}.{cents:02d}"


def get_pro_price() -> ProPrice:
    """The Pro price from dj-stripe, or the fallback.

    Never raises.  Every failure path — no configured id, no mirrored row, a
    malformed payload — logs and returns the fallback, because this runs on a
    public page whose job is to state a number.
    """
    price_id = settings.STRIPE_PRO_PRICE_ID
    if not price_id:
        logger.warning("STRIPE_PRO_PRICE_ID is not set; pricing page shows the fallback")
        return _fallback()

    try:
        price = Price.objects.filter(id=price_id).first()
    except Exception as exc:  # pragma: no cover - defensive; DB is up on this path
        logger.warning("Could not read the Pro price row: %s", exc)
        return _fallback()

    if price is None:
        logger.warning(
            "No dj-stripe Price row for %s; has the price.updated webhook run?", price_id
        )
        return _fallback()

    data: dict[str, Any] = price.stripe_data or {}
    unit_amount = data.get("unit_amount")
    if unit_amount is None:
        # A metered or tiered price has no flat unit_amount. Nothing sensible
        # to print, so say the fallback rather than invent a figure.
        logger.warning("Price %s has no unit_amount (tiered or metered?)", price_id)
        return _fallback()

    recurring = data.get("recurring") or {}
    interval = INTERVAL_LABELS.get(recurring.get("interval", ""), FALLBACK_INTERVAL)

    return ProPrice(
        amount=_format_amount(unit_amount),
        currency=(data.get("currency") or FALLBACK_CURRENCY).upper(),
        interval=interval,
        from_stripe=True,
    )


def _fallback() -> ProPrice:
    return ProPrice(
        amount=FALLBACK_AMOUNT,
        currency=FALLBACK_CURRENCY,
        interval=FALLBACK_INTERVAL,
        from_stripe=False,
    )
