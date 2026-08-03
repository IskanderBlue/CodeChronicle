"""Version comparison: reference parsing, the prepared pair, and the basis.

A comparison names two provision versions and nothing else.  The reference
form is the permalink path form minus the ``/provision/`` prefix, so a reader
builds one by copying two URLs::

    /compare/?a=OBC_1997/3.2.5.7./v3&b=OBC_2006/B/3.2.5.7./v0

Division-less editions (OBC 1997 stores ``division=""``) drop the segment
entirely, exactly as ``core.permalinks`` does for the permalink itself — no
sentinel in the URL.  So a reference has three parts or four, and the count is
what tells them apart.

Three things live here rather than in the view:

- **Parsing and building references**, so the two directions cannot drift.
- **The prepared pair** — what "Compare versions" opens when the reader has
  named only one side.  Every entry point uses this one ladder.
- **The pairing basis** — whether the two provisions are the same provision,
  counterparts we mapped, or two provisions with no mapping between them.
  A cross-edition redline asserts an equivalence nobody enacted, so the page
  must be able to say where the equivalence came from.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from django.urls import reverse

from core.access import edition_allowed
from core.models import CodeEditionProvisionVersion
from core.provision_lineage import LineageDirection, LineageLink, resolve_lineage

#: A redline of two texts that share less than this fraction of their words is
#: noise — the reader gets two panes of almost entirely marked text and learns
#: nothing.  Below the floor the page shows the two texts side by side and says
#: why, with an escape for a reader who disagrees.  The value is a judgement,
#: not a measurement: a third of the words in common is about where a redline
#: stops reading as "these changed" and starts reading as "these are different
#: texts".
REDLINE_FLOOR = 0.35

_VERSION_SEGMENT_RE = re.compile(r"^v(\d+)$")


@dataclass(frozen=True)
class VersionRef:
    """The four things a reference names.  ``division`` is "" when absent."""

    code_edition: str
    division: str
    provision_id: str
    version: int

    @property
    def path(self) -> str:
        """The reference string — the exact inverse of the parser."""
        parts = [self.code_edition]
        if self.division:
            parts.append(self.division)
        parts.extend([self.provision_id, f"v{self.version}"])
        return "/".join(parts)


def parse_version_ref(raw: str | None) -> VersionRef | None:
    """Parse ``OBC_2006/B/3.2.5.7./v0`` into a :class:`VersionRef`.

    Returns ``None`` for anything malformed.  A provision id contains dots but
    never a slash, so splitting on ``/`` is safe.
    """
    if not raw:
        return None
    parts = [p for p in raw.strip("/").split("/") if p]
    if len(parts) == 4:
        code_edition, division, provision_id, version_part = parts
    elif len(parts) == 3:
        code_edition, provision_id, version_part = parts
        division = ""
    else:
        return None
    match = _VERSION_SEGMENT_RE.match(version_part)
    if match is None:
        return None
    return VersionRef(code_edition, division, provision_id, int(match.group(1)))


def version_ref(version: CodeEditionProvisionVersion) -> VersionRef:
    """The reference that names ``version``."""
    provision = version.provision
    return VersionRef(
        provision.edition.code_name,
        provision.division,
        provision.provision_id,
        version.version,
    )


def resolve_version_ref(ref: VersionRef) -> CodeEditionProvisionVersion | None:
    """Look up the version a reference names, or ``None``."""
    code, _, edition_id = ref.code_edition.partition("_")
    return (
        CodeEditionProvisionVersion.objects
        .select_related("provision__edition__code")
        .filter(
            provision__edition__code__code=code,
            provision__edition__edition_id=edition_id,
            provision__division=ref.division,
            provision__provision_id=ref.provision_id,
            version=ref.version,
        )
        .first()
    )


@dataclass(frozen=True)
class PreparedPair:
    """The comparison a "Compare versions" control opens."""

    a: VersionRef
    b: VersionRef
    #: The counterpart sits in an edition this reader cannot open, so the
    #: control upsells to pricing instead of leading to a 403.  Only a lineage
    #: rung can set this; the same-edition rungs stay inside the edition the
    #: reader is already reading.
    locked: bool = False

    @property
    def url(self) -> str:
        """``/compare/?a=…&b=…`` with the references left readable.

        Slashes and dots are legal in a query value, and the whole point of
        reusing the permalink form is that a reader can read the URL and build
        one by hand.  Percent-encoding them would parse identically and read
        like an internal id.
        """
        return f"{reverse('core:compare')}?a={self.a.path}&b={self.b.path}"


def _link_ref(link: LineageLink) -> VersionRef:
    """A reference to what a lineage link points at, without a query.

    ``LineageLink`` already carries the target provision, its edition and the
    hand-off version, which is everything a reference names.
    """
    return VersionRef(
        link.edition.code_name,
        link.provision.division,
        link.provision.provision_id,
        link.version,
    )


def prepared_pair(
    *,
    version: CodeEditionProvisionVersion,
    chain: Sequence[CodeEditionProvisionVersion],
    predecessors: LineageDirection | None = None,
    successors: LineageDirection | None = None,
) -> PreparedPair | None:
    """The comparison "Compare versions" opens for ``version``.

    Pure over data the caller already has — the version, the other versions of
    it in this edition, and the resolved lineage — so a page of search results
    costs no extra query.  ``api.formatters`` stamps all three onto every
    result before this runs.

    Returns ``None`` when this version has no other version anywhere, in which
    case the control is not rendered at all.  An affordance that fails on
    click is worse than no affordance.

    The ladder, in order:

    1. **The previous version in this edition.** The tightest answerable
       question: what the last amendment did.  A whole-life v0-to-v3 diff on a
       long provision is the case most likely to fall through the redline
       floor, which is a poor first contact with the feature.
    2. **A mapped predecessor in an earlier edition.**  A provision with no
       local history reaches across the boundary by itself, which is exactly
       the provision whose interesting comparison is cross-edition.
    3. **The next version in this edition**, for a reader sitting on v0 of a
       provision that was amended later.
    4. **A mapped successor.**

    Steps 3 and 4 put ``version`` on the *earlier* side, because a comparison
    reads earlier-to-later regardless of which end the reader named.
    """
    here = version_ref(version)
    numbers = {v.version for v in chain}

    if version.version - 1 in numbers:
        return PreparedPair(_at_version(here, version.version - 1), here)

    if predecessors is not None and predecessors.links:
        link = predecessors.links[0]
        return PreparedPair(_link_ref(link), here, locked=link.locked)

    if version.version + 1 in numbers:
        return PreparedPair(here, _at_version(here, version.version + 1))

    if successors is not None and successors.links:
        link = successors.links[0]
        return PreparedPair(here, _link_ref(link), locked=link.locked)

    return None


def _at_version(ref: VersionRef, number: int) -> VersionRef:
    """The same provision at a different version number."""
    return VersionRef(ref.code_edition, ref.division, ref.provision_id, number)


def annotate_chain_comparisons(
    version: CodeEditionProvisionVersion,
    chain: Sequence[CodeEditionProvisionVersion],
) -> None:
    """Stamp ``compare_url`` on every other version in this edition's chain.

    The rail's per-row ``compare`` affordance used to hang ``?compare=<n>`` off
    the permalink and render a second comparison in place.  That was the same
    feature twice: it could not cross an edition, had no redline floor, and its
    URL said "this permalink, plus a comparison" rather than naming a
    comparison.  The rows now point at ``/compare/`` and there is one.

    Stamped in Python for the reason the lineage rows are: the template must
    not rebuild a URL, and the order (earlier first) is a rule, not a layout
    choice.
    """
    here = version_ref(version)
    for entry in chain:
        if entry.pk == version.pk:
            continue
        there = _at_version(here, entry.version)
        pair = (
            PreparedPair(there, here)
            if entry.version < version.version
            else PreparedPair(here, there)
        )
        entry.compare_url = pair.url  # type: ignore[attr-defined]


def annotate_lineage_comparisons(
    version: CodeEditionProvisionVersion,
    predecessors: LineageDirection | None,
    successors: LineageDirection | None,
) -> None:
    """Stamp ``compare_url`` on every lineage link, against ``version``.

    The prepared pair reaches a counterpart only for a provision with no local
    history — it is one rung of a ladder, and the earlier rungs win.  A
    provision that was amended twice *and* renumbered into the next edition
    therefore gets the local comparison from the control and would have no way
    to ask for the cross-edition one.  This is that way.

    A predecessor goes on the earlier side and a successor on the later side,
    so the comparison reads earlier-to-later in both directions.

    Mutates the links in place, matching :func:`annotate_lineage_locks`, so
    every render site sees the field without the templates rebuilding a URL —
    the target's edition, division and id all differ from the reader's.
    """
    here = version_ref(version)
    for direction, target_is_earlier in (
        (predecessors, True),
        (successors, False),
    ):
        if direction is None:
            continue
        for link in direction.links:
            if link.locked:
                continue
            there = _link_ref(link)
            pair = (
                PreparedPair(there, here)
                if target_is_earlier
                else PreparedPair(here, there)
            )
            link.compare_url = pair.url


#: Two ticks closer than this many percent of the axis collide as drawn marks.
#: The second one moves down a lane rather than sitting on top of the first.
#: A percentage and not a pixel count because the axis is fluid; at the page's
#: measure this is a little over one mark width, which is what "collide" means.
TICK_LANE_GAP = 3.5


@dataclass(frozen=True)
class TimelineTick:
    """One version, on one row of the comparison's date axis."""

    version: CodeEditionProvisionVersion
    edition_name: str
    #: Position along the axis, 0–100, from the real dates — so a decade of
    #: silence looks like a decade of silence.  Even spacing would draw the
    #: sequence and throw away the fact the axis exists to carry.
    offset: float
    #: Which stacked lane the mark sits in.  Nearly-simultaneous versions would
    #: otherwise be drawn on top of each other, and a mark half-covering
    #: another mark is not a drawing of anything.
    lane: int
    #: This row's own pin — the version this side of the comparison is on.
    is_pin: bool
    #: The *other* row's pin.  Not offerable: choosing it would ask for a
    #: version compared with itself, which the view refuses.
    is_other_pin: bool
    #: The comparison that moving *this row's* pin to this version opens.
    #: Empty on either pin.
    url: str = ""

    @property
    def state(self) -> str:
        """``selected`` | ``taken`` | ``open`` — the mark's three appearances.

        ``taken`` is the version the other row already holds: it would be a
        legitimate choice but for that, so it is drawn in the quiet outline an
        unavailable-but-real option deserves.  ``open`` gets the strong outline
        because it is the only one of the three a click does anything to.
        """
        if self.is_pin:
            return "selected"
        if self.is_other_pin:
            return "taken"
        return "open"


@dataclass(frozen=True)
class TimelineRow:
    """One side of the comparison, as a row of ticks.

    A row is a pin.  Clicking within it moves that pin and leaves the other
    alone, which is the whole reason there are two rows — see
    :class:`VersionTimeline`.
    """

    label: str
    version: CodeEditionProvisionVersion
    ticks: list[TimelineTick]
    #: Where this row's pin sits, so the template can put the date label beside
    #: the mark it names rather than at the end of the row.  A date at the far
    #: end labels the row, and a row is not what a reader is reading.
    pin_offset: float = 0.0
    #: Lane of this row's pin, so the label sits on the pin's own line.
    pin_lane: int = 0
    #: The two ends of this row's dotted connector.  It runs between the marks
    #: the row actually draws, not the full width — a line continuing past the
    #: last mark promises a choice that is not there.
    line_start: float = 0.0
    line_end: float = 100.0

    @property
    def line_width(self) -> float:
        """Length of the connector, since CSS wants a width and not two ends."""
        return self.line_end - self.line_start


@dataclass(frozen=True)
class VersionTimeline:
    """Every version behind a comparison, on a date axis, once per side.

    The axis is what makes a *prepared* pair safe to offer.  The ladder guesses
    which comparison the reader wanted, and a guess the reader cannot see is a
    guess they cannot correct: the timeline draws every version that was
    available, marks the two the page chose, and puts every other choice one
    click away.

    **Two rows, not one.**  A single row has to decide which pin a click moves,
    and every rule for deciding leaves pairs unreachable.  "Move the nearer
    pin" cannot reach two ticks that are both nearer the same pin: each click
    replaces the one that just moved, so the far pin never leaves.  A reader
    asking for exactly that — the two most recent versions of a long-lived
    provision — could not get there.  One row per pin has no rule to get wrong:
    the row you click in is the pin that moves.
    """

    rows: list[TimelineRow]
    #: Editions on the axis, earliest first — the axis legend.
    editions: list[str]
    #: How many lanes the marks stack into, so the template can size the rows.
    lanes: int = 1
    #: Versions on the axis, before either row drops its unusable end.
    version_count: int = 0

    @property
    def is_useful(self) -> bool:
        """False when the axis would draw only the two pins already on screen."""
        return self.version_count > 2


def version_timeline(
    earlier: CodeEditionProvisionVersion,
    later: CodeEditionProvisionVersion,
    user: object,
) -> VersionTimeline:
    """Build the axis for the comparison of ``earlier`` and ``later``.

    The version set is both pinned provisions plus every provision one mapping
    hop away from either.  One hop is the whole reach there is: mapping rows
    are only ever emitted between adjacent editions (see
    ``core.provision_lineage``), so a longer walk would be inventing links the
    data does not assert.

    Editions the reader cannot open are left off entirely rather than drawn and
    locked.  A tick is a control, and a control that fails on click is worse
    than no control — the same rule the ladder's last rung follows.

    Every version has an ``effective_date``; a version that never governed a
    day is a zero-length window, not a missing one, so nothing falls off the
    axis for want of a date.
    """
    provisions = {earlier.provision.pk: earlier.provision,
                  later.provision.pk: later.provision}
    for lineage in resolve_lineage([earlier.provision, later.provision]).values():
        for direction in (lineage.predecessors, lineage.successors):
            for link in direction.links:
                provisions.setdefault(link.provision.pk, link.provision)

    versions = [
        version
        for version in (
            CodeEditionProvisionVersion.objects
            .select_related("provision__edition__code")
            .filter(provision__in=provisions.values())
            .order_by("effective_date", "version")
        )
        if edition_allowed(user, version.provision.edition.code_name)
    ]
    if not versions:
        return VersionTimeline(rows=[], editions=[])

    first = versions[0].effective_date
    span = (versions[-1].effective_date - first).days
    # A span of zero means every version commenced on one day.  Stacking them
    # at the middle is the honest drawing of that.
    offsets = [
        50.0 if span == 0
        else (version.effective_date - first).days * 100.0 / span
        for version in versions
    ]
    lanes = _lanes(offsets)

    editions: list[str] = []
    for version in versions:
        edition = version.provision.edition
        name = f"{edition.code.code} {edition.edition_id}".strip()
        if name not in editions:
            editions.append(name)

    # The labels match the twin header: A is the earlier side, B the later.
    # Each row drops the one version it can never hold: the earlier side cannot
    # be the newest version and the later side cannot be the oldest, because
    # either would leave the other side nothing to be.  Drawing an option that
    # cannot be taken is the same mistake as an affordance that fails on click.
    rows = [
        _timeline_row(label, pin, other, versions, offsets, lanes, skip=skip)
        for label, pin, other, skip in (
            ("A", earlier, later, len(versions) - 1),
            ("B", later, earlier, 0),
        )
    ]
    return VersionTimeline(
        rows=rows,
        editions=editions,
        lanes=max(lanes) + 1,
        version_count=len(versions),
    )


def _lanes(offsets: Sequence[float]) -> list[int]:
    """Stack marks that would otherwise be drawn on top of each other.

    Walks the offsets in order and drops a mark into the next lane down when it
    lands within :data:`TICK_LANE_GAP` of the last mark in the lane above.  Two
    amendments a month apart are a real fact about the provision, and two
    overlapping circles state it as an accident.
    """
    lanes: list[int] = []
    lane_ends: list[float] = []
    for offset in offsets:
        for lane, end in enumerate(lane_ends):
            if offset - end >= TICK_LANE_GAP:
                lanes.append(lane)
                lane_ends[lane] = offset
                break
        else:
            lanes.append(len(lane_ends))
            lane_ends.append(offset)
    return lanes


def _timeline_row(
    label: str,
    pin: CodeEditionProvisionVersion,
    other: CodeEditionProvisionVersion,
    versions: Sequence[CodeEditionProvisionVersion],
    offsets: Sequence[float],
    lanes: Sequence[int],
    *,
    skip: int,
) -> TimelineRow:
    """One pin's row.  Every tick moves this pin and leaves ``other`` alone.

    ``skip`` is the index this side can never hold — the newest version for the
    earlier side, the oldest for the later one.  It is left out rather than
    drawn and refused: an option that cannot be taken is noise on a row whose
    whole content is the options.
    """
    ticks: list[TimelineTick] = []
    pin_offset = 0.0
    pin_lane = 0
    for index, (version, offset, lane) in enumerate(
        zip(versions, offsets, lanes, strict=True)
    ):
        if index == skip:
            continue
        is_pin = version.pk == pin.pk
        if is_pin:
            pin_offset = offset
            pin_lane = lane
        is_other_pin = version.pk == other.pk
        edition = version.provision.edition
        ticks.append(
            TimelineTick(
                version=version,
                edition_name=f"{edition.code.code} {edition.edition_id}".strip(),
                offset=offset,
                lane=lane,
                is_pin=is_pin,
                is_other_pin=is_other_pin,
                url=(
                    ""
                    if is_pin or is_other_pin
                    else _pair_url(version, other)
                ),
            )
        )
    return TimelineRow(
        label=label,
        version=pin,
        ticks=ticks,
        pin_offset=pin_offset,
        pin_lane=pin_lane,
        # A single-version axis leaves a row with nothing after the skip.  The
        # timeline is not useful at that size and is never drawn, but the row
        # is still built, so the connector needs a length that is not min() of
        # an empty list.
        line_start=min((tick.offset for tick in ticks), default=0.0),
        line_end=max((tick.offset for tick in ticks), default=0.0),
    )


def _pair_url(
    moved: CodeEditionProvisionVersion,
    kept: CodeEditionProvisionVersion,
) -> str:
    """The comparison of the two, ordered earlier-first.

    The page re-sorts by date anyway; the order is built here only so the URL
    reads the way the page will.
    """
    pair = (
        PreparedPair(version_ref(moved), version_ref(kept))
        if (moved.effective_date, moved.version)
        <= (kept.effective_date, kept.version)
        else PreparedPair(version_ref(kept), version_ref(moved))
    )
    return pair.url


@dataclass(frozen=True)
class PairingBasis:
    """Why these two texts are shown together.

    ``state`` is one of:

    ``same_provision``
        Two versions of one provision.  The succession is the statute's own,
        so the page says nothing — and that silence is what teaches the reader
        what the other two states mean.
    ``mapped``
        Different provisions, linked by a ``ProvisionMapping``.  The page must
        say the pairing comes from the mapping, or it asserts an equivalence
        nobody enacted.
    ``unmapped``
        Different provisions with no mapping between them.  Reachable only by
        a hand-built URL.  The page says plainly that we did not pair these.
    """

    state: str
    verb: str = ""


def pairing_basis(
    earlier: CodeEditionProvisionVersion,
    later: CodeEditionProvisionVersion,
) -> PairingBasis:
    """Establish how ``earlier`` and ``later`` come to be shown together."""
    if earlier.provision_id == later.provision_id:
        return PairingBasis("same_provision")

    lineage = resolve_lineage([earlier.provision]).get(earlier.provision.pk)
    if lineage is not None:
        for link in lineage.successors.links:
            if link.provision.pk == later.provision.pk:
                return PairingBasis("mapped", verb=link.verb)

    return PairingBasis("unmapped")
