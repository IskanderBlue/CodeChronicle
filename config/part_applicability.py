"""Which part of the code applies to which building.

The code states this itself, and we hold the text.  OBC 2006 and 2012 put it
in Division A, Subsection ``1.1.2.``; OBC 1997 puts the same six statements in
Section ``2.1.``.  Nothing here is invented — every rule below cites the
article it reads, and a reader can open that article and check it.

**The code splits on building type in exactly one place.**  Of the six
applicability articles, only two read the building: the one for Parts 3, 4, 5
and 6, and the one for Part 9.  The rest apply to every building
(Parts 1, 7, 12), or apply to an activity (Part 10 a change of use, Part 11 a
renovation), or apply to a system (Part 8 a sewage system).  So this module
answers one question with two outcomes, and does not need a general rule
engine.

**The rule is time-varying, which is why a rule carries a window.**  On
1 July 2017 a retirement home left Part 9 and joined Parts 3, 5 and 6 —
``1.1.2.4.`` v1 excluded it and ``1.1.2.2.`` v2 named it.  A table keyed by
edition alone cannot say that; a table keyed by window can, and answering "as
it read on that date" is what this product is for.

**A part number is not a key.**  It moves between editions — Part 5 is Wind,
Water and Vapour Protection in 1997 and Environmental Separation from 2006 —
and it collides across divisions of one edition, where Division A Part 3 is
Functional Statements, Division B Part 3 is Fire Protection and Division C
Part 3 is Qualifications.  Every rule therefore names its edition *and* the
division its parts sit in, and OBC 1997 has no divisions at all (``""``).

No Django imports: this package is plain data, read by ``api.search`` and by
the parser.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import TypedDict

#: Major occupancy, as Table 3.1.2.1. "Classification of Buildings" defines it.
#: The keys are the reader-facing words that travel in the address; the values
#: are the code's own labels, for the control and for any copy that explains a
#: boost.  The group letter is deliberately not the key — ``C`` is an internal
#: token to put in a URL a reader reads.
OCCUPANCIES: dict[str, str] = {
    "assembly": "Group A, assembly occupancies",
    "care-or-detention": "Group B, care, care and treatment or detention occupancies",
    "residential": "Group C, residential occupancies",
    "business": "Group D, business and personal services occupancies",
    "mercantile": "Group E, mercantile occupancies",
    "high-hazard-industrial": "Group F, Division 1, high hazard industrial occupancies",
    "medium-hazard-industrial": "Group F, Division 2, medium hazard industrial occupancies",
    "low-hazard-industrial": "Group F, Division 3, low hazard industrial occupancies",
    # Not a group of its own in Table 3.1.2.1. — a retirement home is a Group C
    # residential occupancy.  It is a choice here because the two rules treat
    # it differently after 1 July 2017, and that difference is invisible if the
    # reader can only say "residential".
    "retirement-home": "A retirement home (Group C, residential occupancies)",
}


#: The same occupancies, named briefly enough for a chip.  Derived from the
#: keys rather than written out, so a new occupancy cannot appear in the
#: dropdown and be missing here — and so the query bar, the results header and
#: the control all read one rule instead of each deriving their own.
OCCUPANCY_SHORT: dict[str, str] = {key: key.replace("-", " ") for key in OCCUPANCIES}


#: How much an applicable part's score is raised, and an excluded part's
#: lowered.  Multipliers, applied after scoring — never a filter.  A house is
#: routinely governed by a Part 3 provision through a cross-reference, so an
#: excluded part must move down the page rather than be dropped from it.  (The
#: relevance floor still runs afterwards on the adjusted scores, so a demoted
#: result can fall under the reader's line; see ``_apply_part_boost``.)
#:
#: Measured, not picked round.  On `guard height for a stair in a house` at
#: 1 June 2008 (OBC 2006, 405 matches), Part 3's `3.4.6.5. Guards` ranks 1st
#: unboosted and outranks every Part 9 guard provision.  Stating a two-storey
#: house of 140 m² moves it to:
#:
#:     0.25/0.15  ->  rank 3, still above 9.8.8.1. Required Guards (rank 5)
#:     0.35/0.20  ->  rank 6, below 9.8.8.1. (rank 4)
#:     0.50/0.30  ->  rank 11, with nothing further gained
#:
#: 0.35/0.20 is the smallest pair that puts the Part 9 provisions above their
#: Part 3 counterpart, which is what the reader asked for.  Going further only
#: buries a part a house still reaches by cross-reference.
PART_BOOST = 0.35
PART_DEMOTE = 0.20


class Verdict(Enum):
    """What the code's own test says about one part and one building."""

    #: The applicability article names this building.
    APPLIES = "applies"
    #: The applicability article excludes this building.
    EXCLUDED = "excluded"
    #: We cannot tell.  A missing measurement, an occupancy we were not given,
    #: a part the articles do not gate, or a division they do not reach.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ApplicabilityRule:
    """One edition's building-type split, for one window of that edition."""

    edition_id: str
    #: Division the **gated parts** live in — Division B from 2006, and ``""``
    #: for OBC 1997, which has no divisions.  Deliberately not the division of
    #: the article that states the rule: from 2006 that article is in Division
    #: A and every provision it governs is in Division B, so one field cannot
    #: mean both.  ``source_small`` and ``source_large`` name the article.
    parts_division: str
    #: The parts that apply to a small building of a listed occupancy.
    small_parts: tuple[int, ...]
    #: The parts that apply to everything else the two articles name.
    large_parts: tuple[int, ...]
    #: Occupancies that can reach ``small_parts`` when the building is small
    #: enough.  Above either threshold they reach ``large_parts`` instead.
    sized_occupancies: frozenset[str]
    #: Occupancies that reach ``large_parts`` whatever the size.  The article
    #: states no size test for these, so the word alone decides.
    unsized_occupancies: frozenset[str]
    max_storeys: int
    max_area_m2: int
    #: The articles this rule reads, for the citation beside a boosted result.
    source_small: str
    source_large: str
    #: Half-open window, matching every other date window in this product.
    #: ``None`` on either side means the rule is open in that direction.
    effective: date | None = None
    ineffective: date | None = None


# Group A, B and F1 buildings reach Parts 3/4/5/6 whatever their size — the
# article states no size test for them.  Group C, D, E, F2 and F3 buildings
# reach Part 9 when small and Parts 3/4/5/6 when not.  That shape holds in all
# three loaded editions; only the retirement home moves.
_SIZED = frozenset({
    "residential",
    "business",
    "mercantile",
    "medium-hazard-industrial",
    "low-hazard-industrial",
})
_UNSIZED = frozenset({
    "assembly",
    "care-or-detention",
    "high-hazard-industrial",
})

#: One rule per edition per window, oldest first.  Three editions are loaded;
#: OBC 2012 needs two rows because of the 2017 retirement-home change.
RULES: tuple[ApplicabilityRule, ...] = (
    ApplicabilityRule(
        edition_id="1997",
        parts_division="",
        small_parts=(9,),
        large_parts=(3, 4, 5, 6),
        # 1997 has no retirement-home rule, so the word falls back to what it
        # is: a residential occupancy, sized like any other.
        sized_occupancies=_SIZED | {"retirement-home"},
        unsized_occupancies=_UNSIZED,
        max_storeys=3,
        max_area_m2=600,
        source_small="2.1.1.3.",
        source_large="2.1.1.2.",
    ),
    ApplicabilityRule(
        edition_id="2006",
        parts_division="B",
        small_parts=(9,),
        large_parts=(3, 4, 5, 6),
        sized_occupancies=_SIZED | {"retirement-home"},
        unsized_occupancies=_UNSIZED,
        max_storeys=3,
        max_area_m2=600,
        source_small="Division A 1.1.2.4.",
        source_large="Division A 1.1.2.2.",
    ),
    ApplicabilityRule(
        edition_id="2012",
        parts_division="B",
        small_parts=(9,),
        large_parts=(3, 4, 5, 6),
        sized_occupancies=_SIZED | {"retirement-home"},
        unsized_occupancies=_UNSIZED,
        max_storeys=3,
        max_area_m2=600,
        source_small="Division A 1.1.2.4.",
        source_large="Division A 1.1.2.2.",
        ineffective=date(2017, 7, 1),
    ),
    ApplicabilityRule(
        edition_id="2012",
        parts_division="B",
        small_parts=(9,),
        large_parts=(3, 4, 5, 6),
        # 1.1.2.4. v1 removed retirement homes from Part 9's Group C, and
        # 1.1.2.2. v2 added them to Parts 3, 5 and 6 with no size test.
        sized_occupancies=_SIZED,
        unsized_occupancies=_UNSIZED | {"retirement-home"},
        max_storeys=3,
        max_area_m2=600,
        source_small="Division A 1.1.2.4.",
        source_large="Division A 1.1.2.2.",
        effective=date(2017, 7, 1),
    ),
)


#: Bounds on a supplied measurement.  Not code rules — only a guard so a
#: hand-edited address cannot store a value the control could never draw back.
MAX_STOREYS = 200
MAX_AREA_M2 = 1_000_000.0

#: Square feet in one square metre.  The code states 600 m²; most people doing
#: Ontario residential work hold the figure in square feet, and a reader who
#: types 1500 into a box measured in metres describes a building two and a half
#: times over the Part 9 limit — silently, because the page simply re-ranks.
#: So the reader picks the unit and this converts.
SQFT_PER_M2 = 10.763910416709722

#: The units the area may be given in, and what the control calls each.
AREA_UNITS: dict[str, str] = {
    "m2": "m²",
    "sqft": "ft²",
}
DEFAULT_AREA_UNIT = "m2"


class Building(TypedDict, total=False):
    """What the reader told us about their building, after validation.

    Every key is optional, and an absent one means "not stated" — never a
    default, because a default here would be a guess about somebody's
    building.  ``area`` and ``area_unit`` are the reader's own figure and
    unit; ``area_m2`` is the conversion the rule reads.
    """

    occupancy: str
    storeys: int
    area: float
    area_unit: str
    area_m2: float


def coerce_building(
    occupancy: object,
    storeys: object,
    area: object,
    area_unit: object = DEFAULT_AREA_UNIT,
) -> Building:
    """Clamp reader-supplied building facts to storable values.

    Every caller is handling untrusted input — a form post or a query
    parameter a reader can edit by hand.  Anything unusable becomes an absent
    key rather than a default, because a default here would be a guess about
    somebody's building, and a guess is what this whole design avoids.

    **The reader's own number and unit are kept, and the metric value is
    derived.**  Three keys come back for an area: ``area`` and ``area_unit``
    are what the reader typed, and ``area_m2`` is what the rule reads.  Storing
    the reader's figure rather than only the conversion is what lets the
    address, the control and the history card show them the number they
    entered — converting back would round 1500 ft² into something near it but
    not equal to it, in a URL.
    """
    building: Building = {}

    if isinstance(occupancy, str) and occupancy in OCCUPANCIES:
        building["occupancy"] = occupancy

    try:
        floors = int(str(storeys).strip())
    except (TypeError, ValueError):
        floors = 0
    if 1 <= floors <= MAX_STOREYS:
        building["storeys"] = floors

    unit = str(area_unit) if area_unit in AREA_UNITS else DEFAULT_AREA_UNIT
    try:
        value = float(str(area).strip())
    except (TypeError, ValueError):
        value = 0.0
    # NaN needs no guard: it compares false against both bounds below, so
    # the range test drops it exactly as it drops zero.
    metric = value if unit == "m2" else value / SQFT_PER_M2
    if 0 < metric <= MAX_AREA_M2:
        building["area"] = round(value, 2)
        building["area_unit"] = unit
        building["area_m2"] = round(metric, 2)

    return building


@dataclass(frozen=True)
class SizeWindow:
    """A span in which one set of occupancies is decided by its size."""

    start: date | None
    end: date | None
    sized: frozenset[str]


def _overlap(
    a: tuple[date | None, date | None], b: tuple[date | None, date | None]
) -> tuple[date | None, date | None] | None:
    """Intersect two half-open windows, or ``None`` when they do not meet."""
    starts = [d for d in (a[0], b[0]) if d is not None]
    ends = [d for d in (a[1], b[1]) if d is not None]
    start = max(starts) if starts else None
    end = min(ends) if ends else None
    if start is not None and end is not None and start >= end:
        return None
    return start, end


def size_relevance_intervals(
    edition_windows: Mapping[str, tuple[date | None, date | None]],
) -> list[SizeWindow]:
    """When a measurement can decide, and for which occupancies.

    One entry per rule, as ``(start, end, sized)`` with real dates.  A caller
    that has to serialise these does its own shaping — this module states the
    rule and stops there, which is what keeps it importable by the scorer
    without dragging a control's payload format along.

    The control unions the ``sized`` sets of every window covering the
    reader's AS-OF date, so it asks for a size exactly where a size changes
    the answer on that day: a retirement home is sized before 1 July 2017 and
    unsized after it, and the reader should see that happen when they move the
    date rather than be asked either way.

    ``edition_windows`` comes from the corpus (``CodeEdition``), because that
    is where an edition's dates live; a copy here would be a second set of
    edition dates to keep true.  A rule for an edition that is not loaded is
    dropped, which is what makes the control describe the corpus rather than
    the table.
    """
    windows: list[SizeWindow] = []
    for rule in RULES:
        if rule.edition_id not in edition_windows:
            continue
        overlap = _overlap(
            (rule.effective, rule.ineffective), edition_windows[rule.edition_id]
        )
        if overlap is None:
            continue
        windows.append(SizeWindow(overlap[0], overlap[1], rule.sized_occupancies))
    return windows


def size_thresholds() -> tuple[int, int] | None:
    """The storey and area limits, when every loaded rule agrees on them.

    ``None`` when they differ, which is the signal for a caller to stop
    printing one pair of numbers as though it governed the whole corpus.  All
    three loaded editions state three storeys and 600 m², so today this
    returns that pair — but the copy reads it from here rather than repeating
    it, because a hand-typed threshold is a claim about the code that nothing
    checks.
    """
    pairs = {(rule.max_storeys, rule.max_area_m2) for rule in RULES}
    return pairs.pop() if len(pairs) == 1 else None


def rule_for(edition_id: str, on_date: date | None) -> ApplicabilityRule | None:
    """The rule governing ``edition_id`` on ``on_date``, or ``None``.

    ``None`` for an edition this module does not describe, which every caller
    must read as "do not boost" rather than as "does not apply".  A date of
    ``None`` takes the edition's earliest rule, which is what a search with no
    stated date already falls back to elsewhere.
    """
    candidates = [r for r in RULES if r.edition_id == edition_id]
    if not candidates:
        return None
    if on_date is None:
        return candidates[0]
    for rule in candidates:
        if rule.effective is not None and on_date < rule.effective:
            continue
        if rule.ineffective is not None and on_date >= rule.ineffective:
            continue
        return rule
    return None


def part_of(provision_id: str) -> int | None:
    """The part number an id sits in, or ``None``.

    The leading number of the first dotted segment: ``9.8.8.3.`` is Part 9 and
    ``3(20)`` is Part 3.  The whole product reads a part number here — the
    search boost, and ``core.views.regulation``, which groups a regulation's
    amended provisions into Part blocks.

    Those two callers pass ids from **two vocabularies**, and this reads both:

    * ``CodeEditionProvision.provision_id``, where a part-level row's own id is
      ``Part 9``.  A container page is a search result like any other.
    * ``RegulationClause.target_id``, where a part-level target is the bare
      number ``9``, because the level lives in ``target_level`` beside it.

    A ``/`` **in the first segment** means the id is a regulation citation such
    as ``350/06``, which the second vocabulary also carries
    (``target_level="regulation"``).  It has no part, and reading its leading
    digits as one produced a "Part 350" block on the regulation page.  The test
    is on that segment alone, not the whole id: ``11.5.1.1.D/E.`` is a real
    Part 11 table whose slash sits in a later segment.
    """
    text = provision_id.strip()
    if not text:
        return None
    head = text.split(".", 1)[0].strip()
    if "/" in head:
        return None
    if head.lower().startswith("part"):
        head = head[4:].strip()
    match = re.match(r"\d+", head)
    return int(match.group(0)) if match else None


def _is_small(
    rule: ApplicabilityRule, storeys: int | None, area_m2: float | None
) -> bool | None:
    """Does the building clear both of the small-building thresholds?

    ``None`` means undecided, and undecided must never boost.  Either
    measurement can decide **on its own** when it is over its threshold, which
    is the case worth having: a four-storey house is not a Part 9 building
    whatever its area, and that is exactly what a guess at the storey count
    gets wrong.  Deciding the other way needs both, because an unstated
    measurement may be the one that breaches.
    """
    if storeys is not None and storeys > rule.max_storeys:
        return False
    if area_m2 is not None and area_m2 > rule.max_area_m2:
        return False
    if storeys is not None and area_m2 is not None:
        return True
    return None


def source_for(
    *, edition_id: str, provision_id: str, on_date: date | None
) -> str:
    """The article that decides this provision's part, for a citation.

    Only meaningful where :func:`verdict_for` returned something other than
    ``UNKNOWN`` — a boost the reader cannot trace back to an article is a
    number we are asking them to trust.
    """
    rule = rule_for(edition_id, on_date)
    part = part_of(provision_id)
    if rule is None or part is None:
        return ""
    if part in rule.small_parts:
        return rule.source_small
    if part in rule.large_parts:
        return rule.source_large
    return ""


def verdict_for(
    *,
    edition_id: str,
    division: str,
    provision_id: str,
    occupancy: str | None,
    storeys: int | None,
    area_m2: float | None,
    on_date: date | None,
) -> Verdict:
    """What the code's own test says about this provision and this building.

    Returns :data:`Verdict.UNKNOWN` for anything the applicability articles do
    not decide, which includes Division A, Division C, the ungated parts, an
    edition with no rule, and a building we know too little about.
    """
    if occupancy is None or occupancy not in OCCUPANCIES:
        return Verdict.UNKNOWN

    rule = rule_for(edition_id, on_date)
    if rule is None or division != rule.parts_division:
        return Verdict.UNKNOWN

    part = part_of(provision_id)
    if part is None:
        return Verdict.UNKNOWN
    in_small = part in rule.small_parts
    in_large = part in rule.large_parts
    if not in_small and not in_large:
        return Verdict.UNKNOWN

    if occupancy in rule.unsized_occupancies:
        # The article names no size test for these, so the word decides both
        # ways: the large parts apply, and Part 9 is excluded.
        return Verdict.APPLIES if in_large else Verdict.EXCLUDED

    if occupancy not in rule.sized_occupancies:
        return Verdict.UNKNOWN

    small = _is_small(rule, storeys, area_m2)
    if small is None:
        return Verdict.UNKNOWN
    if small:
        return Verdict.APPLIES if in_small else Verdict.EXCLUDED
    return Verdict.APPLIES if in_large else Verdict.EXCLUDED
