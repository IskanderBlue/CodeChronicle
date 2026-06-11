"""
Static and settings page views.
"""

from typing import Any

from allauth.account.forms import ChangePasswordForm
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render

from core.models import CodeEdition

from .billing import _sync_subscription_status


def terms_of_service(request):
    """Terms of Service page."""
    return render(request, "terms_of_service.html")


def privacy_policy(request):
    """Privacy Policy page."""
    return render(request, "privacy_policy.html")


def data_sources(request):
    """Data sourcing & coverage page.

    The coverage table is generated from the same tables the search reads,
    so it can't drift from what the product actually serves.  "Edition" here
    means the provenance corpus units — rows with amending regulations
    loaded — not the per-consolidation snapshot rows (``source='elaws'``)
    or legacy MCP entries, which are internal.  Only verified editions are
    listed, mirroring the publish gate (CCM only ships an edition JSON to
    prod once its amendment chain is complete AND its reconstruction's
    discrepancies have been reviewed — the ``verified`` flag).  Deliberately
    ungated (like viewer edition-dates): metadata only, no provision content.
    """
    editions = list(
        CodeEdition.objects.select_related("code")
        .filter(regulations__isnull=False, verified=True)
        .distinct()
        .annotate(
            amendment_count=Count(
                "regulations", filter=Q(regulations__role="amendment"), distinct=True
            )
        )
        .order_by("effective_date")
    )
    consolidation_count = CodeEdition.objects.filter(source="elaws").count()
    # Era-specific source bullets, keyed to what's actually loaded:
    # pre-e-Laws editions (1997 and older) draw their amending regulations
    # from Ontario Gazette scans on the Internet Archive; OBC 2024+ draws on
    # handbooks and corrections downloaded from ontario.ca.
    has_gazette_sources = any(e.year <= 1997 for e in editions)
    has_handbook_sources = any(e.year >= 2024 for e in editions)
    return render(
        request,
        "data_sources.html",
        {
            "editions": editions,
            "consolidation_count": consolidation_count,
            "has_gazette_sources": has_gazette_sources,
            "has_handbook_sources": has_handbook_sources,
        },
    )


def _pricing_plans(user: Any) -> list[dict[str, Any]]:
    """Plan header cards for the content-scoped tier split.

    Name/price/CTA only — the feature comparison lives in
    ``PRICING_COMPARISON`` so each point lines up Free-vs-Pro in one row.
    Price recovered from the original pre-early-access view.
    """
    is_pro = bool(getattr(user, "is_authenticated", False)) and bool(
        getattr(user, "has_active_subscription", False)
    )
    return [
        {"id": "free", "name": "Free", "price": "0", "is_current": not is_pro},
        {"id": "pro", "name": "Pro", "price": "29", "is_current": is_pro},
    ]


# Feature comparison rows (templates/pricing.html): one row per point, the
# Free and Pro cells directly comparable side by side and self-describing
# (no row labels).  ``free=None`` renders as "not included".  Mirrors the
# free-tier gate's scope (core.access / FREE_TIER_CODE_NAMES): Free is
# OBC 2006 in full; Pro is every loaded edition.
PRICING_COMPARISON: list[dict[str, str | None]] = [
    {
        "free": "Ontario Building Code 2006",
        "pro": "Every covered edition (OBC 2006, 2012, and counting)",
    },
    {
        "free": "Amendment history & amending regulations for OBC 2006",
        "pro": "Amendment history & amending regulations",
    },
    {
        "free": "Unlimited searches with a free account — 1/day without one",
        "pro": "Unlimited searches",
    },
    {
        "free": "Provision permalinks & regulation detail within OBC 2006",
        "pro": "Provision permalinks & regulation detail",
    },
    {
        "free": None,
        "pro": "Cross-edition lineage, transition compare & diffs",
    },
    {
        "free": None,
        "pro": "Direct API access",
    },
]


def pricing(request):
    """Pricing and subscription tiers.

    Tracks the free-tier content gate: while FREE_TIER_GATING_ENABLED is
    off, everyone gets everything, so the early-access placeholder (free
    for now, unlimited) is the truthful page.  Flipping the flag swaps in
    the Free/Pro plan cards in the same deploy — the two can't skew.
    """
    if settings.FREE_TIER_GATING_ENABLED:
        plans = _pricing_plans(request.user)
        return render(
            request,
            "pricing.html",
            {
                "plans": plans,
                # Per-column accent flags for the row cells (the boxes carry
                # the border, but rows live outside the plans loop).
                "free_current": plans[0]["is_current"],
                "pro_current": plans[1]["is_current"],
                "comparison": PRICING_COMPARISON,
            },
        )
    return render(request, "pricing_early_access.html")


@login_required
def user_settings(request):
    """User settings page — syncs subscription status from Stripe."""
    if request.user.stripe_customer_id:
        _sync_subscription_status(request.user)

    password_form = ChangePasswordForm(user=request.user)
    return render(
        request,
        "settings.html",
        {
            "password_form": password_form,
        },
    )
