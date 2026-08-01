"""Public front page — what CodeChronicle is, and why its text can be trusted.

Every quantity on this page is read from the same tables the search runs
against, never hand-set, for the same reason the Sources page and the masthead
currency stamp are: a landing page that overstates coverage is the one page a
prospective subscriber checks against reality first.

Scope matches the Sources page exactly — ``verified`` editions that actually
have regulations loaded.  ``verified`` is the publish gate: CCM only ships an
edition once its amendment chain is complete *and* the two independent
reconstructions of it have been diffed and every remaining difference
classified.  So "an edition is listed here" and "that edition cleared the
parity review" are the same statement, which is what lets the page describe
the review in the present tense without keeping a second set of numbers.

The route is deliberately two URLs onto one view:

* ``/``       — the front door.  Signed-in readers are sent straight to the
  search page; they have already been sold, and a marketing page between them
  and the tool is friction on every visit.
* ``/about/`` — the same page, no redirect, so the explanation stays reachable
  for a signed-in reader (and linkable from the footer) instead of being
  visible only to logged-out visitors.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any, TypedDict

from django.db.models import Count, Max, Min, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.access import edition_allowed, free_tier_code_names
from core.cross_refs import annotate_versions
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    Consolidation,
    CorpusCurrency,
    Regulation,
)

from .regulation import _provenance_result
from .search import EXAMPLE_QUERIES

#: The provision the section III specimens are drawn from — Article 1.1.2.4. of
#: Division A in OBC 2006, at version 2.
#:
#: One provision, not five hand-drawn pictures.  Rows 02 and 04 render the
#: *shipping* partials against this record, so a specimen cannot promise a
#: surface the product no longer has; row 03 already did this through
#: ``rail_legend``.  It earns the job on three counts: it is inside the free
#: tier, so the "open it" link works for the visitor reading the page; it has a
#: three-regulation amendment chain and a mapped OBC 1997 predecessor, so the
#: provenance rail shows lineage, base and amendments rather than a stub; and
#: one of its citations (to 1.3.1.2.) resolves to two candidate versions, which
#: is the fan-out case row 04 is about.  A different provision would need all
#: three properties again.
SPECIMEN: tuple[str, str, str, int] = ("2006", "A", "1.1.2.4.", 2)

#: The date the specimen is rendered at.  Fan-out is a function of the date —
#: it appears when the cited provision changed inside the citing version's life
#: — so this is chosen to land in the window where 1.3.1.2. has two candidates.
SPECIMEN_DATE = date(2010, 6, 1)

#: The query the section III row 01 specimen arrives prefilled with.  The row
#: renders the real search form (``partials/_search_form.html``) in handoff
#: mode, so pressing Enter runs this query for real; the pair lives here rather
#: than in the template because the form's AS-OF cell formats a ``date``, and a
#: template literal would have to be a string.
SPECIMEN_QUERY = "fire separation between a garage and a house"
SPECIMEN_QUERY_DATE = date(2009, 6, 1)

#: The difference classes CCM's parity report is allowed to close a version on
#: (``known_safe_kind`` in ``<CODE>_<EDITION>-parity.json``).  The point of the
#: section is that the residue after the two reconstructions are diffed is a
#: short, named, *closed* vocabulary rather than an unexplained error bar — so
#: each entry carries a real worked example, not only a definition.
#:
#: ``example`` is ``(edition, division, provision_id, version)``, taken from an
#: item the parity report actually closed on that class.  Exemplars prefer
#: OBC 2006 because that edition is inside the free tier and so opens for
#: everyone; several classes simply do not occur there.  Those links land on
#: the locked-edition teaser rather than the provision, which the view flags so
#: the page can say so up front instead of springing it.
#:
#: ``occurs_in`` is the set of editions whose parity report raised the class at
#: all, and it is why the exemplars are not all OBC 2006: **OBC 2006 only ever
#: produced three of these eleven classes.**  Without it the reader (and the
#: next maintainer) reads a 1997 or 2012 exemplar as an arbitrary pick rather
#: than the only one available.  It also carries the section's sharpest fact
#: for free — the table classes are absent from 2006 and 2012 and concentrated
#: in 1997, because that era is scanned paper and the later two are e-Laws
#: HTML.
#:
#: Transcribed from the reports rather than counted live: CodeChronicle's
#: database stores the *outcome* of the parity review (the ``verified`` gate),
#: not its items.  Only edition names are recorded here, never counts — a
#: quantity on this page must be derivable from the tables the search reads.
#: Regenerate with, in the CodeChronicleMapping repository::
#:
#:     python -c "import json,collections;
#:     d=json.load(open('data/intermediates/reports/OBC_2006-parity.json'));
#:     print(collections.Counter(i.get('known_safe_kind') for i in d['items']))"
#:
#: The view drops any entry whose provision is not in the database, so the page
#: cannot ship a dead link if an edition is unloaded.  Keep in step with CCM's
#: classifier when a new class appears; a stale name here understates the work,
#: it cannot overstate the agreement (the agreement is the ``verified`` gate).
class DifferenceClass(TypedDict):
    """One entry of the closed vocabulary.

    A ``TypedDict`` rather than a plain mapping so ``example`` unpacks into four
    typed names.  ``dict[str, object]`` made every one of them ``object``, and
    the four unpacked names then needed a suppression each.
    """

    name: str
    gloss: str
    occurs_in: tuple[str, ...]
    example: tuple[str, str, str, int]


DIFFERENCE_CLASSES: list[DifferenceClass] = [
    {
        "name": "editorial-drift",
        "gloss": "e-Laws restyled the text — bolding, spacing, an added colon — "
                 "where no regulation said to",
        "occurs_in": ("1997", "2006", "2012"),
        "example": ("2006", "A", "1.4.1.2.", 1),
    },
    {
        "name": "elaws-advance-notice",
        "gloss": "e-Laws printed an amendment before the day it commenced",
        "occurs_in": ("2006", "2012"),
        "example": ("2006", "B", "1.3.1.2.", 2),
    },
    {
        "name": "elaws-note-marker-spacing",
        "gloss": "a footnote marker set as a superscript rather than plain text",
        "occurs_in": ("1997", "2006"),
        "example": ("2006", "B", "9.12.2.2.", 0),
    },
    {
        "name": "elaws-drops-revoked-subtree",
        "gloss": "e-Laws stopped printing a provision whose parent was revoked",
        "occurs_in": ("1997",),
        "example": ("1997", "", "2.11.1.", 1),
    },
    {
        "name": "revoked-before-effect",
        "gloss": "a provision was revoked before its own commencement arrived",
        "occurs_in": ("1997", "2012"),
        "example": ("2012", "C", "4.1.2.", 2),
    },
    {
        "name": "elaws-table-reformat",
        "gloss": "the same table, laid out differently",
        "occurs_in": ("1997", "2012"),
        "example": ("2012", "B", "10.3.2.2.", 2),
    },
    {
        "name": "elaws-table-header-merge",
        "gloss": "two table header rows combined into one",
        "occurs_in": ("2012",),
        "example": ("2012", "B", "3.1.4.7.", 1),
    },
    {
        "name": "elaws-rendering-omission",
        "gloss": "content the consolidation page did not render at all",
        "occurs_in": ("1997", "2012"),
        "example": ("2012", "A", "1.4.1.2.", 4),
    },
    {
        "name": "elaws-notes-reflow",
        "gloss": "notes moved on the page, with no change of wording",
        "occurs_in": ("1997",),
        "example": ("1997", "", "11.2.1.1.", 1),
    },
    {
        "name": "table-format",
        "gloss": "a table's structure recovered differently from the scan",
        "occurs_in": ("1997",),
        "example": ("1997", "", "3.12.4.5.", 0),
    },
    {
        # The user-facing point, and the reason this one is tolerated rather
        # than chased down: it only arises in the scanned pre-e-Laws era, and
        # only on tables we present as the page IMAGE. The reader sees the
        # scan, so stray OCR characters in the extracted text behind it cannot
        # mislead them — they only affect what the table matches on in search.
        "name": "non-keyword-table-ocr",
        "gloss": "OCR noise in a scanned table we show as the page image — "
                 "it never reaches what you read",
        "occurs_in": ("1997",),
        "example": ("1997", "", "3.1.13.7.", 0),
    },
]


def _resolve_examples(user: Any) -> list[dict[str, Any]]:
    """Attach a permalink and a tier flag to each difference class.

    An entry whose provision is not loaded keeps its name and gloss and loses
    only the link.  The section's argument is the *vocabulary* — that the
    residue is short, named and closed — and the worked examples are its
    supporting evidence; dropping the vocabulary because an edition is absent
    would discard the argument to protect the evidence.
    """
    resolved: list[dict[str, Any]] = []
    for entry in DIFFERENCE_CLASSES:
        edition_id, division, provision_id, version = entry["example"]
        provision = (
            CodeEditionProvision.objects.select_related("edition")
            .filter(
                edition__code__code="OBC",
                edition__edition_id=edition_id,
                division=division,
                provision_id=provision_id,
            )
            .first()
        )
        loadable = provision is not None and CodeEditionProvisionVersion.objects.filter(
            provision=provision, version=version
        ).exists()

        url = ""
        if loadable and provision is not None:
            # Division-less editions (OBC 1997 stores division="") take the
            # sibling route that omits the segment entirely — a URL path
            # segment cannot be empty, and there is no sentinel.
            kwargs = {
                "code_edition": provision.edition.code_name,
                "provision_id": provision_id,
                "version": version,
            }
            if division:
                url = reverse(
                    "core:provision_permalink", kwargs={**kwargs, "division": division}
                )
            else:
                url = reverse("core:provision_permalink_no_division", kwargs=kwargs)

        resolved.append(
            {
                "name": entry["name"],
                "gloss": entry["gloss"],
                "occurs_in": entry["occurs_in"],
                # True when OBC 2006 never raised this class, which is the
                # reason the exemplar is from another edition. Resolved here so
                # the template asks "was 2006 even possible?" rather than
                # re-deriving it from the free-tier list.
                "absent_from_free_tier": "2006" not in entry["occurs_in"],
                "url": url,
                "cite": f"{provision_id}{f' Div. {division}' if division else ''}",
                "edition_label": f"OBC {edition_id}",
                "locked": bool(url)
                and provision is not None
                and not edition_allowed(user, provision.edition.code_name),
            }
        )
    return resolved


def _free_tier_examples() -> list[dict[str, str]]:
    """Hero "try this" queries, restricted to what a visitor can actually open.

    Drawn from the search page's own vetted ``EXAMPLE_QUERIES`` so there is one
    list, not two that drift.  Each carries its own date, and the link passes it
    as ``?d=`` — without that the search runs at the default AS-OF date and a
    query whose text says "1999" comes back with results from a later edition.
    Only examples dated inside a free-tier edition's window are offered: an
    anonymous visitor gets one search a day, and spending it on a locked page is
    the worst possible first impression.
    """
    free_names = free_tier_code_names()
    windows = [
        (e.effective_date, e.ineffective_date or date.max)
        for e in CodeEdition.objects.select_related("code").filter(verified=True)
        if e.code_name in free_names
    ]
    if not windows:
        return []

    offered: list[dict[str, str]] = []
    for example in EXAMPLE_QUERIES:
        raw = example.get("date")
        if not raw:
            continue
        try:
            when = date.fromisoformat(raw)
        except ValueError:
            continue
        if any(start <= when < end for start, end in windows):
            offered.append({"query": example["query"], "date": raw})
    return offered[:3]


def _specimen(user: Any) -> dict[str, Any]:
    """The real record behind the section III specimens, or ``{}``.

    Returns the same ``result`` mapping the permalink page builds, plus the
    citation-linked html, so the template can include ``_provenance_rail.html``
    and print ``linked_html`` — the shipping components, against a shipping
    record.  A drawn picture of a rail is a claim about the product that
    nothing keeps true; this cannot drift, because it *is* the product.

    Empty when the specimen provision is not loaded (a fresh database, or a
    corpus without OBC 2006).  The template then falls back to prose, because a
    front page must render before the data does.
    """
    edition_id, division, provision_id, version_number = SPECIMEN
    provision = (
        CodeEditionProvision.objects.select_related("edition__code")
        .filter(
            edition__code__code="OBC",
            edition__edition_id=edition_id,
            division=division,
            provision_id=provision_id,
        )
        .first()
    )
    if provision is None:
        return {}
    version = provision.versions.filter(version=version_number).first()
    if version is None:
        return {}

    code_name = provision.edition.code_name
    # fan_out=True is the point of row 04: where the cited provision changed
    # inside this version's life, every candidate is offered rather than one
    # being guessed at silently.
    annotate_versions([version], code_name, on_date=SPECIMEN_DATE, fan_out=True)
    # Row 04 is about one sentence — the citation inside it — and the article's
    # clause list underneath is noise on a landing page. Split on the first
    # closing paragraph rather than by character count, so the excerpt is always
    # a whole block and can never end mid-tag. The caption links to the rest.
    lead_html, sep, _rest = (version.linked_html or "").partition("</p>")
    return {
        "provenance": _provenance_result(
            provision, version, code_name, division, provision_id, user
        ),
        "version": version,
        "lead_html": lead_html + sep,
        "title": version.title,
        "cite": provision_id,
        "url": reverse(
            "core:provision_permalink",
            kwargs={
                "code_edition": code_name,
                "division": division,
                "provision_id": provision_id,
                "version": version_number,
            },
        ),
    }


def _source_chips() -> list[Regulation]:
    """One regulation per publication source we link out to.

    Real rows, so the two chips in row 05 carry the label and the URL the
    provision pages carry.  The pairing is the claim: e-Laws for the modern
    record, Ontario Gazette scans for the years before e-Laws went online — a
    hand-typed pair could keep saying that after a source stopped being used.
    """
    chips: list[Regulation] = []
    for kind in (Regulation.SourceKind.ELAWS, Regulation.SourceKind.ARCHIVE_GAZETTE):
        regulation = (
            Regulation.objects.exclude(source_url="")
            .filter(source_kind=kind)
            .order_by("effective_date")
            .first()
        )
        if regulation is not None:
            chips.append(regulation)
    return chips


def _edition_band(
    editions: Sequence[CodeEdition], span_start: date, span_end: date
) -> list[dict[str, object]]:
    """Lay the editions out along the covered span as percentage offsets.

    The same in-force band the search results and the attestation rail draw,
    scaled to the whole corpus instead of one provision — so the shape a reader
    meets on the front page is the shape they meet in a result.  Geometry is
    computed here rather than in the template because the template cannot do
    date arithmetic, and because an edition still in force has no
    ``ineffective_date`` to measure against (it runs to the end of the span).

    ``last_day`` is the INCLUSIVE final day in force — ``ineffective_date``
    minus one.  The stored date is exclusive, so printing it raw shows the
    successor edition's first day as this edition's "until", which reads as an
    overlap and made two of three rows look like they ended on January 1st.
    """
    total = (span_end - span_start).days or 1
    band: list[dict[str, object]] = []
    for edition in editions:
        start = max(edition.effective_date, span_start)
        end = min(edition.ineffective_date or span_end, span_end)
        left = (start - span_start).days / total * 100
        width = max((end - start).days / total * 100, 0.5)
        band.append(
            {
                "edition": edition,
                "left": round(left, 3),
                "width": round(width, 3),
                "start": start,
                "last_day": end - timedelta(days=1),
            }
        )
    return band


def landing(request: HttpRequest, *, redirect_signed_in: bool = False) -> HttpResponse:
    """The front page.  Redirects a signed-in reader to the search page.

    ``redirect_signed_in`` is set by the ``/`` route only, so the ``/about/``
    route renders for everybody.  It arrives as a URLconf extra kwarg rather
    than being derived from the resolved route name, so the behaviour is
    visible where the routes are declared.
    """
    if redirect_signed_in and request.user.is_authenticated:
        return redirect("core:search")

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
    edition_ids = [e.pk for e in editions]
    # Render-time annotation, not a DB field: the INCLUSIVE last day in force.
    # ``ineffective_date`` is exclusive, so printing it raw gives the successor
    # edition's first day and the table reads as though the editions overlap.
    for edition in editions:
        edition.last_day = (  # type: ignore[attr-defined]
            edition.ineffective_date - timedelta(days=1) if edition.ineffective_date else None
        )

    # One aggregate per corpus-wide count.  ``amendment_count`` is already
    # annotated per edition above; summing the annotation in Python avoids a
    # second join that would double-count regulations shared across editions.
    amending_regs = sum(int(getattr(e, "amendment_count", 0)) for e in editions)
    provision_count = CodeEditionProvision.objects.filter(edition_id__in=edition_ids).count()
    version_count = CodeEditionProvisionVersion.objects.filter(
        provision__edition_id__in=edition_ids
    ).count()
    consolidation_count = Consolidation.objects.filter(edition_id__in=edition_ids).count()
    # The earliest consolidation we can verify against.  It is the honest
    # bound on the *online* record: before this date there is no e-Laws
    # snapshot of the Code to check a reconstruction against, so the amending
    # regulations come from Ontario Gazette scans instead.  Stated as a fact
    # about our own corpus rather than a claim about e-Laws' whole system.
    elaws_pit_start = Consolidation.objects.filter(edition_id__in=edition_ids).aggregate(
        first=Min("effective_from")
    )["first"]

    # Span: the corpus stamp when it exists (the same figure the masthead
    # shows, recomputed on every data load), else the editions' own extremes.
    currency = CorpusCurrency.get_solo()
    bounds = CodeEdition.objects.filter(pk__in=edition_ids).aggregate(
        first=Min("effective_date"), last=Max("ineffective_date")
    )
    span_start = (currency.coverage_start if currency else None) or bounds["first"]
    span_end = (currency.coverage_end if currency else None) or bounds["last"]

    band = (
        _edition_band(editions, span_start, span_end)
        if editions and span_start and span_end and span_end > span_start
        else []
    )

    return render(
        request,
        "landing.html",
        {
            "editions": editions,
            "edition_count": len(editions),
            "amending_regs": amending_regs,
            "provision_count": provision_count,
            "version_count": version_count,
            "consolidation_count": consolidation_count,
            "elaws_pit_start": elaws_pit_start,
            "try_examples": _free_tier_examples(),
            "specimen": _specimen(request.user),
            "specimen_query": SPECIMEN_QUERY,
            "specimen_query_date": SPECIMEN_QUERY_DATE,
            "source_chips": _source_chips(),
            "span_start": span_start,
            "span_end": span_end,
            "band": band,
            "difference_classes": _resolve_examples(request.user),
        },
    )
