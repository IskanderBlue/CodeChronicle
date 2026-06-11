"""Provision lineage: predecessor/successor resolution across edition boundaries.

Resolves, for each provision, where it came from (predecessors in the
previous edition, or an intra-edition renumber) and where it went
(successors in the next edition) — the data behind the lineage rows on the
provenance rail and the viewer (``tasks/provision-lineage.md``).

Data contract (confirmed):

- ``ProvisionMapping`` rows are only ever emitted between *adjacent*
  editions — no chaining or multi-hop resolution anywhere.
- CCM emits a **total** cross-edition mapping: every carried-forward
  provision gets a row (identity carries arrive typed ``renumbered``; see
  the contract doc's typing-issue note).  On a **covered** transition (an
  ``EditionTransition`` row exists), every provision is accounted for by
  a row, a tombstone, or a sentinel — so absence of all three reads as
  discontinued.
- **Number equality proves nothing** (Iskander, 2026-06-11): the same
  bare provision number does not consistently map to the same provision
  across editions, so links come from mapping rows ONLY — there is no
  same-id fallback, on covered or uncovered transitions alike.

Per provision, per direction, exactly one of four states:

- ``linked`` — mapping row(s).  Multiple links only for split/merged.
  A ``not_processed`` disposition coexisting with forward rows is NOT a
  contradiction: it is one verdict with an extra leg whose content left
  the corpus (2006 B 12.3.4.6. split into 2012 B 12.3.1.4. *and*
  SB-10-delegated content) — surfaced via ``outside_corpus``.
- ``discontinued`` — covered transition, no row.  Forward,
  ``ProvisionDisposition`` records refine the marker: an explicit
  tombstone stays ``discontinued``; a ``not_processed`` disposition
  (content delegated outside the corpus) reads as ``no_data_yet``, not
  as a fifth state.
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
from typing import Any, TypeAlias

from django.db.models import Max, Min, Q

from core.access import edition_allowed
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EditionTransition,
    ProvisionDisposition,
    ProvisionMapping,
)
from core.permalinks import provision_permalink_url

# Direction states (template-comparable strings).
LINKED = "linked"
DISCONTINUED = "discontinued"
NO_DATA_YET = "no_data_yet"
ENDPOINT = "endpoint"

# Disposition status → direction state.  ``not_processed`` means the
# content's fate is outside our corpus, which is exactly what the
# "not yet covered" marker says — no fifth state.
_DISPOSITION_STATE: dict[str, str] = {
    ProvisionDisposition.Status.DISCONTINUED: DISCONTINUED,
    ProvisionDisposition.Status.NOT_PROCESSED: NO_DATA_YET,
}

# Row verbs per mapping type and direction, precomputed onto each link so
# every render site (rail, permalink, viewer) words the rows identically and
# the templates stay branch-free.  The same-id continuation ("" mapping
# type) reads as "continues"; templates add "(same number)" off ``same_id``.
_FORWARD_VERBS: dict[str, str] = {
    ProvisionMapping.MappingType.RENUMBERED: "renumbered to",
    ProvisionMapping.MappingType.SPLIT: "split into",
    ProvisionMapping.MappingType.MERGED: "merged into",
    ProvisionMapping.MappingType.REPLACED: "replaced by",
    "": "continues as",
}
_BACKWARD_VERBS: dict[str, str] = {
    ProvisionMapping.MappingType.RENUMBERED: "renumbered from",
    ProvisionMapping.MappingType.SPLIT: "split from",
    ProvisionMapping.MappingType.MERGED: "merged from",
    ProvisionMapping.MappingType.REPLACED: "replaces",
    "": "continues from",
}


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
    #: The target shares the bare provision number — via the same-id
    #: fallback *or* an identity-carry mapping row.  These get the
    #: "continues as/from" verbs; ``mapping_type`` tells the mechanisms apart.
    same_id: bool
    #: Intra-edition renumber row (both endpoints in this edition).
    same_edition: bool
    #: Direction-aware row phrase ("renumbered to" / "split from" / …).
    verb: str = ""
    #: Free-tier gate verdict — the target edition is outside the viewing
    #: user's scope, so render a locked upsell link, never the raw URL.
    #: Stamped by :func:`annotate_lineage_locks`, not the resolver (the
    #: resolver is user-agnostic).
    locked: bool = False


@dataclass
class LineageDirection:
    """One direction (predecessor or successor) of a provision's lineage."""

    state: str
    links: list[LineageLink] = field(default_factory=list)
    #: The adjacent edition the marker rows talk about ("transition to
    #: OBC 2024 not yet mapped"); ``None`` at an endpoint.
    edition: CodeEdition | None = None
    #: A ``not_processed`` disposition coexists with the mapping rows: the
    #: verdict has an additional leg whose content left the corpus (e.g. a
    #: split where one leg went to a supplementary standard).  Templates
    #: render an extra non-link leg row after the links.
    outside_corpus: bool = False
    #: Where the out-of-corpus content went, when the disposition names it
    #: ("SB-10"); "" when unknown.  Set alongside ``outside_corpus`` AND on
    #: a ``not_processed``-only ``no_data_yet`` direction, so the markers
    #: can read "…moved to SB-10, not yet covered" instead of the generic
    #: wording.
    outside_reference: str = ""


@dataclass
class Lineage:
    predecessors: LineageDirection
    successors: LineageDirection


#: Per-direction resolution plan from the first pass:
#: (state, mapping rows, adjacent edition).
_Plan: TypeAlias = tuple[str, list[ProvisionMapping], CodeEdition | None]


def resolve_lineage(
    provisions: Iterable[CodeEditionProvision],
) -> dict[int, Lineage]:
    """Resolve lineage for a batch of provisions in a fixed number of queries.

    Returns ``{provision_pk: Lineage}``.  Batched like
    ``_merge_provision_mapping_transitions`` so a page of search results
    doesn't go N+1: editions, coverage, mappings, dispositions, and
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

    # First pass: settle each direction's state.
    plans: dict[int, tuple[_Plan, _Plan]] = {}

    def _plan_direction(
        prov: CodeEditionProvision, rows: list[ProvisionMapping], *, forward: bool
    ) -> _Plan:
        edition = editions_by_pk[prov.edition_id]
        prev_ed, next_ed = neighbours[edition.pk]
        adjacent = next_ed if forward else prev_ed
        if rows:
            return (LINKED, rows, adjacent)
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
            return (state, [], None)
        key = (edition.pk, adjacent.pk) if forward else (adjacent.pk, edition.pk)
        if key not in covered:
            return (NO_DATA_YET, [], adjacent)
        # Covered + no row: discontinued (forward) / new in this edition
        # (backward).  CCM accounts for every provision on a covered
        # transition, and number equality proves nothing — never guess a
        # same-id link.
        return (DISCONTINUED, [], adjacent)

    for pk, prov in by_pk.items():
        plans[pk] = (
            _plan_direction(prov, pred_rows.get(pk, []), forward=False),
            _plan_direction(prov, succ_rows.get(pk, []), forward=True),
        )

    # Forward disposition markers, one query for the batch: a tombstone
    # keeps the discontinued marker; ``not_processed`` reads as "not yet
    # covered".  (Backward needs none — dispositions are keyed on the OLD
    # provision, and a covered transition with no incoming row already
    # reads "new in this edition".)
    dispositions: dict[tuple[int, int], tuple[str, str]] = {
        (prov_pk, edition_pk): (status, reference)
        for prov_pk, edition_pk, status, reference in ProvisionDisposition.objects.filter(
            provision_id__in=set(by_pk)
        ).values_list("provision_id", "new_edition_id", "status", "target_reference")
    }

    # Version bounds for every link target (v0 / last version), one query.
    target_pks: set[int] = set()
    for pred_plan, succ_plan in plans.values():
        for plan, forward in ((pred_plan, False), (succ_plan, True)):
            for row in plan[1]:
                target_pks.add(row.old_provision_id if not forward else row.new_provision_id)
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
        mapping_type = mapping.mapping_type if mapping else ""
        same_id = mapping is None or (
            mapping.old_provision.provision_id == mapping.new_provision.provision_id
        )
        verbs = _FORWARD_VERBS if forward else _BACKWARD_VERBS
        verb = verbs.get(mapping_type, verbs[""])
        # CCM emits a *total* cross-edition mapping and types identity
        # carries "renumbered" (the contract's identity-carry example): a
        # row whose endpoints share the number is a continuation, not a
        # renumber — word it as one.
        if same_id and mapping_type == ProvisionMapping.MappingType.RENUMBERED:
            verb = verbs[""]
        return LineageLink(
            provision=target,
            edition=edition,
            url=provision_permalink_url(
                edition.code_name, target.division, target.provision_id, version
            ),
            version=version,
            mapping_type=mapping_type,
            same_id=same_id,
            same_edition=same_edition,
            verb=verb,
        )

    def _build_direction(
        prov: CodeEditionProvision, plan: _Plan, *, forward: bool
    ) -> LineageDirection:
        state, rows, adjacent = plan
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
            # A coexisting ``not_processed`` disposition is the verdict's
            # out-of-corpus leg (one split, two successors — one of them in
            # a document we don't carry), not a producer contradiction the
            # way row+tombstone is.  Merges can have the mirror-image leg,
            # but CCM has no backward emission shape for it yet.
            disposition = (
                dispositions.get((prov.pk, adjacent.pk))
                if forward and adjacent is not None
                else None
            )
            outside_corpus = bool(
                disposition
                and disposition[0] == ProvisionDisposition.Status.NOT_PROCESSED
            )
            return LineageDirection(
                state=LINKED,
                links=links,
                edition=adjacent,
                outside_corpus=outside_corpus,
                outside_reference=disposition[1] if outside_corpus and disposition else "",
            )
        outside_reference = ""
        if forward and state == DISCONTINUED and adjacent is not None:
            disposition = dispositions.get((prov.pk, adjacent.pk))
            if disposition is not None:
                status, reference = disposition
                state = _DISPOSITION_STATE.get(status, NO_DATA_YET)
                if status == ProvisionDisposition.Status.NOT_PROCESSED:
                    outside_reference = reference
        return LineageDirection(
            state=state, edition=adjacent, outside_reference=outside_reference
        )

    return {
        pk: Lineage(
            predecessors=_build_direction(prov, plans[pk][0], forward=False),
            successors=_build_direction(prov, plans[pk][1], forward=True),
        )
        for pk, prov in by_pk.items()
    }


def annotate_lineage_locks(lineages: Iterable[Lineage], user: Any) -> None:
    """Stamp the free-tier gate verdict on every link, in place.

    Lineage links are inherently cross-edition, so a link's target can sit
    outside the viewing user's scope even when the source provision is in
    scope.  Locked links render as an upsell to pricing, never a raw URL
    that 403s after click-through (the permalink view's teaser is only the
    backstop).  Inert (everything unlocked) while gating is disabled.
    """
    for lineage in lineages:
        for direction in (lineage.predecessors, lineage.successors):
            for link in direction.links:
                link.locked = not edition_allowed(user, link.edition.code_name)
