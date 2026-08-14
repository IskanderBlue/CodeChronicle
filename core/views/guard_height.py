"""The guard-height article — one question, and every change to the answer.

Why this page exists.  A screenshot of a search box proves nothing, and a
reader who works with the code can check a provision against a source they
trust.  So the article asks one question a practitioner answers wrong, then
walks the changes that moved the answer, rendered by the product itself.

**The page is built out of changes, not out of texts.**  It opens on the
oldest text in full, and every section after it is one amendment shown as a
redline through ``provenance/_compare_pane.html`` — the same panes ``/compare/``
draws, prepared the same way by ``core.views.compare._side``.  A list of six
texts made the reader do the diffing; this is the product doing it, which is
also the thing the product is for.

**Nothing here is transcribed.**  Each side fetches a real version and renders
through the shipping partials, so a corpus that changes changes the article.
The attestation band on the opening text is the shipping band, not a picture of
one.  Same reasoning as ``core.views.landing._specimen``, and it reuses that
page's helper (``_provenance_result``) to say so in code.

**The article is not a gated surface, and it does not need an exception.**
``core.access`` answers one question — may this reader open this *edition* —
and the partials never ask it.  A view decides and sets ``locked_edition_name``;
the partials render what the view says.  This view leaves that flag unset, so
the OBC 1997 text renders for a logged-out reader.  Do not add a provision- or
version-level axis to ``core.access`` for this: that module works because
there is one question to ask, and this page would be its only caller.

What *does* stay gated is what each section links to — the permalink, and the
full comparison page.  OBC 1997 is outside ``FREE_TIER_CODE_NAMES``, so a
comparison with a 1997 side lands on the locked-edition teaser.  ``locked``
records that, and the template says so rather than springing it on the reader.

**OBC 2024 is not in the corpus** and this view does not pretend otherwise.
The current text is quoted in the template from the Compendium, under the
King's Printer attribution, and it is the one thing on the page the product did
not render.  See ``tasks/ao-proof-content-edition-comparison.md``.
"""

from datetime import date
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from api.formatters import _diff_html_content, diff_similarity
from core.access import edition_allowed
from core.compare import REDLINE_FLOOR, PreparedPair, version_ref
from core.cross_refs import annotate_versions
from core.http_cache import corpus_conditional
from core.models import CodeEditionProvisionVersion
from core.permalinks import provision_permalink_url
from core.seo import last_governed_day

from .compare import _side
from .regulation import _provenance_result

#: One version of the guard-height article, as
#: ``(edition_id, division, provision_id, version)``.
Ref = tuple[str, str, str, int]

#: The oldest text, shown in full because the article starts there.  Everything
#: after it is a change *to* it.
OPENING: Ref = ("1997", "", "9.8.8.2.", 0)

#: Every amendment that produced a new text, oldest first, as
#: ``(slug, earlier, later)``.  The slug is how the template addresses one:
#: each section carries prose about that particular change, so the sections
#: cannot be a loop, and a numeric index would not survive a corpus that grows
#: a version in the middle.
#:
#: The provision *number* moves across the first pair: guard height is 9.8.8.2.
#: in OBC 1997 and 9.8.8.3. from OBC 2006 onward, where 9.8.8.2. becomes "Loads
#: on Guards".  That is the article's sharpest fact, so the pairs are written
#: out rather than derived from a single id — no query could find these six by
#: number.
#:
#: OBC 1997 carries no division letter; the later editions are Division B.
#: ``provision_permalink_url`` and ``core.compare`` both route around the empty
#: one.
TRANSITIONS: tuple[tuple[str, Ref, Ref], ...] = (
    ("renumbered", ("1997", "", "9.8.8.2.", 0), ("2006", "B", "9.8.8.3.", 0)),
    ("measured", ("2006", "B", "9.8.8.3.", 0), ("2006", "B", "9.8.8.3.", 1)),
    ("split", ("2006", "B", "9.8.8.3.", 1), ("2012", "B", "9.8.8.3.", 0)),
    ("exterior", ("2012", "B", "9.8.8.3.", 0), ("2012", "B", "9.8.8.3.", 1)),
    ("resolved", ("2012", "B", "9.8.8.3.", 1), ("2012", "B", "9.8.8.3.", 2)),
)

#: There was briefly an ``ASIDES`` tuple beside this one, carrying OBC 2012
#: B 3.4.6.6. — Part 3's exit-stair guard, where "1 070 mm around landings"
#: had been one sentence about exit stairs since OBC 2006.  It was gathered to
#: argue that 9.8.8.3. (5)(b) carried a narrower meaning than it said.  That
#: argument was wrong: (2) and (5)(b) are both minimums, so they never
#: conflicted, and the higher one simply governs.  The section went, and the
#: machinery went with it.  Do not bring either back.

#: Title and description.  Set here rather than in a ``{% block title %}``:
#: ``base.html`` resolves the title as ``{% firstof meta_title default_title %}``
#: and ``partials/_social_meta.html`` builds the Open Graph and Twitter tags
#: from the same two names.  Overriding the block would change the browser tab
#: and leave every forwarded link carrying the generic site card — and this
#: article travels by being forwarded.
META_TITLE = (
    "Minimum guard height for a stair inside a house in Ontario, "
    "1998 to today"
)
META_DESCRIPTION = (
    "The Ontario Building Code sets the flight and the landing of a stair "
    "separately. It allowed 800 mm on the flight until 2006, and from 2014 to "
    "2022 it required 1 070 mm around the landing. Every text, its in-force "
    "dates, and what each amendment changed."
)


def _version(ref: Ref) -> CodeEditionProvisionVersion | None:
    """One version, or ``None`` when it is not loaded.

    ``None`` rather than an exception: a fresh development database has no
    corpus, and an article that 500s there is harder to work on than one that
    renders its prose and skips the specimens.  The template counts what it
    got, and the tests pin the numbers.
    """
    edition_id, division, provision_id, number = ref
    return (
        CodeEditionProvisionVersion.objects.select_related(
            "provision__edition__code"
        )
        .filter(
            provision__edition__code__code="OBC",
            provision__edition__edition_id=edition_id,
            provision__division=division,
            provision__provision_id=provision_id,
            version=number,
        )
        .first()
    )


def _load() -> dict[Ref, CodeEditionProvisionVersion]:
    """Every version the page needs, fetched once and annotated once.

    Once, because the transitions overlap: five pairs name six versions, and a
    version fetched twice would be annotated twice and diffed against two
    different objects holding the same text.
    """
    refs = {OPENING, *(ref for _, a, b in TRANSITIONS for ref in (a, b))}
    loaded: dict[Ref, CodeEditionProvisionVersion] = {}
    for ref in refs:
        version = _version(ref)
        if version is None:
            continue
        # Citations become permalinks, read at this version's own commencement
        # — the same date the band is built at, so a link and the band beside
        # it cannot describe two different moments.  Per version, because
        # ``annotate_versions`` scopes the links to one edition and this page
        # spans three.
        annotate_versions(
            [version],
            version.provision.edition.code_name,
            on_date=version.effective_date,
        )
        loaded[ref] = version
    return loaded


def _opening(version: CodeEditionProvisionVersion, user: Any) -> dict[str, Any]:
    """The oldest text in full, with the attestation band above it."""
    provision = version.provision
    code_name = provision.edition.code_name
    return {
        "provenance": _provenance_result(
            provision,
            version,
            code_name,
            provision.division,
            provision.provision_id,
            user,
        ),
        "version": version,
        "edition_year": provision.edition.year,
        "provision_id": provision.provision_id,
        # The last day this text actually governed.  The stored window is
        # half-open, so the end date names the first day it did *not* — see
        # ``core.seo.last_governed_day``, which the whole product calls rather
        # than subtracting a day in three places.
        "last_day": last_governed_day(version.ineffective_date),
        "url": provision_permalink_url(
            code_name, provision.division, provision.provision_id, version.version
        ),
        "locked": not edition_allowed(user, code_name),
    }


def _transition(
    earlier: CodeEditionProvisionVersion,
    later: CodeEditionProvisionVersion,
    user: Any,
) -> dict[str, Any]:
    """One amendment, as the comparison page would draw it.

    The redline floor is applied here too.  Below it ``/compare/`` shows two
    plain panes and says why, and an article that redlined a pair the product
    refuses to redline would be showing the reader something the product does
    not do.  Every pair on this page currently clears the floor; the rule is
    here so a reloaded corpus cannot quietly make that false.
    """
    similarity = diff_similarity(earlier.html, later.html)
    redline = similarity >= REDLINE_FLOOR
    old_diff, new_diff = (None, None)
    if redline:
        # Diff the linked bodies, so the citations survive into the redline.
        # The differ passes tags through untouched and compares words only, so
        # the anchors change neither what is marked nor where.
        old_diff, new_diff = _diff_html_content(
            earlier.linked_html or earlier.html,
            later.linked_html or later.html,
        )
    side_a = _side(earlier, "A")
    side_b = _side(later, "B")
    return {
        "date": later.effective_date,
        "side_a": side_a,
        "side_b": side_b,
        # The same two dicts as a list, because the side rows loop over them
        # and a Django `for` cannot take a tuple literal.
        "sides": [side_a, side_b],
        "old_diff": old_diff,
        "new_diff": new_diff,
        "redline": redline,
        "similarity_pct": round(similarity * 100),
        "compare_url": PreparedPair(version_ref(earlier), version_ref(later)).url,
        # Whether that link lands on the comparison or on the locked-edition
        # teaser.  ``/compare/`` gates both sides, so one gated side locks the
        # pair.  The article states this; it does not let the reader discover
        # it by clicking.
        "locked": any(
            not edition_allowed(user, version.provision.edition.code_name)
            for version in (earlier, later)
        ),
    }


@corpus_conditional
def guard_height(request: HttpRequest) -> HttpResponse:
    """The article.  Public, indexed, and listed in ``STATIC_PAGE_NAMES``."""
    loaded = _load()
    opening = (
        _opening(loaded[OPENING], request.user) if OPENING in loaded else None
    )
    transitions = {
        slug: _transition(loaded[a], loaded[b], request.user)
        for slug, a, b in TRANSITIONS
        if a in loaded and b in loaded
    }
    return render(
        request,
        "guard_height.html",
        {
            "opening": opening,
            "transitions": transitions,
            "retrieved": date.today(),
            "meta_title": META_TITLE,
            "meta_description": META_DESCRIPTION,
            "canonical_path": reverse("core:guard_height"),
        },
    )
