"""
Static and settings page views.
"""

from typing import Any

from allauth.account.forms import ChangePasswordForm
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render

from core.models import CodeEdition
from core.pricing import get_pro_price

from .billing import _sync_subscription_status


def terms_of_service(request):
    """Terms of Service page."""
    return render(request, "terms_of_service.html")


def privacy_policy(request):
    """Privacy Policy page."""
    return render(request, "privacy_policy.html")


def verification_guide(request):
    """How to read the attestation rail — symbol key + a worked example of each
    status configuration.

    The examples render through the same ``_attestation_rail.html`` partial the
    search results use (data from ``core.rail_examples`` via the ``rail_legend``
    template tag), so the guide can't drift from the rail that ships. Static
    reference, ungated like the data-sources page — metadata only, no provision
    content. Opened in a new tab from each rail's "How to read this" link.
    """
    return render(request, "verification_guide.html")


def list_punctuation(request):
    """Editorial convention: how a phrase inserted into a list is punctuated.

    An amend-add directive names the words to insert and says nothing about the
    mark that joins them, so the mapping supplies one by a fixed convention
    (mirror the neighbouring separator, with non-peer exceptions).  That mark is
    the one thing on a reconstructed provision the regulation did not put there,
    so it gets stated publicly rather than only in the producer's code.

    Static reference, ungated like the verification guide and data-sources page
    — convention only, no provision content.  Copy source of truth is
    ``tasks/complete/list-insertion-punctuation.md``; the rule itself lives in CCM
    (``amendment/html/insert.py``).  CCM ``tasks/supplied-separator-note.md``
    adds the matching per-provision disclosure, which will link here.
    """
    return render(request, "list_punctuation.html")


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

    The Pro figure comes from Stripe (``core.pricing``), not from a literal
    here: the literal and the Stripe price were two numbers for one fact, and
    only one of them took money.  Free is genuinely zero and has no Stripe
    price, so it carries the same currency and interval as Pro for the two
    cards to read as a pair.
    """
    is_pro = bool(getattr(user, "is_authenticated", False)) and bool(
        getattr(user, "has_active_subscription", False)
    )
    pro = get_pro_price()
    return [
        {
            "id": "free",
            "name": "Free",
            "price": "0",
            "currency": pro.currency,
            "interval": pro.interval,
            "is_current": not is_pro,
        },
        {
            "id": "pro",
            "name": "Pro",
            "price": pro.amount,
            "currency": pro.currency,
            "interval": pro.interval,
            "is_current": is_pro,
        },
    ]


# Feature comparison rows (templates/pricing.html): one row per point, the
# Free and Pro cells directly comparable side by side and self-describing
# (no row labels).  ``free=None`` renders as "not included".  Mirrors the
# free-tier gate's scope (core.access / FREE_TIER_CODE_NAMES): Free is
# OBC 2006 in full; Pro is every loaded edition.
PRICING_COMPARISON: list[dict[str, str | None]] = [
    # OBC 1997 leads the Pro cell, and is named before the other two.  It is
    # the edition whose text left e-Laws before the consolidation era, so it
    # is the only one a reader cannot get anywhere else — which makes it the
    # reason to pay.  The row used to read "OBC 2006, 2012, and counting" and
    # omitted it entirely, so the page that had to make the argument was the
    # one page that did not make it.
    #
    # No coverage dates here on purpose: the masthead already prints the real
    # span from CorpusCurrency on every page, and a hand-written date in this
    # constant would be a second figure free to drift from it.
    {
        "free": "Ontario Building Code 2006",
        "pro": "Every covered edition — OBC 1997, 2006 and 2012",
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
    """Pricing and subscription tiers."""
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
