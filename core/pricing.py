"""What the Pro plan costs.

Reads the local dj-stripe ``Price`` row, keyed by
``settings.STRIPE_PRO_PRICE_ID`` — the same setting
``core.views.billing.create_checkout_session`` passes to Stripe, so the page
and the charge cannot name different prices.  The row is a mirror that the
``price.updated`` webhook keeps current, so a change made in the Stripe
dashboard reaches the page with no deploy and no network call on the render
path.

**There is no fallback figure.**  When the row cannot be read,
``get_pro_price`` answers ``None`` and the page states no price.  A stand-in
number would advertise the old price after a change while checkout took the
new one.

The price fails to read in two ways, and they need different answers:

- **The price id is set and the row is missing** — a webhook that has not
  landed, or a restored database.  Checkout still works, because it sends the
  id to Stripe and Stripe is the authority.  There is a way to pay, so the
  page points at checkout for the figure.
- **The price id is empty.**  ``create_checkout_session`` answers an error, so
  there is no way to pay, and the page offers no purchase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coloured_logger import Logger
from django.conf import settings
from djstripe.models import Price

logger = Logger(__name__)

#: Stripe's interval names, shortened for display beside the figure.  An
#: interval Stripe adds later is printed as Stripe spells it rather than
#: guessed at.
INTERVAL_LABELS = {"day": "day", "week": "wk", "month": "mo", "year": "yr"}


@dataclass(frozen=True)
class ProPrice:
    """The Pro plan's price, ready to render.  Always from Stripe."""

    amount: str
    #: Upper-case ISO code, e.g. "CAD".  Always shown: "$29" is ambiguous to a
    #: Canadian buyer and wrong to an American one.
    currency: str
    interval: str


def checkout_is_configured() -> bool:
    """Whether there is any way to buy Pro.

    The pricing page asks this before it offers a purchase.  It is the same
    test ``core.views.billing.create_checkout_session`` makes before it talks
    to Stripe, so the page cannot offer a button that view refuses.
    """
    return bool(settings.STRIPE_PRO_PRICE_ID)


def _format_amount(unit_amount: int) -> str:
    """Stripe stores cents. Render whole dollars whole, and cents when present."""
    dollars, cents = divmod(int(unit_amount), 100)
    return f"{dollars}" if cents == 0 else f"{dollars}.{cents:02d}"


def get_pro_price() -> ProPrice | None:
    """The Pro price from dj-stripe, or ``None`` when it cannot be read.

    Never raises.  Every failure path — no configured id, no mirrored row, a
    payload with no flat amount — logs and answers ``None``, because this runs
    on a public page whose job is to state a number correctly or not at all.
    """
    price_id = settings.STRIPE_PRO_PRICE_ID
    if not price_id:
        logger.warning("STRIPE_PRO_PRICE_ID is not set; the pricing page cannot offer Pro")
        return None

    try:
        price = Price.objects.filter(id=price_id).first()
    except Exception as exc:  # pragma: no cover - defensive; DB is up on this path
        logger.warning("Could not read the Pro price row: %s", exc)
        return None

    if price is None:
        logger.warning(
            "No dj-stripe Price row for %s; has the price.updated webhook run?", price_id
        )
        return None

    data: dict[str, Any] = price.stripe_data or {}
    unit_amount = data.get("unit_amount")
    if unit_amount is None:
        # A metered or tiered price has no flat unit_amount. Nothing sensible
        # to print, so say nothing rather than invent a figure.
        logger.warning("Price %s has no unit_amount (tiered or metered?)", price_id)
        return None

    recurring = data.get("recurring") or {}
    stripe_interval: str = recurring.get("interval") or ""

    return ProPrice(
        amount=_format_amount(unit_amount),
        currency=(data.get("currency") or "").upper(),
        interval=INTERVAL_LABELS.get(stripe_interval, stripe_interval),
    )
