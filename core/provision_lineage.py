"""Provision lineage: predecessor/successor resolution across edition boundaries.

Resolves, for each provision, where it came from (predecessors in the
previous edition, or an intra-edition renumber) and where it went
(successors in the next edition) — the data behind the lineage rows on the
provenance rail and the viewer (``tasks/provision-lineage.md``).

Data contract (confirmed):

- ``ProvisionMapping`` rows are only ever emitted between *adjacent*
  editions — no chaining or multi-hop resolution anywhere.
- CCM emits mapping rows only where identity *changed*.  On a **covered**
  transition (an ``EditionTransition`` row exists), absence of a mapping row
  positively asserts "same division/id continues" — the same-id fallback is
  trusted there and *only* there.  On an uncovered transition the id may
  have been renumbered away or reused, so we never guess.

Per provision, per direction, exactly one of four states:

- ``linked`` — mapping row(s), or same (division, id) continues on a
  covered transition.  Multiple links only for split/merged.
- ``discontinued`` — covered transition, no row, no same-id match.
- ``no_data_yet`` — a neighbouring edition exists in reality but the
  transition isn't mapped (includes editions beyond the corpus window:
  the corpus edge is just an uncovered transition, not "nothing exists").
- ``endpoint`` — no neighbouring edition exists in reality: first edition
  ever (``Code.first_edition_date``) / still-current edition (newest loaded
  edition open-ended, the same distinction ``CorpusCurrency.refresh`` draws).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TypeAlias

from django.db.models import Max, Min, Q

from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EditionTransition,
    ProvisionMapping,
)
from core.permalinks import provision_permalink_url

# Direction states (template-comparable strings).
LINKED = "linked"
DISCONTINUED = "discontinued"
NO_DATA_YET = "no_data_yet"
ENDPOINT = "endpoint"

# Same-id fallback division preference when a bare id exists in several
# divisions of the target edition (after the source provision's own
# division): body divisions over appendices, then division-less.
_DIVISION_PREFERENCE = ["B", "C", "D", "A", ""]


@dataclass
class LineageLink:
    """One predecessor/successor link, ready to render."""

    provision: CodeEditionProvision
    edition: CodeEdition
    url: str
    #: Version the URL points at — successor → its v0 (birth in the new
    #: edition); predecessor → its last version (the one that handed off);
    #: intra-edition renumber successor → ``introduced_by_version``.
    version: int
    #: ``ProvisionMapping.MappingType`` value; ``""`` for a same-id
    #: continuation (no mapping row on a covered transition).
    mapping_type: str
    same_id: bool
    #: Intra-edition renumber row (both endpoints in this edition).
    same_edition: bool


@dataclass
class LineageDirection:
    """One direction (predecessor or successor) of a provision's lineage."""

    state: str
    links: list[LineageLink] = field(default_factory=list)
    #: The adjacent edition the marker rows talk about ("transition to
    #: OBC 2024 not yet mapped"); ``None`` at an endpoint.
    edition: CodeEdition | None = None


@dataclass
class Lineage:
    predecessors: LineageDirection
    successors: LineageDirection


#: Per-direction resolution plan from the first pass:
#: (state, mapping rows, adjacent edition, same-id fallback key).  The
#: fallback key is set only when the direction needs the same-id lookup to
#: decide linked vs discontinued.
_Plan: TypeAlias = tuple[
    str, list[ProvisionMapping], CodeEdition | None, tuple[int, str] | None
]


def resolve_lineage(
    provisions: Iterable[CodeEditionProvision],
) -> dict[int, Lineage]:
    """Resolve lineage for a batch of provisions in a fixed number of queries.

    Returns ``{provision_pk: Lineage}``.  Batched like
    ``_merge_provision_mapping_transitions`` so a page of search results
    doesn't go N+1: editions, coverage, mappings, same-id candidates, and
    version bounds are each one query for the whole batch.
    """
    by_pk: dict[int, CodeEditionProvision] = {p.pk: p for p in provisions}
    if not by_pk:
        return {}

    edition_pks = {p.edition_id for p in by_pk.values()}
    code_ids = set(
        CodeEdition.objects.filter(pk__in=edition_pks).values_list("code_id", flat=True)
    )

    # All real editions of the involved codes, in chain order — adjacency is
    # position in this list.  Restricted to editions that actually carry
    # provisions: the shared code_editions table also holds search-metadata-
    # only editions (OBC_2012_v05, OBC_2024, …) with no provision data — the
    # same trap CorpusCurrency.refresh dodges with its regulation-count
    # filter.  A provision-less edition can't take part in provision lineage,
    # and treating one as "adjacent" would wreck neighbour detection and the
    # endpoint logic alike.
    editions_by_code: dict[int, list[CodeEdition]] = defaultdict(list)
    editions_by_pk: dict[int, CodeEdition] = {}
    for edition in (
        CodeEdition.objects.filter(code_id__in=code_ids, provisions__isnull=False)
        .distinct()
        .select_related("code")
        .order_by("effective_date", "year", "edition_id")
    ):
        editions_by_code[edition.code_id].append(edition)
        editions_by_pk[edition.pk] = edition

    neighbours: dict[int, tuple[CodeEdition | None, CodeEdition | None]] = {}
    for chain in editions_by_code.values():
        for i, edition in enumerate(chain):
            prev_ed = chain[i - 1] if i > 0 else None
            next_ed = chain[i + 1] if i < len(chain) - 1 else None
            neighbours[edition.pk] = (prev_ed, next_ed)

    covered: set[tuple[int, int]] = set(
        EditionTransition.objects.filter(
            old_edition__code_id__in=code_ids
        ).values_list("old_edition_id", "new_edition_id")
    )

    pred_rows: dict[int, list[ProvisionMapping]] = defaultdict(list)
    succ_rows: dict[int, list[ProvisionMapping]] = defaultdict(list)
    for mapping in (
        ProvisionMapping.objects.filter(
            Q(old_provision_id__in=by_pk) | Q(new_provision_id__in=by_pk)
        )
        .select_related("old_provision", "new_provision", "introduced_by_version")
    ):
        if mapping.old_provision_id in by_pk:
            succ_rows[mapping.old_provision_id].append(mapping)
        if mapping.new_provision_id in by_pk:
            pred_rows[mapping.new_provision_id].append(mapping)

    # First pass: settle each direction's state; collect the same-id lookups
    # and link targets so they batch.
    plans: dict[int, tuple[_Plan, _Plan]] = {}
    fallback_keys: set[tuple[int, str]] = set()

    def _plan_direction(
        prov: CodeEditionProvision, rows: list[ProvisionMapping], *, forward: bool
    ) -> _Plan:
        edition = editions_by_pk[prov.edition_id]
        prev_ed, next_ed = neighbours[edition.pk]
        adjacent = next_ed if forward else prev_ed
        if rows:
            return (LINKED, rows, adjacent, None)
        if adjacent is None:
            if forward:
                # Newest loaded edition: open-ended = still the current
                # edition (true endpoint); closed = a real successor exists
                # that we haven't mapped.
                state = ENDPOINT if edition.ineffective_date is None else NO_DATA_YET
            else:
                # Earliest loaded edition: only the seeded first-edition fact
                # can prove nothing came before; unseeded defaults to the
                # honest "no data yet".
                first = edition.code.first_edition_date
                state = ENDPOINT if first and edition.effective_date == first else NO_DATA_YET
            return (state, [], None, None)
        key = (edition.pk, adjacent.pk) if forward else (adjacent.pk, edition.pk)
        if key not in covered:
            return (NO_DATA_YET, [], adjacent, None)
        fallback_key = (adjacent.pk, prov.provision_id)
        fallback_keys.add(fallback_key)
        return (DISCONTINUED, [], adjacent, fallback_key)

    for pk, prov in by_pk.items():
        plans[pk] = (
            _plan_direction(prov, pred_rows.get(pk, []), forward=False),
            _plan_direction(prov, succ_rows.get(pk, []), forward=True),
        )

    # Same-id candidates, one query for every (edition, id) pair needed.
    candidates: dict[tuple[int, str], list[CodeEditionProvision]] = defaultdict(list)
    if fallback_keys:
        fallback_filter = Q()
        for adj_pk, provision_id in fallback_keys:
            fallback_filter |= Q(edition_id=adj_pk, provision_id=provision_id)
        for cand in CodeEditionProvision.objects.filter(fallback_filter):
            candidates[(cand.edition_id, cand.provision_id)].append(cand)

    def _pick_same_id(
        prov: CodeEditionProvision, key: tuple[int, str]
    ) -> CodeEditionProvision | None:
        pool = candidates.get(key, [])
        for division in [prov.division, *_DIVISION_PREFERENCE]:
            for cand in pool:
                if cand.division == division:
                    return cand
        return min(pool, key=lambda c: c.division) if pool else None

    # Version bounds for every link target (v0 / last version), one query.
    target_pks: set[int] = set()
    for pred_plan, succ_plan in plans.values():
        for plan, forward in ((pred_plan, False), (succ_plan, True)):
            for row in plan[1]:
                target_pks.add(row.old_provision_id if not forward else row.new_provision_id)
    for pk, prov in by_pk.items():
        for plan in plans[pk]:
            if plan[3] is not None:
                fallback_target = _pick_same_id(prov, plan[3])
                if fallback_target is not None:
                    target_pks.add(fallback_target.pk)
    bounds: dict[int, tuple[int, int]] = {
        row["provision_id"]: (row["vmin"], row["vmax"])
        for row in CodeEditionProvisionVersion.objects.filter(provision_id__in=target_pks)
        .values("provision_id")
        .annotate(vmin=Min("version"), vmax=Max("version"))
    }

    def _link(
        target: CodeEditionProvision,
        *,
        forward: bool,
        mapping: ProvisionMapping | None,
    ) -> LineageLink:
        edition = editions_by_pk[target.edition_id]
        vmin, vmax = bounds.get(target.pk, (0, 0))
        same_edition = bool(
            mapping and mapping.old_provision.edition_id == mapping.new_provision.edition_id
        )
        if not forward:
            version = vmax  # the version that handed off
        elif same_edition and mapping and mapping.introduced_by_version is not None:
            version = mapping.introduced_by_version.version
        else:
            version = vmin  # birth in the new edition
        return LineageLink(
            provision=target,
            edition=edition,
            url=provision_permalink_url(
                edition.code_name, target.division, target.provision_id, version
            ),
            version=version,
            mapping_type=mapping.mapping_type if mapping else "",
            same_id=mapping is None,
            same_edition=same_edition,
        )

    def _build_direction(
        prov: CodeEditionProvision, plan: _Plan, *, forward: bool
    ) -> LineageDirection:
        state, rows, adjacent, fallback_key = plan
        if rows:
            links = [
                _link(
                    row.new_provision if forward else row.old_provision,
                    forward=forward,
                    mapping=row,
                )
                for row in rows
            ]
            links.sort(key=lambda li: (li.provision.division, li.provision.provision_id))
            return LineageDirection(state=LINKED, links=links, edition=adjacent)
        if fallback_key is not None:
            cand = _pick_same_id(prov, fallback_key)
            if cand is not None:
                return LineageDirection(
                    state=LINKED,
                    links=[_link(cand, forward=forward, mapping=None)],
                    edition=adjacent,
                )
        return LineageDirection(state=state, edition=adjacent)

    return {
        pk: Lineage(
            predecessors=_build_direction(prov, plans[pk][0], forward=False),
            successors=_build_direction(prov, plans[pk][1], forward=True),
        )
        for pk, prov in by_pk.items()
    }
