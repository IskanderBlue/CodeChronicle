"""
Static and settings page views.
"""

from typing import Any

from allauth.account.forms import ChangePasswordForm
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render

from api.auth import API_SEARCHES_BEFORE_THROTTLE
from core.access import api_access_allowed
from core.models import CodeEdition, Membership
from core.pricing import (
    checkout_is_configured,
    format_amount,
    get_pro_price,
    get_team_price,
    team_checkout_is_configured,
)
from core.seo import TITLE_SUFFIX
from core.teams import access_membership, administered_organizations
from core.views.api_keys import MAX_ACTIVE_KEYS, NEW_TOKEN_SESSION_KEY
from core.views.billing import MAX_SELF_SERVE_SEATS, sync_subscription_status


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


#: The seat count the Team card opens on.  Two is the smallest thing that is
#: a firm, so it is both the input's starting value and the count the
#: server-rendered total is for.  One constant, because a card that opens
#: saying "$499 for 3 seats" over an input reading 2 is worse than either.
TEAM_STARTING_SEATS = 2


def _pricing_plans(user: Any) -> list[dict[str, Any]]:
    """Plan header cards for the content-scoped tier split.

    Name, price, CTA — and the features the column adds, from
    ``PRICING_FEATURES`` and ``PRICING_INHERITS``.  A column lists only what
    it adds to the one before it, under "Everything in <that column>", so no
    point is written twice.

    Every figure comes from Stripe (``core.pricing``), never a literal here.
    Free is genuinely zero and has no Stripe price, so it borrows Pro's
    currency and interval for the cards to read as one statement.

    ``price`` is ``None`` when Stripe cannot be read, and there is no stand-in
    figure.  ``can_buy`` answers a different question — whether a purchase is
    possible at all.  A missing mirrored row still leaves checkout working;
    only an unset price id does not.

    **Which column reads as current** is decided by where the access comes
    from, not by the fact of having it.  A person with a seat in a firm is on
    Team, and somebody who bought alone is on Pro; asking only
    ``has_active_subscription`` would mark the same column for both and tell
    one of them something false.

    **Team's figure is a total, not a rate.**  It is billed as two Stripe
    line items — the Pro price for the first seat, ``extra_price_cents`` for
    each seat after it — and the card adds them up for the seat count on
    screen.  See ``core.views.billing.create_checkout_session`` for why two
    line items beat one tiered price.

    **Custom carries no price and no ``can_buy``.**  It is not something the
    page can sell, and a figure beside it would be a guess at a quote.
    """
    signed_in = bool(getattr(user, "is_authenticated", False))
    has_access = signed_in and bool(getattr(user, "has_active_subscription", False))

    seat = access_membership(user) if signed_in else None
    on_team = seat is not None and not seat.organization.is_personal

    pro = get_pro_price()
    team = get_team_price()
    currency = pro.currency if pro else ""
    interval = pro.interval if pro else ""

    plans: list[dict[str, Any]] = [
        {
            "id": "free",
            "name": "Free",
            "price": "0",
            "currency": currency,
            "interval": interval,
            "per_seat": False,
            "is_current": not has_access,
            "can_buy": True,
        },
        {
            "id": "pro",
            "name": "Pro",
            "price": pro.amount if pro else None,
            "price_cents": pro.cents if pro else None,
            "currency": currency,
            "interval": interval,
            "per_seat": False,
            "is_current": has_access and not on_team,
            "can_buy": checkout_is_configured(),
        },
        {
            "id": "team",
            # **The headline is the whole bill, and it moves with the seat
            # count.**  A team subscription is the Pro price once plus the seat
            # price for every seat after it, and printing that as two figures
            # made the reader do the arithmetic to learn what they would pay.
            # ``price`` is the total at the starting seat count, rendered by
            # the server so the card states a figure with no JavaScript;
            # ``price_cents`` and ``extra_price_cents`` let the browser
            # re-total it as the reader changes the count.  The maths runs on
            # cents, never on the rendered string.
            "price": (
                format_amount(pro.cents + team.cents * (TEAM_STARTING_SEATS - 1))
                if pro and team
                else (pro.amount if pro else None)
            ),
            "price_cents": pro.cents if pro else None,
            "name": "Team",
            "currency": currency,
            "interval": interval,
            "per_seat": True,
            # The second figure, printed under the first.  ``None`` when the
            # seat price cannot be read, on the same no-stand-in rule as every
            # other figure here.
            "extra_price_cents": team.cents if team else None,
            "is_current": on_team,
            "can_buy": team_checkout_is_configured(),
        },
        {
            "id": "custom",
            "name": "Custom",
            "price": None,
            "currency": "",
            "interval": "",
            "per_seat": False,
            "is_current": False,
            "can_buy": False,
        },
    ]
    # The features are attached here rather than looked up in the template,
    # so the template loops over one list and knows nothing about plan ids.
    for plan in plans:
        plan["features"] = PRICING_FEATURES[plan["id"]]
        plan["inherits"] = PRICING_INHERITS[plan["id"]]
    return plans


# What each column adds to the one before it (templates/pricing.html).
#
# Free mirrors the gate's scope (core.access / FREE_TIER_CODE_NAMES): OBC 2006
# in full.  Pro is every loaded edition.
#
# **The columns build, they do not repeat.**  A seat buys exactly what Pro
# buys, and Custom buys exactly what Team buys, so a side-by-side matrix said
# the same six sentences three times over — free to drift three ways, and
# with nothing to compare across a row.  Each column now lists only what it
# adds, under "Everything in <the column before>".
#
# The one number here is the API allowance.  It is stated because Free
# promises unlimited searches, and a reader who meets that and a bare "Direct
# API access" concludes the API is unlimited too.  Past the allowance the API
# slows rather than stops (API_SEARCHES_BEFORE_THROTTLE, api/auth.py), so the
# line says "then slower" and not "then no".  It counts API searches only — a
# subscriber's own reading on the website never spends it.
#
# No coverage dates here on purpose: the masthead already prints the real
# span from CorpusCurrency on every page, and a hand-written date in this
# constant would be a second figure free to drift from it.
PRICING_FEATURES: dict[str, list[str]] = {
    # Free is scoped to one edition, and every line says so.  The scope is
    # the argument for paying, so it is never left implied.
    # **The first line names the edition; nothing below it repeats the scope.**
    # A column headed "Ontario Building Code 2006" has already said what a free
    # reader can see, and "within OBC 2006" on every line after it reads as
    # four separate restrictions rather than one.
    "free": [
        "Ontario Building Code 2006",
        "Amendment history & amending regulations",
        "Provision permalinks & regulation detail",
        # Comparing two versions of one provision is free, and was not stated.
        # `edition_allowed` gates per edition, so both sides of a comparison
        # inside the free edition pass — a free reader really does get the
        # diff.  What they cannot do is put two editions side by side.
        "Compare versions & see the diff",
        "Unlimited searches with a free account — 1/day without one",
    ],
    # OBC 1997 leads, and is named before the other two.  It is the edition
    # whose text left e-Laws before the consolidation era, so it is the only
    # one a reader cannot get anywhere else — which makes it the reason to
    # pay.  The row used to read "OBC 2006, 2012, and counting" and omitted it
    # entirely, so the page that had to make the argument did not make it.
    # "Amendment history & permalinks across all of them" is gone: the first
    # line widens the corpus, and every Free line then applies to the wider
    # corpus by inheritance.  Restating one of them said nothing new.
    "pro": [
        "Every covered edition — OBC 1997, 2006 and 2012",
        "Compare across editions — lineage and transition diffs",
        f"Direct API access — {API_SEARCHES_BEFORE_THROTTLE} searches a day, then slower",
    ],
    # What a firm adds is how it buys, not what anybody can read.
    "team": [
        "Seats on one invoice — add or remove one at any time",
        "A team panel: invite, remove, and see who holds a seat",
    ],
    # Custom says what to do, not what it includes.  Everything it includes
    # is negotiated, so a list would be a guess at somebody else's quote — and
    # an "Everything in Team, plus" line over a single bullet claimed a
    # difference the page cannot state.
    "custom": [
        "Contact us to discuss your needs.",
    ],
}

#: What each column inherits, printed above its own list.  ``None`` for Free,
#: which starts the chain.
PRICING_INHERITS: dict[str, str | None] = {
    "free": None,
    "pro": "Everything in Free, plus",
    "team": "Everything in Pro, plus",
    # Custom inherits nothing on screen.  What it adds is paperwork, and a
    # heading promising additions over one line of prose read as an error.
    "custom": None,
}


# What is coming, in the order it is coming (templates/pricing.html, the
# "roadmap" anchor).  The template numbers these from their position, so a
# reorder is an edit to this list alone.  The six items used to be six
# hand-written blocks each carrying its own printed number, where a reorder
# meant renumbering by hand and a promise could end up listed twice.
#
# Delivered work leaves the list.  A roadmap that still names what shipped is
# not a roadmap, and "Ontario codes back to 1997" sat at the top of it for
# months after OBC 1997 went live.
PRICING_ROADMAP: list[str] = [
    "Ontario codes back to 1975",
    "Current Ontario code (OBC2024)",
    "Supplementary standards for 2012, 2006",
    "National codes",
    "Other provincial codes",
]


def pricing(request):
    """Pricing and subscription tiers."""
    plans = _pricing_plans(request.user)
    return render(
        request,
        "pricing.html",
        {
            # Page title, description and social card, from one source each.
            # The description names no figure: the price comes from the
            # mirrored Stripe row (core.pricing), and a number written here
            # would outlive the next change in the dashboard.
            "meta_title": f"Pricing{TITLE_SUFFIX}",
            "social_title": "Pricing",
            "meta_description": (
                "What a CodeChronicle subscription unlocks: every edition in "
                "the corpus, not only the free one, with the amendment history "
                "behind each provision."
            ),
            "plans": plans,
            "roadmap": PRICING_ROADMAP,
            # The seat control lives in the Team card and needs its ceiling.
            "team_max_seats": MAX_SELF_SERVE_SEATS,
            "team_starting_seats": TEAM_STARTING_SEATS,
        },
    )


@login_required
def user_settings(request):
    """User settings page — syncs subscription status from Stripe."""
    sync_subscription_status(request.user)

    password_form = ChangePasswordForm(user=request.user)

    # The API section is drawn only for a subscriber, because a key issued to
    # anybody else is a key the API refuses.  The same test runs in
    # core.views.api_keys, so the section and the control agree.
    api_access = api_access_allowed(request.user)
    api_keys = (
        list(request.user.api_keys.filter(revoked_at__isnull=True)) if api_access else []
    )
    # The plain token, put here by the POST that made it, and taken out as it
    # is read.  A refresh of this page shows the key list without it, which is
    # the whole point: there is one copy and one chance to keep it.
    new_api_token = request.session.pop(NEW_TOKEN_SESSION_KEY, None)

    # The team panel is drawn only for somebody who administers an
    # organization that holds more than themselves.  A reader who bought for
    # themselves has an organization of one, and must never meet the word.
    teams = [
        organization
        for organization in administered_organizations(request.user)
        if not organization.is_personal
    ]
    team_roles = [
        (Membership.Role.MEMBER.value, "Member — a seat, and full access"),
        (Membership.Role.ADMIN.value, "Admin — a seat, and manages the team"),
        (Membership.Role.BILLING.value, "Billing only — no seat, and no access"),
    ]

    return render(
        request,
        "settings.html",
        {
            "password_form": password_form,
            "api_access": api_access,
            "api_keys": api_keys,
            "api_key_limit": MAX_ACTIVE_KEYS,
            "new_api_token": new_api_token,
            "teams": teams,
            "team_roles": team_roles,
        },
    )
