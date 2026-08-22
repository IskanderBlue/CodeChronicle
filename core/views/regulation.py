"""
Regulation browsing views.
"""

import re
from datetime import date
from typing import Any

from django.contrib.auth.views import redirect_to_login
from django.db.models import prefetch_related_objects
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from api.formatters import (
    provenance_lines,
    replacement_commencement,
    select_commencement_record,
)
from config.part_applicability import part_of
from core.access import edition_allowed, edition_gate
from core.attribution import (
    crown_years_for_provisions,
    crown_years_for_regulations,
)
from core.citations import in_force_phrase
from core.compare import (
    annotate_chain_comparisons,
    annotate_lineage_comparisons,
    prepared_pair,
)
from core.cross_refs import annotate_versions, cited_by
from core.events import arrival_context, record_event
from core.http_cache import corpus_conditional
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
    ProvisionVersionTable,
    Regulation,
    RegulationClause,
    natural_provision_key,
)
from core.page_crops import build_crops
from core.permalinks import (
    edition_contents_url,
    provision_permalink_url,
    provision_print_url,
    provision_text_url,
)
from core.print_options import apply_tables_mode, resolve_tables_mode, toggle_query
from core.provision_lineage import (
    annotate_lineage_locks,
    annotate_lineage_titles,
    resolve_lineage,
)
from core.reading_ledger import record_versions
from core.seo import (
    TITLE_SUFFIX,
    amending_regulations,
    base_regulation,
    exhibit_title,
    last_governed_day,
    provision_jsonld,
    provision_page_meta,
    regulation_jsonld,
    site_origin,
)
from core.subtrees import contents_view, related_links, walk_subtree
from core.verification import base_input, build_rail
from core.views.search import in_force_versions

# ── Clause-target display + linking ──────────────────────────────────────
# A clause can touch several provisions at once — it produced (contributed
# to) a version of each.  Rather than collapse to one "best" target, we list
# them ALL: one entry per distinct provision, each linking the earliest
# version the clause produced of it.  The authoritative set comes from the
# through model (``contributed_to_versions``), which carries provision,
# division, and version number directly.
#
# Fallback (``_fallback_targets``): some clauses have a stated ``target_id``
# but no materialised contribution — notably base-regulation *enact* clauses,
# whose v0 provisions aren't linked back to the base reg (a CCM data gap).
# For those we still show the stated target, resolved to its provision and
# the version in force on the regulation's effective date, so the label/link
# never silently disappears.  ``target_id`` reduction is used only here.

_ITEM_RE = re.compile(r"\(Item \d+\)")
_PAREN_RE = re.compile(r"\([^)]*\)")
_TABLE_LETTER_RE = re.compile(r"[A-Z]\.$")


def _reduce_target_id(clause: RegulationClause) -> str:
    """Reduce a target_id to the provision_id it lives in (drop sentence/
    clause parts, item numbers, and trailing table letters)."""
    tid = _ITEM_RE.sub("", clause.target_id or "")
    tid = _PAREN_RE.sub("", tid).strip()
    if clause.target_level in ("table", "table_item"):
        tid = _TABLE_LETTER_RE.sub("", tid).strip()
    return tid


def _stated_label(clause: RegulationClause) -> str:
    """Human label from the clause's own ``target_level``/``target_id``.

    Used when no provision row backs the target — tables collapse to
    "Table <id>", everything else keeps "<Level> <id>".
    """
    tid = clause.target_id or ""
    if clause.target_level in ("table", "table_item"):
        return f"Table {_ITEM_RE.sub('', tid).strip()}".strip()
    if not clause.target_level:
        return tid
    return f"{clause.get_target_level_display()} {tid}".strip()


def _fallback_targets(clause: RegulationClause) -> list[dict[str, Any]]:
    """A single target from the stated ``target_id`` when none materialised.

    Resolves the reduced target_id to a provision in the clause's edition and
    links the version in force on the regulation's effective date (earliest
    if none is in force then).  Degrades to a label-only entry when the
    provision can't be found — never silently empty.
    """
    tid = _reduce_target_id(clause)
    if not tid:
        return []
    qs = CodeEditionProvision.objects.filter(
        edition=clause.regulation.edition, provision_id=tid,
    )
    prov = qs.filter(division=clause.target_division or "").first() or qs.first()
    versions = sorted(prov.versions.all(), key=lambda v: v.version) if prov else []
    if prov is None or not versions:
        return [{
            "label": _stated_label(clause),
            "url": None,
            "level": clause.target_level,
            "version": None,
            "title": "",
            "indent": 0,
        }]
    chosen = next(
        (v for v in versions if v.in_force_on(clause.regulation.effective_date)),
        versions[0],
    )
    return [{
        "label": f"{prov.get_level_display()} {prov.provision_id}".strip(),
        "url": provision_permalink_url(
            prov.edition.code_name, prov.division, prov.provision_id, chosen.version
        ),
        "level": prov.level,
        "version": chosen.version,
        "title": chosen.title,
        "indent": 0,
    }]


def _clause_self_address(clause: RegulationClause) -> str:
    """The provision address a base regulation's clause_id encodes — its home.

    A base reg's clause_id *is* a provision reference: ``4.2.1.1(2)`` means
    Article 4.2.1.1., sentence (2).  Drop the sentence parenthetical and
    normalise the trailing dot.  Empty for ordinal amendment clause_ids
    (``164``, ``138``), detected by the absence of an interior dot — those
    aren't provision addresses and must not be mistaken for a home article.
    """
    base = _PAREN_RE.sub("", clause.clause_id or "").strip()
    if "." not in base:
        return ""
    return base if base.endswith(".") else base + "."


def _clause_targets(clause: RegulationClause) -> list[dict[str, Any]]:
    """Every provision a clause affects, as hierarchy-ordered permalinks.

    One entry per distinct provision (the earliest version this clause
    produced of it), sorted in natural order and tagged with an ``indent``
    so nested targets read under their ancestors.  ``version`` is None for a
    regulation-level target (a revocation links straight to the other
    regulation, which has no provision version).
    """
    # Regulation-level target (e.g. a revocation): no provision versions —
    # link to the other regulation directly.
    if clause.target_level == "regulation":
        reg = Regulation.objects.filter(reg_id=clause.target_id).first()
        return [{
            "label": f"O. Reg. {clause.target_id}",
            "url": reverse("core:regulation_detail", args=[reg.pk]) if reg else None,
            "level": "regulation",
            "version": None,
            # A regulation target has no provision title; the label already
            # names the regulation, which is what that page is about.
            "title": "",
            "indent": 0,
        }]

    versions = list(clause.contributed_to_versions.all())
    if not versions:
        return _fallback_targets(clause)

    # Collapse to one version per provision — the earliest the clause produced
    # (v0 for a base enactment, v1+ for an amendment).  Keyed by provision pk.
    earliest: dict[int, CodeEditionProvisionVersion] = {}
    for v in versions:
        cur = earliest.get(v.provision_id)
        if cur is None or v.version < cur.version:
            earliest[v.provision_id] = v

    chosen = sorted(
        earliest.values(), key=lambda v: _natural_key(v.provision.provision_id)
    )

    # Drop the clause's own home article: a base reg's clause_id is a provision
    # reference (e.g. 4.2.1.1(2) lives at Article 4.2.1.1.), and the
    # version→clause linkage records the clause against its own home version.
    # That home isn't a target — it's the clause's location, already shown as
    # the clause identifier.  Fall through to the declared target_id if dropping
    # it leaves nothing (a clause whose only contribution was its own home).
    own_addr = _clause_self_address(clause)
    if own_addr:
        chosen = [v for v in chosen if v.provision.provision_id != own_addr]
        if not chosen:
            return _fallback_targets(clause)

    ids = [(v.provision.provision_id, v.provision.division) for v in chosen]

    targets: list[dict[str, Any]] = []
    for v in chosen:
        prov = v.provision
        # Indent depth: how many other targets are ancestors of this one
        # (same division, a strict dotted prefix of its provision_id).  Zero
        # when there's no nesting among the affected set — "hierarchy if
        # applicable" falls out for free.
        depth = sum(
            1
            for pid, div in ids
            if div == prov.division
            and pid != prov.provision_id
            and prov.provision_id.startswith(pid)
        )
        label = f"{prov.get_level_display()} {prov.provision_id}".strip()
        targets.append({
            "label": label,
            "url": provision_permalink_url(
                prov.edition.code_name, prov.division, prov.provision_id, v.version
            ),
            "level": prov.level,
            "version": v.version,
            # Each target is a provision other than the one being read, so the
            # link names it (tasks/c-lineage-anchor-text.md).  This version's
            # own title, not the provision's latest — the title can change
            # between versions.  Free: ``v`` is already in hand.
            "title": v.title,
            "indent": depth * 12,
        })
    return targets


#: Provision-id ordering, shared with every other surface that lists
#: provisions (``core.models.natural_provision_key``).
_natural_key = natural_provision_key


def _edition_roots(edition: CodeEdition) -> list[CodeEditionProvision]:
    """The top of one edition's structure, in reading order.

    A root is a provision with no parent.  What that *is* differs by edition
    and the difference is real, not a defect: OBC 2006 and 2012 carry a
    division-level provision (``A`` / ``B`` / ``C``) that owns the parts,
    while OBC 1997 has no division at all and its twelve parts are the roots.
    So this returns divisions for one edition and parts for another, and the
    ladder above it must not assume which.

    Provisions with a blank ``level`` are excluded.  Six of them exist in
    OBC 2012 Division B (``Table-1.3.1.2.``, ``3.2.4.22(13)`` and four more):
    no parent, no children, no level.  They are loose rows rather than a rung
    of the structure, and listing them beside A, B and C would say the corpus
    has nine divisions.  They are unreachable by navigation either way — a
    CCM question, not one this page can answer.
    """
    roots = (
        CodeEditionProvision.objects
        .filter(edition=edition, parent__isnull=True)
        .exclude(level="")
        .prefetch_related("versions")
    )
    return sorted(roots, key=lambda p: (p.division, _natural_key(p.provision_id)))


def _sibling_editions(edition: CodeEdition) -> list[CodeEdition]:
    """Every edition of the same code that a reader can actually open.

    Loaded editions only.  The corpus carries a placeholder row for each
    consolidation of an edition (``OBC 2006_v07`` and some sixty more) and a
    row for every code we intend to hold but do not yet — all of them with
    zero provisions.  A pager offering those would be a list of empty rooms,
    so the test is whether the edition has any structure, which is the same
    thing as whether it can be navigated.
    """
    return list(
        CodeEdition.objects
        .filter(code=edition.code, provisions__isnull=False)
        .distinct()
        .order_by("effective_date")
    )


def _sibling_link(
    provision: CodeEditionProvision, day: date, code_name: str
) -> dict[str, Any]:
    """Link to a sibling provision as it reads on ``day`` (the pinned date).

    A pager (prev/next) points at one version, not many, so pick the
    sibling version in force on the pinned version's effective date; fall
    back to the earliest version when nothing is in force then (e.g. the
    sibling didn't exist yet).

    Shaped exactly like :func:`core.subtrees.related_links` — a ``versions`` list holding
    one entry — so all four nav groups (pager, parent, children) render
    through one partial and align on one grid.  A pager row that built its
    own markup was how the ids stopped lining up.
    """
    versions = sorted(provision.versions.all(), key=lambda v: v.version)
    chosen = next((v for v in versions if v.in_force_on(day)), versions[0])
    return {
        "provision_id": provision.provision_id,
        # The pager names a sibling — a different provision — so the link
        # text carries its title (tasks/c-lineage-anchor-text.md).
        "title": chosen.title,
        "versions": [{
            "version": chosen.version,
            "title": chosen.title,
            "effective_date": chosen.effective_date,
            "last_day": last_governed_day(chosen.ineffective_date),
            "never_in_force": chosen.never_in_force,
            "url": provision_permalink_url(
                code_name, provision.division, provision.provision_id, chosen.version
            ),
        }],
    }


def provenance_result(
    matched: CodeEditionProvision,
    target_version: CodeEditionProvisionVersion,
    code_name: str,
    division: str,
    provision_id: str,
    user: Any = None,
) -> dict[str, Any]:
    """The ``result`` shape the search provenance banner expects.

    Mirrors the subset of ``api.formatters._format_single_result`` the
    ``_provenance_banner.html`` partial reads — version, amending clause,
    base regulation, full chain, next version, and lineage rows — so the
    permalink can reuse the same banner.  ``band`` is None (no query date
    here), which the partial already treats as "no query-date rail /
    coverage cell".  ``user`` feeds the free-tier gate on lineage links.
    """
    chain = list(matched.versions.order_by("version"))
    # The provision's own base reg: edition base for a base original, the
    # introducing amendment for an amend-add-created provision (see
    # CodeEditionProvision.origin_regulation).
    base_regulation = matched.origin_regulation
    is_added = target_version.is_added_origin
    clause = target_version.last_contributing_clause
    next_version = next(
        (v for v in chain if v.version > target_version.version), None
    )
    # The amendment chain, for the Reference citation.  It names the provision
    # itself with the shared pinpoint helper and prints these lines underneath.
    chain_lines = provenance_lines(
        version=target_version,
        most_recent_clause=clause,
        base_regulation=base_regulation,
        next_version=next_version,
        is_added=is_added,
    )
    next_clause = next_version.last_contributing_clause if next_version else None
    lineage = resolve_lineage([matched])[matched.pk]
    annotate_lineage_locks([lineage], edition_gate(user))
    annotate_lineage_titles([lineage])
    # Commencement proof for both band edges, mirroring
    # api.formatters._format_single_result: a base version's From falls back
    # to the base regulation's own schedule, and an edition-final version's
    # Until falls back to the replacing edition's base regulation.
    from_commencement = clause.commencement if clause else None
    if from_commencement is None and clause is None and base_regulation is not None:
        from_commencement = select_commencement_record(
            base_regulation.commencement,
            provision_id,
            division,
            target_version.effective_date,
        )
    until_commencement = next_clause.commencement if next_clause else None
    until_commencement_date = next_version.effective_date if next_version else None
    if (
        until_commencement is None
        and next_version is None
        and target_version.ineffective_date is not None
    ):
        until_commencement = replacement_commencement(
            matched.edition,
            provision_id,
            division,
            target_version.ineffective_date,
        )
        until_commencement_date = (
            target_version.ineffective_date if until_commencement else None
        )
    annotate_lineage_comparisons(
        target_version, lineage.predecessors, lineage.successors,
    )
    # ``next_version`` is not in ``chain`` — the chain is what has happened,
    # and the next version has not yet.  It still deserves a compare link: "what
    # is about to change" is the same question as "what changed", asked early.
    annotate_chain_comparisons(
        target_version,
        [*chain, next_version] if next_version is not None else chain,
    )
    return {
        "version": target_version,
        "clause": clause,
        "is_base": clause is None,
        "is_added": is_added,
        "base_regulation": base_regulation,
        "next_version": next_version,
        "lineage_predecessors": lineage.predecessors,
        "lineage_successors": lineage.successors,
        # The comparison "Compare versions" opens.  Same ladder the search
        # results use, over the keys just above — never a second definition
        # of what a prepared pair is.  ``annotate_lineage_comparisons`` runs
        # just before the return, so the lineage rows carry their own
        # cross-edition comparisons too.
        "compare_pair": prepared_pair(
            version=target_version,
            chain=chain or [target_version],
            predecessors=lineage.predecessors,
            successors=lineage.successors,
        ),
        "from_commencement": from_commencement,
        "until_commencement": until_commencement,
        "until_commencement_date": until_commencement_date,
        "amendment_chain": chain,
        "provenance_lines": chain_lines,
        # Attestation rail. The permalink has no user query date, so it reads the
        # rail at this version's own commencement (the direct replacement for the
        # old "as it read [date]" line) — verification status at its From. The base
        # regulation is folded in as the enactment origin.
        "rail": build_rail(
            target_version,
            target_version.effective_date,
            date.today(),
            base=base_input(base_regulation),
        ),
        # Provision identity, so the banner can build per-version permalinks
        # (same keys the search formatter supplies: code_edition/division/id).
        "code_edition": code_name,
        "division": division,
        "id": provision_id,
    }


_TABLE_REF_RE = re.compile(r"^Table-", re.IGNORECASE)
_APPENDIX_TABLE_RE = re.compile(r"^[A-Za-z]-")


def _is_appendix_table(label: str) -> bool:
    """An appendix table ref (``Table-A-10``) — a ``Table-`` whose body is a
    letter-dash form, not a numeric article address."""
    return bool(_TABLE_REF_RE.match(label)) and bool(
        _APPENDIX_TABLE_RE.match(label[len("Table-"):])
    )


def _format_table_label(table_id: str) -> str:
    """Display form of an appendix table id: ``Table-A-10`` → ``Table A-10``."""
    return f"Table {table_id[len('Table-'):]}" if _TABLE_REF_RE.match(table_id) else table_id


def _reduce_provision_ref(raw: str) -> str:
    """Reduce a commencement provision ref to the provision it lives in.

    Refs arrive at whatever granularity the amending clause operated, since
    they're the clauses' resolved targets — a sentence/clause/subclause
    (``4.2.1.1.(1)(b)``), a whole article (``3.1.4.2.``), or a numbered table
    (``Table-11.2.1.1.B.``).  Permalinks exist only at the article level, so
    everything collapses to its containing article:

    - Sentence/clause/subclause: drop everything from the first ``(``.
    - Table ``Table-<article>[.<letter>.]``: strip the ``Table-`` prefix and
      keep the first four dotted segments — the article the table hangs off.
      Its trailing table-letter (``.B.``, ``.D/E.``) is a fifth segment that
      names *which* table on that article and isn't part of the address.
      The 4th segment may carry a letter (``3.3.2.8A.``) — that stays.

    Appendix tables (``Table-A-10``) carry no article address, so they're
    handled separately — :func:`_is_appendix_table` routes them to a
    ``ProvisionVersionTable`` lookup (the link lives on the provision side).
    """
    if _TABLE_REF_RE.match(raw):
        body = raw[len("Table-"):]
        if _APPENDIX_TABLE_RE.match(body):
            return raw
        segments = [s for s in body.split(".") if s]
        article = ".".join(segments[:4])
        return f"{article}." if article else raw
    return raw.split("(", 1)[0].strip()


def _commencement_schedule(
    regulation: Regulation,
) -> list[dict[str, Any]]:
    """Shape ``Regulation.commencement`` into display rows — one per parsed
    commencement record, sorted by in-force date (default first).

    A regulation's blanket ``effective_date`` is only its *default*
    commencement; Ontario regs routinely stagger later in-force dates for
    specific provisions.  Each record's ``resolved_provisions`` is a list of
    ``"<provision_id>|<division>"`` refs (bare-letter division per
    reference_division_format) — the *targets* of the amending clauses the
    commencement subsection names, at whatever granularity each clause
    operated.  We split them into:

    - ``provisions`` — sentence/clause/article/numbered-table refs reduced to
      their containing article (:func:`_reduce_provision_ref`), **deduped by
      provision** (one clause can touch a sentence five times; O. Reg. 88/19
      defers 441 raw refs that collapse to far fewer articles).
    - ``tables`` — appendix tables (``Table-A-10``), which have no article
      address of their own; each links to the provision(s) that *own* it,
      resolved on the provision side via ``ProvisionVersionTable``.

    Both link to the version in force on the record's date — the version the
    deferral brings into effect.  The template renders this schedule only
    when it carries a staggered (non-default) date.
    """
    code_name = regulation.edition.code_name
    rows: list[dict[str, Any]] = []
    for rec in regulation.commencement or []:
        provisions: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        seen_provisions: set[tuple[str, str]] = set()
        seen_tables: set[str] = set()
        for ref in rec.get("resolved_provisions") or []:
            label, _, division = str(ref).partition("|")
            if _is_appendix_table(label):
                if label in seen_tables:
                    continue
                seen_tables.add(label)
                tables.append({
                    "table_id": label,
                    "label": _format_table_label(label),
                    "division": division,
                    "owners": [],
                })
                continue
            provision_id = _reduce_provision_ref(label)
            key = (division, provision_id)
            if key in seen_provisions:
                continue
            seen_provisions.add(key)
            provisions.append({
                "provision_id": provision_id,
                "division": division,
                "url": None,
            })
        tables.sort(key=lambda t: _natural_key(t["table_id"]))
        rows.append({
            "date": _parse_iso_date(rec.get("effective_date")),
            "is_default": bool(rec.get("is_default")),
            "clause": rec.get("clause", ""),
            "text": rec.get("commencement_clause", ""),
            "provisions": provisions,
            "tables": tables,
            "affected_count": len(provisions) + len(tables),
        })
    _link_commencement_provisions(regulation, code_name, rows)
    for row in rows:
        row["provision_groups"] = _group_provisions(row["provisions"], row["tables"])
    rows.sort(key=lambda r: (r["date"] or date.min, not r["is_default"]))
    return rows


# Appendix tables (``Table-A-<n>``) carry no Part in their id, but in the OBC
# they're all Part 9 housing tables — so they're grouped under their
# division's Part 9 alongside the Part 9 provisions.
_APPENDIX_TABLE_PART = 9


def _group_provisions(
    provisions: list[dict[str, Any]],
    tables: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group the (already-linked) provisions and appendix tables by Division
    then Part so a large deferral (O. Reg. 191/14 defers 156) reads as a few
    labelled blocks the template can flow through columns, rather than one
    undifferentiated blob.

    Grouping by ``(division, part)`` also fixes cross-division interleaving:
    a flat natural sort on ``provision_id`` alone would sort ``1.1.2.1.`` (Div
    A) next to ``1.3.1.1.`` (Div B).  Appendix tables join their division's
    Part 9 bucket (see ``_APPENDIX_TABLE_PART``).  Within each block,
    provisions are natural-sorted and the tables follow.
    """
    buckets: dict[tuple[str, int | None], dict[str, list[dict[str, Any]]]] = {}

    def _bucket(division: str, part: int | None) -> dict[str, list[dict[str, Any]]]:
        return buckets.setdefault(
            (division, part), {"provisions": [], "tables": []}
        )

    for p in provisions:
        _bucket(p["division"], part_of(p["provision_id"]))["provisions"].append(p)
    for t in tables or []:
        _bucket(t["division"], _APPENDIX_TABLE_PART)["tables"].append(t)

    def _group_key(key: tuple[str, int | None]) -> tuple[str, int]:
        division, part = key
        # Parts in number order; an id with no Part sorts after all of them.
        return (division, part if part is not None else 1_000_000)

    groups: list[dict[str, Any]] = []
    for division, part in sorted(buckets, key=_group_key):
        if division and part is not None:
            group_label = f"Div {division} · Part {part}"
        elif part is not None:
            group_label = f"Part {part}"
        elif division:
            group_label = f"Div {division}"
        else:
            group_label = "Other"
        bucket = buckets[(division, part)]
        groups.append({
            "label": group_label,
            "provisions": sorted(
                bucket["provisions"], key=lambda p: _natural_key(p["provision_id"])
            ),
            "tables": sorted(
                bucket["tables"], key=lambda t: _natural_key(t["table_id"])
            ),
        })
    return groups


def _dated_provision_url(
    provision: CodeEditionProvision, day: date | None, code_name: str
) -> str:
    """Permalink for ``provision`` as it reads on ``day`` — the version in
    force then, falling back to the earliest."""
    versions = sorted(provision.versions.all(), key=lambda v: v.version)
    chosen = next(
        (v for v in versions if day and v.in_force_on(day)), versions[0]
    )
    return provision_permalink_url(
        code_name, provision.division, provision.provision_id, chosen.version
    )


def _link_commencement_provisions(
    regulation: Regulation, code_name: str, rows: list[dict[str, Any]]
) -> None:
    """Fill in each schedule entry's permalink(s) in place.

    Two batched lookups for the whole schedule (88/19 defers hundreds):

    - **Provisions** — one ``provision_id__in`` query; each links to the
      version in force on its record's date.  A ref resolving to no
      provision/version keeps ``url=None``.
    - **Appendix tables** — one ``ProvisionVersionTable`` query keyed by
      ``table_id``; the link lives on the provision side, so a table can own
      several provisions (``Table-A-12`` → four).  Each owner is listed as a
      dated permalink.
    """
    prov_keys = {
        (p["division"], p["provision_id"])
        for row in rows for p in row["provisions"] if p["provision_id"]
    }
    lookup: dict[tuple[str, str], CodeEditionProvision] = {}
    if prov_keys:
        provisions = CodeEditionProvision.objects.filter(
            edition=regulation.edition,
            provision_id__in={pid for _, pid in prov_keys},
        ).prefetch_related("versions")
        lookup = {(p.division, p.provision_id): p for p in provisions}

    # Appendix-table owners: table_id → distinct owning provisions.
    table_ids = {t["table_id"] for row in rows for t in row["tables"]}
    owners_by_table: dict[str, dict[int, CodeEditionProvision]] = {}
    if table_ids:
        pvts = (
            ProvisionVersionTable.objects.filter(
                version__provision__edition=regulation.edition,
                table_id__in=table_ids,
            )
            .select_related("version__provision")
            .prefetch_related("version__provision__versions")
        )
        for pvt in pvts:
            prov = pvt.version.provision
            owners_by_table.setdefault(pvt.table_id, {})[prov.pk] = prov

    for row in rows:
        day = row["date"]
        for p in row["provisions"]:
            matched = lookup.get((p["division"], p["provision_id"]))
            if matched is not None:
                p["url"] = _dated_provision_url(matched, day, code_name)
        for t in row["tables"]:
            owners = owners_by_table.get(t["table_id"], {}).values()
            t["owners"] = [
                {
                    "provision_id": prov.provision_id,
                    "division": prov.division,
                    "url": _dated_provision_url(prov, day, code_name),
                }
                for prov in sorted(owners, key=lambda pr: _natural_key(pr.provision_id))
            ]


def _parse_iso_date(value: str | None) -> date | None:
    """Parse an ISO date string from CCM JSON, tolerating None/empty."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def locked_edition_response(
    request: HttpRequest, edition: CodeEdition, *, surface: str
) -> HttpResponse:
    """A 403 teaser page for content outside the user's free-tier scope.

    Gating happens *after* the object lookup so the page can name the
    edition; a free user following a cross-edition link sees what exists
    and how to unlock it, never a bare 403 or a silent 404.

    Records a ``locked_content_view`` on the way out.  This is the single
    choke point for the three gated page views, so every refusal is captured
    here rather than at each call site — a new gated view gets the signal by
    using this helper.  ``surface`` says which view refused; the caller must
    pass it since the helper can't tell.

    The page carries a **generic** social card.  It names the edition and says
    the edition is Pro content, and it names no provision, so a forwarded link
    cannot promise a text it will not deliver.  The first design emitted no
    card at all, which read worse than an upsell: a link with no card arrives
    in Slack as a bare URL, which looks broken, and looking broken is the
    failure the card exists to prevent.
    """
    edition_name = f"{edition.code.code} {edition.edition_id}".strip()
    record_event(
        request,
        event_type=EngagementEvent.EventType.LOCKED_CONTENT_VIEW,
        object_type="CodeEdition",
        object_id=edition.pk,
        search_id=request.GET.get("search_id"),
        context={
            "surface": surface,
            "code_edition": edition.code_name,
            "path": request.path,
        },
    )
    return render(
        request,
        "locked_edition.html",
        {
            "edition": edition,
            "edition_display_name": edition_name,
            "meta_title": f"{edition_name} — Pro content{TITLE_SUFFIX}",
            "social_title": f"{edition_name} is Pro content on CodeChronicle",
            "meta_description": (
                f"{edition_name} is part of the Pro plan. The free plan covers "
                "the Ontario Building Code 2006 in full, with its amendment "
                "history."
            ),
        },
        status=403,
    )


@corpus_conditional
def regulation_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show a single regulation with all its clauses."""
    regulation = get_object_or_404(
        Regulation.objects.select_related("edition__code", "amends"),
        pk=pk,
    )
    if not edition_allowed(request.user, regulation.edition.code_name):
        return locked_edition_response(
            request, regulation.edition, surface="regulation_detail"
        )
    # ``clause_id`` is a CharField, so a DB ``order_by`` is lexicographic
    # (1, 10, 11, 2, 3, …).  Re-sort in Python on the natural key so clauses
    # read in numeric order (1, 2, 3, …, 10, 11, …) — the order a reader
    # expects and the order the index nav mirrors.
    clauses = sorted(
        regulation.clauses.select_related("regulation__edition__code")
        .prefetch_related("contributed_to_versions__provision__edition__code"),
        key=lambda c: _natural_key(c.clause_id),
    )
    # Annotate each clause with the full list of provisions it affects
    # (resolved server-side so the template stays logic-free).  See
    # _clause_targets: all targets, natural-ordered, indented as a hierarchy.
    # Also flag staggered commencement — a clause whose own effective_date
    # is later than the regulation's blanket date — so the template can mark
    # it without a date comparison of its own.
    for clause in clauses:
        clause.targets = _clause_targets(clause)  # type: ignore[attr-defined]
        clause.is_staggered = bool(  # type: ignore[attr-defined]
            clause.effective_date
            and clause.effective_date != regulation.effective_date
        )

    commencement = _commencement_schedule(regulation)
    has_staggered_commencement = any(not row["is_default"] for row in commencement)
    # Engagement: a user landed on this regulation's detail page.  Non-fatal.
    record_event(
        request,
        event_type=EngagementEvent.EventType.REGULATION_VIEW,
        object_type="Regulation",
        object_id=regulation.pk,
        search_id=request.GET.get("search_id"),
        context={"reg_id": regulation.reg_id, "role": regulation.role},
    )
    return render(request, "regulation/detail.html", {
        "regulation": regulation,
        # This page reproduces one regulation's own clause text, so it
        # names itself rather than looking through to versions.
        "crown_years": crown_years_for_regulations([regulation]),
        "clauses": clauses,
        "commencement": commencement,
        "has_staggered_commencement": has_staggered_commencement,
        # The schema.org/Legislation block. A provision's block names this
        # regulation in legislationConsolidates and links here, so the object
        # it names describes itself when a crawler follows the link.
        "jsonld": regulation_jsonld(regulation, origin=site_origin(request)),
    })


def _print_response(
    request: HttpRequest,
    *,
    matched: CodeEditionProvision,
    target_version: CodeEditionProvisionVersion,
    sections: list[dict[str, Any]],
    code_name: str,
    division: str,
    provision_id: str,
    version: int,
    contents_ctx: dict[str, Any],
) -> HttpResponse:
    """Render the subtree as an exhibit.

    Everything the header states is sourced, never guessed: the window comes
    from :func:`core.citations.in_force_phrase` (which closes an open version
    at the edition's end and states the last day actually governed), and the
    instruments come from :mod:`core.seo`, which already refuses to fall back
    to the edition's base regulation when CCM shipped no contributing clause.

    The crops are attached to the version and table rows here rather than
    computed in a template filter, so the geometry stays in one testable place
    and the shared content partials only place what they are handed.
    """
    edition = matched.edition
    version_rows = [v for s in sections for v in s["active_versions"]]
    # Prefetch, then mutate the prefetched rows.  Without this,
    # ``version.tables.all()`` in the content partial issues a fresh query and
    # returns fresh instances — the crops attached to the objects here would
    # be attached to objects nobody renders, and every table would print as an
    # empty frame.
    prefetch_related_objects(version_rows, "tables")
    for version_row in version_rows:
        version_row.crops = build_crops(version_row.page_images)
        for table in version_row.tables.all():
            table.crops = build_crops(table.images)

    # A scanned page already shows its tables, so repeating them as their own
    # figures prints the same table twice.  Suppressed by default for an
    # image-rendered version, and still the reader's call — see
    # core.print_options.
    tables_mode = resolve_tables_mode(request.GET.get("tables"))
    tables_separate = apply_tables_mode(version_rows, tables_mode)

    return render(request, "regulation/provision_print.html", {
        "print_mode": True,
        "tables_separate": tables_separate,
        # Whether the page decided, or the reader did.  The control explains
        # itself only in the first case: a reader who asked for this state
        # does not need to be told why it holds.
        "tables_by_default": tables_mode is None,
        "tables_toggle_query": toggle_query(request.GET, tables_separate),
        "edition": edition,
        "code_display_name": f"{edition.code.code} {edition.edition_id}".strip(),
        "division": division,
        "provision_id": provision_id,
        "provision_title": target_version.title,
        "version_number": version,
        "window_phrase": in_force_phrase(target_version, edition),
        "base_reg": base_regulation(edition),
        "amending_regs": amending_regulations(target_version),
        "retrieved": date.today(),
        "site_origin": site_origin(request),
        "version_path": provision_permalink_url(
            code_name, division, provision_id, version
        ),
        "sections": sections,
        # The regulations that enacted the text on this sheet, not the
        # edition's base year -- an amendment is its own instrument.
        "crown_years": crown_years_for_provisions(
            {row.provision for row in version_rows}
        ),
        # An exhibit of an oversized provision is its own text plus what it
        # contains, for the same reason the page is: the printed alternative
        # is 1,339 provisions, and the guarantee this export makes is that
        # paper shows what the page shows.
        **contents_ctx,
        "active_node_id": provision_id,
        "active_provision_id": provision_id,
        "transition_active": False,
        **provision_page_meta(matched, target_version),
        # After the spread, deliberately: the reading page's title is right
        # for a tab and wrong for a saved file, and this page is a file.
        "meta_title": exhibit_title(
            f"{edition.code.code} {edition.edition_id} "
            f"{'Div ' + division + ' ' if division else ''}"
            f"{provision_id} v{version}",
            date.today(),
        ),
    })


def _defers_text(request: HttpRequest, for_print: bool) -> bool:
    """Whether this response hands over headings and fetches the bodies later.

    Two conditions, and both are about the record rather than about reading
    comfort:

    * **Signed in.** An anonymous response is stored at the edge and never
      reaches Django, so deferring for an anonymous reader would multiply the
      requests without recording one of them.  Anonymous rendering is also
      what crawlers see, and the cost work in ``CONTENTS_THRESHOLD`` was
      measured against it.
    * **Not the exhibit.** A printed page has no later.
    """
    return request.user.is_authenticated and not for_print


def _section_row(
    prov: CodeEditionProvision,
    prov_versions: list[CodeEditionProvisionVersion],
    *,
    code_name: str,
    is_active: bool,
    is_container: bool,
    defer_text: bool,
) -> dict[str, Any]:
    """One row of the ``sections`` list the viewer partials render.

    Shared by the permalink page, its print branch and ``provision_text``.
    The fragment must describe a provision exactly as the whole-subtree render
    would, or a lazily-loaded body differs from the printed one — which is the
    same guarantee ``for_print`` makes, now with a second code path to hold it
    against.
    """
    return {
        "provision_id": prov.provision_id,
        "node_id": prov.provision_id,
        # No fallback to the provision id.  The id is printed beside the
        # title, so falling back rendered "Part 2 — Part 2".  An untitled
        # provision has no title; the template omits the dash.
        "title": prov_versions[-1].title if prov_versions else "",
        # Whether anything sits under this provision.  A container has no
        # text of its own — every part, section and division in this
        # corpus has an empty body — so it must not be reported as text we
        # failed to supply.
        "is_container": is_container,
        # Its own permalink.  Nothing above article level carries text, so
        # a container page *is* its links — and the rail's "Subprovisions"
        # names only the direct children, which left every deeper
        # provision on the page unreachable without going back up.  The
        # matched provision links nowhere: it is already here.
        "url": (
            ""
            if is_active or not prov_versions
            else provision_permalink_url(
                code_name, prov.division, prov.provision_id,
                prov_versions[-1].version,
            )
        ),
        "division": prov.division,
        "active_versions": prov_versions,
        "is_active": is_active,
        # Only a row that has a version can be deferred; a row with nothing in
        # force renders its one line here and costs no request.
        "defer_text": defer_text and bool(prov_versions),
        # Where the body comes from when it is deferred.  Empty when there is
        # no version to name, which is exactly when nothing is deferred.
        "text_url": (
            provision_text_url(
                code_name, prov.division, prov.provision_id,
                prov_versions[-1].version,
            )
            if prov_versions else ""
        ),
    }


def provision_text(
    request: HttpRequest,
    code_edition: str,
    division: str,
    provision_id: str,
    version: int,
) -> HttpResponse:
    """One provision version's body.  HTMX fragment.

    The website's ``/api/provision``.  It exists so that text leaves this
    product one provision at a time and every departure is countable; see item
    3 of ``tasks/b-reading-ledger-for-the-website.md``.

    Signed-in readers only.  Nothing anonymous links here — an anonymous
    permalink renders its whole subtree inline — so answering an anonymous
    request would open a second, unrecorded way to sweep the corpus for no
    feature at all.  It answers **403** rather than redirecting to the login
    page, because htmx swaps nothing on a non-2xx: an expired session leaves
    the heading in place instead of pasting a sign-in form into the body slot.

    Cross-references resolve at this version's own effective date, which is
    also what ``provision_permalink`` does for the version its URL names.  On
    a permalink the *descendants* instead inherit the matched version's date,
    so the two differ wherever a descendant came into force earlier — 28 of
    9,822 descendant rows, measured 21 August 2026.  It changes which version
    a citation links to, never the text.
    """
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Sign in to read this provision.")

    code, _, edition_id = code_edition.partition("_")
    target = get_object_or_404(
        CodeEditionProvisionVersion.objects
        .select_related("provision__edition__code")
        .prefetch_related("tables"),
        provision__edition__code__code=code,
        provision__edition__edition_id=edition_id,
        provision__division=division,
        provision__provision_id=provision_id,
        version=version,
    )
    prov = target.provision
    # The gate, before any text is read.  A key changes how an account asks,
    # never what it may read — and the same holds for a fragment URL.
    if not edition_allowed(request.user, prov.edition.code_name):
        return HttpResponseForbidden("This edition is not in your plan.")

    code_name = prov.edition.code_name
    # Within-edition citations, linked inline.  Without this the deferred body
    # renders its cross-references as plain text while the inline one links
    # them, so the same provision reads differently depending on how it
    # arrived.
    annotate_versions(
        [target], code_name, on_date=target.effective_date, fan_out=True,
    )

    section = _section_row(
        prov,
        [target],
        code_name=code_name,
        is_active=False,
        is_container=CodeEditionProvision.objects.filter(
            parent_id=prov.pk, edition=prov.edition, division=division
        ).exists(),
        defer_text=False,
    )

    # The ledger, after the gate and before the response is built.  This is the
    # row the page render no longer writes.
    record_versions(request, [target])

    return render(
        request, "partials/_viewer_section_body.html", {"section": section}
    )


@corpus_conditional
def provision_permalink(
    request: HttpRequest,
    code_edition: str,
    division: str,
    provision_id: str,
    version: int,
    for_print: bool = False,
) -> HttpResponse:
    """A standalone view of one provision *at a specific version*.

    Targeted by regulation-clause links: ``version`` is the version that
    clause produced (v0 for a base regulation, v1+ for amendments).  There's
    no query date in this context, so the in-force / coverage chrome is
    omitted; the matched provision is pinned to the linked version and its
    descendants are shown as they read on that version's effective date.

    ``for_print`` (set by the ``/print/`` route) renders the same provision as
    an exhibit: same subtree, same partials, no navigation, page images cropped
    to the provision.  One view rather than two, because the guarantee this
    export makes is that a printed provision cannot show something the page
    does not — and two assemblies of the same subtree is exactly how that
    guarantee would quietly stop being true.
    """
    code, _, edition_id = code_edition.partition("_")
    matched = get_object_or_404(
        CodeEditionProvision.objects.select_related("edition__code", "parent"),
        edition__code__code=code,
        edition__edition_id=edition_id,
        division=division,
        provision_id=provision_id,
    )
    if not edition_allowed(request.user, matched.edition.code_name):
        return locked_edition_response(request, matched.edition, surface="permalink")
    target_version = get_object_or_404(
        CodeEditionProvisionVersion, provision=matched, version=version,
    )
    anchor_date = target_version.effective_date
    code_name = matched.edition.code_name

    if for_print and not request.user.is_authenticated:
        # The citation string is open to everybody — it carries our URL into
        # somebody else's document, which is the point of it.  The exhibit is
        # work product, and it is the natural moment to ask for an account.
        return redirect_to_login(request.get_full_path())

    # Hierarchical navigation: up to the parent, down to the direct children.
    # Each neighbour links to every version whose in-force window overlaps the
    # pinned version's, so a long-lived parent can point at several child
    # versions (and vice-versa).
    # The exhibit has no navigation — there is nowhere to click on paper — so
    # the nav queries are skipped rather than computed and dropped.
    nav_up: list[dict[str, Any]] = []
    if matched.parent_id and not for_print:
        parent = (
            CodeEditionProvision.objects
            .prefetch_related("versions")
            .get(pk=matched.parent_id)
        )
        nav_up.append(related_links(parent, target_version, code_name))
    nav_down: list[dict[str, Any]] = []
    if not for_print:
        child_provisions = (
            CodeEditionProvision.objects
            .filter(parent_id=matched.pk, edition=matched.edition, division=division)
            .prefetch_related("versions")
        )
        nav_down = [
            related_links(child, target_version, code_name)
            for child in sorted(
                child_provisions, key=lambda p: _natural_key(p.provision_id)
            )
        ]

    # Sibling pager: previous / next provision under the same parent, in
    # natural order, each shown as it reads on the pinned date.
    #
    # A root has no parent, and its siblings are the edition's other roots —
    # Division A beside B beside C, or Part 1 beside Part 2 in an edition with
    # no divisions.  Note the division filter is dropped there, deliberately:
    # everywhere else in the tree ``division`` scopes the query, but at the
    # root crossing divisions is the whole point of the row.
    nav_prev: dict[str, Any] | None = None
    nav_next: dict[str, Any] | None = None
    if not for_print:
        if matched.parent_id:
            siblings = sorted(
                CodeEditionProvision.objects
                .filter(
                    parent_id=matched.parent_id,
                    edition=matched.edition,
                    division=division,
                )
                .prefetch_related("versions"),
                key=lambda p: _natural_key(p.provision_id),
            )
        else:
            siblings = _edition_roots(matched.edition)
        pks = [p.pk for p in siblings]
        if matched.pk in pks:
            idx = pks.index(matched.pk)
            if idx > 0:
                nav_prev = _sibling_link(siblings[idx - 1], anchor_date, code_name)
            if idx < len(siblings) - 1:
                nav_next = _sibling_link(siblings[idx + 1], anchor_date, code_name)

    # Subtree: matched provision + all descendants (same edition/division),
    # unless that is more than a reader would ever scroll — see
    # ``core.subtrees.CONTENTS_THRESHOLD``.  The search overlay walks the same
    # way from a different root, which is why the walk is not written here.
    all_provisions, oversized = walk_subtree(
        matched, edition=matched.edition, division=division
    )

    # Too big to read: the page shows this provision's own text and a table of
    # contents for what is under it.  Nothing becomes unreachable — every
    # child is still linked, one hop further on.  The search overlay shows the
    # same block from the same builder, so a reader who meets the contents of
    # Part 9 there and again here meets one list.
    contents_ctx: dict[str, Any] = {
        "contents": [], "contents_total": 0, "contents_noun": "",
    }
    if oversized:
        all_provisions = [matched]
        contents_ctx = contents_view(matched, target_version, code_name, division)
        # The "Subprovisions" nav lists the same children as links.  Two lists
        # of one thing on one page is worse than either alone, and the
        # contents rows say more.
        nav_down = []

    # Descendants: the version in force on the linked version's effective
    # date.  The matched provision itself is pinned to exactly the linked
    # version (so a zero-duration base v0 still shows, which the date-based
    # in-force filter would otherwise drop).
    active = in_force_versions(all_provisions, anchor_date)
    by_provision: dict[int, list[CodeEditionProvisionVersion]] = {}
    for v in active:
        by_provision.setdefault(v.provision_id, []).append(v)

    by_provision[matched.pk] = [target_version]

    # Within-edition citations, linked inline.  This page pins a version rather
    # than a date, so a citation whose referent was amended mid-window fans out
    # into one link per target version — the presentation the hierarchy nav
    # already uses for a multi-version neighbour (_permalink_nav_item.html).
    annotate_versions(
        [v for versions in by_provision.values() for v in versions],
        code_name,
        on_date=anchor_date,
        fan_out=True,
    )

    # There is no in-place comparison here any more.  ``?compare=<version>``
    # rendered a second side-by-side diff on this page: the same feature as
    # ``/compare/`` but unable to cross an edition, without the redline floor,
    # and behind a URL that named a permalink with a modifier rather than
    # naming a comparison.  The rail's per-row ``compare`` links now go to
    # ``/compare/``.
    # Which of these provisions contain another one, so an empty body can be
    # told apart from a missing one.
    parent_pks = {p.parent_id for p in all_provisions if p.parent_id}

    # Deferred bodies.  A signed-in reader gets the matched provision's text
    # and the *headings* of everything under it; each body arrives through
    # ``provision_text`` as it is scrolled to.  See ``_defers_text``.
    defer_text = _defers_text(request, for_print)

    sections: list[dict[str, Any]] = []
    for prov in sorted(all_provisions, key=lambda p: _natural_key(p.provision_id)):
        sections.append(_section_row(
            prov,
            by_provision.get(prov.pk, []),
            code_name=code_name,
            is_active=prov.pk == matched.pk,
            is_container=(
                prov.pk in parent_pks
                or (bool(contents_ctx["contents"]) and prov.pk == matched.pk)
            ),
            # The provision the URL names is never deferred.  It is what the
            # reader asked for, and a page that answers a request for one
            # provision with a spinner is not a page.
            defer_text=defer_text and prov.pk != matched.pk,
        ))

    # The reading ledger.  Written from the versions this page actually
    # rendered, not from ``matched`` — the request names one provision and the
    # response can carry forty, and recording the name would report an account
    # served the whole corpus as holding about 2% of it.
    #
    # A deferred section delivered no text, so it records none; ``provision_text``
    # records its own when it answers.  That split is the point of item 3 of
    # ``tasks/b-reading-ledger-for-the-website.md``: the ledger can only be as
    # granular as delivery is.
    #
    # The print branch never defers — it renders the whole subtree in one pass
    # with no ``CONTENTS_THRESHOLD``, and is the cheapest way to take text out
    # of the product.  A ledger with a hole where bulk delivery is easiest is
    # worse than none: it reads as a clean account.
    delivered, recorded = record_versions(
        request,
        [v for section in sections if not section["defer_text"]
         for v in section["active_versions"]],
    )

    # Engagement.  A print request is an *export*, not a view: recording both
    # would double-count the same reader in the view totals and make the export
    # counts unreadable against them.
    #
    # Written *after* the ledger, not before, because of ``delivered`` and
    # ``recorded`` below — and the page has to be assembled before either
    # number exists.  Nothing between the gate above and here returns, so the
    # move costs no event; a request that raises on the way now records
    # nothing, which is right, since a 500 delivered no reading.
    ledger_counts = {
        # What this response handed over, and what reached the ledger.  A page
        # that delivers forty texts and records three is not a silent day, so
        # ``ledger_health``'s day-level test passes it.  These two numbers make
        # a partial failure visible per request; ``record_versions`` explains
        # why they come from two different functions.
        "delivered": delivered,
        "recorded": recorded,
    }
    if for_print:
        record_event(
            request,
            event_type=EngagementEvent.EventType.EXPORT,
            object_type="CodeEditionProvisionVersion",
            object_id=target_version.pk,
            search_id=request.GET.get("search_id"),
            context={
                "kind": "provision_pdf",
                "division": division,
                "provision_id": provision_id,
                "code_edition": code_name,
                # The exhibit is the cheapest bulk delivery in the product: it
                # never defers and ignores CONTENTS_THRESHOLD.  It is the last
                # surface that should be missing from the watch.
                **ledger_counts,
            },
        )
    else:
        record_event(
            request,
            event_type=EngagementEvent.EventType.PROVISION_VERSION_VIEW,
            object_type="CodeEditionProvisionVersion",
            object_id=target_version.pk,
            search_id=request.GET.get("search_id"),
            context={
                "code": matched.edition.code.code,
                "edition_id": matched.edition.edition_id,
                "division": division,
                "provision_id": provision_id,
                "version": version,
                "surface": "permalink",
                # Followed to, or arrived at cold.  A reader follows links; a
                # script composes URLs.  See ``core.events.arrival_context``.
                **arrival_context(request),
                **ledger_counts,
            },
        )

    if for_print:
        return _print_response(
            request,
            matched=matched,
            target_version=target_version,
            sections=sections,
            code_name=code_name,
            division=division,
            provision_id=provision_id,
            version=version,
            contents_ctx=contents_ctx,
        )

    return render(request, "regulation/provision_permalink.html", {
        "edition": matched.edition,
        "code_display_name": (
            f"{matched.edition.code.code} {matched.edition.edition_id}".strip()
        ),
        "division": division,
        "provision_id": provision_id,
        "version_number": version,
        "effective_date": anchor_date,
        "never_in_force": target_version.never_in_force,
        "nav_up": nav_up,
        "nav_down": nav_down,
        **contents_ctx,
        "nav_prev": nav_prev,
        "nav_next": nav_next,
        # The top of the ladder, reachable from any depth. "Within" climbs one
        # parent at a time and stops at a root, which left a reader inside
        # Division B with no way out of it; this row is the way out, and from
        # there the editions sit side by side.
        "nav_edition": {
            "label": f"{matched.edition.code.code} {matched.edition.edition_id}".strip(),
            "url": edition_contents_url(code_name),
        },
        "provenance": provenance_result(
            matched, target_version, code_name, division, provision_id, request.user
        ),
        "sections": sections,
        # Every regulation that enacted text shown here, base and amending
        # alike.  A consolidated provision is not the work of one instrument.
        "crown_years": crown_years_for_provisions(
            {v.provision for section in sections for v in section["active_versions"]}
        ),
        "active_node_id": provision_id,
        "active_provision_id": provision_id,
        "transition_active": False,
        # Fan-in: the provisions that pointed *here* while this version stood.
        # Not in the printed code — only a whole-edition index can answer it.
        "cited_by": cited_by(target_version, matched, code_name),
        # The exhibit, linked from the foot of the page as well as from the
        # Cite menu.  Inside the menu it was two clicks and a lazy load deep,
        # which is a strange place to keep one of the four measured exports —
        # /compare/ has offered the same link in the open all along.
        "print_url": provision_print_url(code_name, division, provision_id, version),
        "print_needs_sign_in": not request.user.is_authenticated,
        # Search-engine metadata: a per-page title, description and canonical
        # URL. Built in core.seo rather than in the template because the
        # canonical rule is shared with the sitemap and must not be restated.
        **provision_page_meta(matched, target_version),
        # The schema.org/Legislation block. Built here rather than merged into
        # provision_page_meta because it needs the request's origin to make its
        # URLs absolute, and that helper deliberately knows nothing of the
        # request. base.html prints it only where it is set, so the locked
        # teaser above carries no block without a tier test of its own.
        "jsonld": provision_jsonld(
            matched, target_version, origin=site_origin(request)
        ),
    })


@corpus_conditional
def edition_contents(request: HttpRequest, code_edition: str) -> HttpResponse:
    """One edition's structure: its roots, and the editions either side of it.

    The top of the navigation ladder.  A provision page climbs to its parent,
    and a parent to its parent, but a root had nowhere left to go — so a
    reader inside Division B could not reach Division C, and no page in the
    product listed an edition's own contents.

    Two moves from here.  **Down**, into the roots — divisions in OBC 2006 and
    2012, parts in OBC 1997, whichever that edition holds.  **Sideways**, into
    the neighbouring editions, which is an edition-level move and needs no
    provision mapping: the rail already answers "where did *this provision*
    go", from mapping rows and never from a matching number, and that question
    is not this one.

    ``code_edition`` is the ``OBC_2006`` form the provision permalinks use.
    """
    if "_" not in code_edition:
        raise Http404("Unknown edition")
    system_code, edition_id = code_edition.split("_", 1)
    edition = get_object_or_404(
        CodeEdition.objects.select_related("code"),
        code__code=system_code,
        edition_id=edition_id,
    )
    # The gate, before anything is read. An edition's contents is the shape of
    # the edition, which is content.
    if not edition_allowed(request.user, edition.code_name):
        return locked_edition_response(request, edition, surface="edition_contents")

    roots = _edition_roots(edition)
    # Each root as it last read. A contents page is not pinned to a date — the
    # reader has not chosen one yet — so it links the highest version, which is
    # the same rule core.seo uses to pick a canonical URL.
    entries = []
    for root in roots:
        versions = sorted(root.versions.all(), key=lambda v: v.version)
        newest = versions[-1]
        entries.append({
            "provision_id": root.provision_id,
            "division": root.division,
            "level": root.get_level_display(),
            "title": newest.title,
            "url": provision_permalink_url(
                code_edition, root.division, root.provision_id, newest.version
            ),
        })

    siblings = _sibling_editions(edition)
    return render(request, "regulation/edition_contents.html", {
        "edition": edition,
        "code_display_name": f"{edition.code.code} {edition.edition_id}".strip(),
        # The last day this edition governed, not the stored end — that is the
        # first day it did not.  core.seo owns the conversion for the product.
        "last_day": last_governed_day(edition.ineffective_date),
        "entries": entries,
        "crown_years": crown_years_for_provisions(roots),
        "editions": [
            {
                "label": f"{e.code.code} {e.edition_id}".strip(),
                "effective_date": e.effective_date,
                "last_day": last_governed_day(e.ineffective_date),
                "url": edition_contents_url(f"{e.code.code}_{e.edition_id}"),
                "is_current": e.pk == edition.pk,
            }
            for e in siblings
        ],
        "meta_title": f"{edition.code.code} {edition.edition_id} — contents{TITLE_SUFFIX}",
    })


@corpus_conditional
def edition_chain(request: HttpRequest, pk: int) -> HttpResponse:
    """Show the amendment chain timeline for a code edition."""
    edition = get_object_or_404(
        CodeEdition.objects.select_related("code"),
        pk=pk,
    )
    if not edition_allowed(request.user, edition.code_name):
        return locked_edition_response(request, edition, surface="edition_chain")
    regulations = (
        edition.regulations
        .select_related("amends")
        .prefetch_related("clauses")
        .order_by("effective_date")
    )
    return render(request, "regulation/chain.html", {
        "edition": edition,
        "regulations": regulations,
        "crown_years": crown_years_for_regulations(regulations),
    })
