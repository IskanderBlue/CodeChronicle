"""What the Pro plan costs.

Reads the local dj-stripe ``Price`` row, keyed by
``settings.STRIPE_PRO_PRICE_ID`` — the same setting
``web.views.billing.create_checkout_session`` passes to Stripe, so the page
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
    #: The same figure in cents, as Stripe stores it.  The Team card totals a
    #: seat count in the browser, and money arithmetic on the rendered string
    #: is how a page ends up quoting a figure Stripe would not charge.
    cents: int


def checkout_is_configured() -> bool:
    """Whether there is any way to buy Pro.

    The pricing page asks this before it offers a purchase.  It is the same
    test ``web.views.billing.create_checkout_session`` makes before it talks
    to Stripe, so the page cannot offer a button that view refuses.
    """
    return bool(settings.STRIPE_PRO_PRICE_ID)


def format_amount(unit_amount: int) -> str:
    """Stripe stores cents. Render whole dollars whole, and cents when present.

    Public because the Team card renders a *total* — the Pro price plus a seat
    price times a seat count — and that total has to be spelled the same way
    every other figure on the page is.
    """
    dollars, cents = divmod(int(unit_amount), 100)
    return f"{dollars}" if cents == 0 else f"{dollars}.{cents:02d}"


def team_checkout_is_configured() -> bool:
    """Whether a firm can buy seats.

    It answers the same question for the team plan that
    ``checkout_is_configured`` answers for Pro: is there any way to pay?  With
    no way to pay the control is hidden, never offered and then refused.

    **Both ids are needed, because a team checkout sends two line items.**  A
    firm buys the first seat at the Pro price and every seat after it at the
    per-seat price, so a team purchase fails on a missing Pro id exactly as it
    fails on a missing seat id.  ``create_checkout_session`` makes both tests,
    and this makes both for the same reason.
    """
    return bool(settings.STRIPE_PRO_PRICE_ID) and bool(
        getattr(settings, "STRIPE_TEAM_PRICE_ID", "")
    )


def get_pro_price() -> ProPrice | None:
    """The Pro price from dj-stripe, or ``None`` when it cannot be read."""
    return _price_for(settings.STRIPE_PRO_PRICE_ID, "STRIPE_PRO_PRICE_ID")


def get_team_price() -> ProPrice | None:
    """The per-seat team price, or ``None`` when it cannot be read.

    Read exactly as the Pro price is, from the same mirrored table, with the
    same rule: no fallback figure.  The page multiplies this by the seat count
    the buyer chose, and Stripe multiplies the same figure by the same
    quantity, so the two cannot disagree.
    """
    return _price_for(settings.STRIPE_TEAM_PRICE_ID, "STRIPE_TEAM_PRICE_ID")


def _price_for(price_id: str, setting_name: str) -> ProPrice | None:
    """One mirrored ``Price`` row, rendered, or ``None``.

    Never raises.  Every failure path — no configured id, no mirrored row, a
    payload with no flat amount — logs and answers ``None``, because this runs
    on a public page whose job is to state a number correctly or not at all.
    """
    if not price_id:
        logger.warning("%s is not set; the pricing page cannot offer that plan", setting_name)
        return None

    try:
        price = Price.objects.filter(id=price_id).first()
    except Exception as exc:  # pragma: no cover - defensive; DB is up on this path
        logger.warning("Could not read the price row for %s: %s", setting_name, exc)
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
        amount=format_amount(unit_amount),
        cents=int(unit_amount),
        currency=(data.get("currency") or "").upper(),
        interval=INTERVAL_LABELS.get(stripe_interval, stripe_interval),
    )
