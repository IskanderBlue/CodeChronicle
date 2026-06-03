"""
Regulation browsing views.
"""

import re
from datetime import date
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from core.events import record_event
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
    ProvisionVersionTable,
    Regulation,
    RegulationClause,
)

from .search import _active_versions

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


def _provision_permalink_url(
    code_name: str, division: str, provision_id: str, version: int
) -> str:
    """Reverse a provision permalink, routing around empty divisions.

    A ``<str:division>`` path segment can't be empty, so division-less
    editions (e.g. OBC 1997, ``division=""``) must use the sibling
    ``provision_permalink_no_division`` route or ``reverse`` raises
    ``NoReverseMatch``.
    """
    if division:
        return reverse(
            "core:provision_permalink",
            args=[code_name, division, provision_id, version],
        )
    return reverse(
        "core:provision_permalink_no_division",
        args=[code_name, provision_id, version],
    )


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
            "indent": 0,
        }]
    chosen = next(
        (v for v in versions if _version_contains(v, clause.regulation.effective_date)),
        versions[0],
    )
    return [{
        "label": f"{prov.get_level_display()} {prov.provision_id}".strip(),
        "url": _provision_permalink_url(
            prov.edition.code_name, prov.division, prov.provision_id, chosen.version
        ),
        "level": prov.level,
        "version": chosen.version,
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
            "url": _provision_permalink_url(
                prov.edition.code_name, prov.division, prov.provision_id, v.version
            ),
            "level": prov.level,
            "version": v.version,
            "indent": depth * 12,
        })
    return targets


def _natural_key(provision_id: str) -> tuple[tuple[int, int, str], ...]:
    """Sort key that orders 'A.1.10.' after 'A.1.9.' (numeric segments).

    Each segment is wrapped as ``(kind, number, text)`` so numeric and word
    segments never compare directly — a subtree can mix shapes like
    'Part 3' and '3.17.', and a bare ``(int | str)`` tuple would raise
    ``TypeError`` on the cross-type compare.
    """
    parts = re.split(r"(\d+)", provision_id or "")
    return tuple(
        (0, int(p), "") if p.isdigit() else (1, 0, p.lower())
        for p in parts if p
    )


# ── Hierarchical permalink navigation ────────────────────────────────────
# The permalink shows one provision pinned to one version.  A reader needs
# to walk up to the parent and down to the children — but each related
# provision has its own version timeline, so a single linked version can
# overlap *several* versions of a neighbour.  Links are emitted per
# overlapping version, not per provision.


def _version_contains(v: CodeEditionProvisionVersion, day: "date") -> bool:
    """Is ``day`` within v's half-open window [effective, ineffective)?"""
    return v.effective_date <= day and (
        v.ineffective_date is None or day < v.ineffective_date
    )


def _overlaps(
    a: CodeEditionProvisionVersion, b: CodeEditionProvisionVersion
) -> bool:
    """Do two versions' in-force windows overlap? (half-open, None = open end).

    A *zero-duration* version (effective == ineffective) is a half-open
    interval of length zero — it overlaps nothing under the plain test, so
    such a version would silently drop out of the nav.  These do occur:
    a base-edition v0 that was superseded on the edition's own start date
    (e.g. OBC 2012 B 1.3.1.2. v0, 2014-01-01→2014-01-01).  Treat it as the
    instant {effective} and ask whether the other window contains it, so the
    base version still links alongside its later siblings.
    """
    a_point = a.ineffective_date is not None and a.ineffective_date == a.effective_date
    b_point = b.ineffective_date is not None and b.ineffective_date == b.effective_date
    if a_point and b_point:
        return a.effective_date == b.effective_date
    if a_point:
        return _version_contains(b, a.effective_date)
    if b_point:
        return _version_contains(a, b.effective_date)
    a_before_b = a.ineffective_date is not None and a.ineffective_date <= b.effective_date
    b_before_a = b.ineffective_date is not None and b.ineffective_date <= a.effective_date
    return not a_before_b and not b_before_a


def _related_links(
    provision: CodeEditionProvision,
    ref: CodeEditionProvisionVersion,
    code_name: str,
) -> dict[str, Any]:
    """A neighbour provision plus a link to each version overlapping ``ref``.

    Uses the provision's prefetched ``versions`` cache; the versions whose
    in-force window touches the pinned version's are the ones a reader on
    this page could have been looking at, so each gets its own link.
    """
    versions = sorted(
        (v for v in provision.versions.all() if _overlaps(v, ref)),
        key=lambda v: v.version,
    )
    return {
        "provision_id": provision.provision_id,
        "versions": [
            {
                "version": v.version,
                "effective_date": v.effective_date,
                "ineffective_date": v.ineffective_date,
                "url": _provision_permalink_url(
                    code_name, provision.division, provision.provision_id, v.version
                ),
            }
            for v in versions
        ],
    }


def _sibling_link(
    provision: CodeEditionProvision, day: date, code_name: str
) -> dict[str, Any] | None:
    """Link to a sibling provision as it reads on ``day`` (the pinned date).

    A pager (prev/next) points at one version, not many, so pick the
    sibling version in force on the pinned version's effective date; fall
    back to the earliest version when nothing is in force then (e.g. the
    sibling didn't exist yet).  Returns ``None`` for a sibling with no
    versions at all.
    """
    versions = sorted(provision.versions.all(), key=lambda v: v.version)
    if not versions:
        return None
    chosen = next((v for v in versions if _version_contains(v, day)), versions[0])
    return {
        "provision_id": provision.provision_id,
        "version": chosen.version,
        "url": _provision_permalink_url(
            code_name, provision.division, provision.provision_id, chosen.version
        ),
    }


def _provenance_result(
    matched: CodeEditionProvision,
    target_version: CodeEditionProvisionVersion,
    code_name: str,
    division: str,
    provision_id: str,
) -> dict[str, Any]:
    """The ``result`` shape the search provenance banner expects.

    Mirrors the subset of ``api.formatters._format_single_result`` the
    ``_provenance_banner.html`` partial reads — version, amending clause,
    base regulation, full chain and next version — so the permalink can
    reuse the same banner.  ``band`` is None (no query date here), which the
    partial already treats as "no query-date rail / coverage cell".
    """
    from api.formatters import _build_copy_text

    chain = list(matched.versions.order_by("version"))
    base_regulation = Regulation.objects.filter(
        edition=matched.edition, role="base"
    ).first()
    clause = target_version.last_contributing_clause
    next_version = next(
        (v for v in chain if v.version > target_version.version), None
    )
    copy_text = _build_copy_text(
        code_edition=code_name,
        division=division,
        provision_id=provision_id,
        title=target_version.title or provision_id,
        version=target_version,
        most_recent_clause=clause,
        base_regulation=base_regulation,
        next_version=next_version,
    )
    next_clause = next_version.last_contributing_clause if next_version else None
    return {
        "version": target_version,
        "clause": clause,
        "is_base": clause is None,
        "base_regulation": base_regulation,
        "next_version": next_version,
        # Proof of the version's END: the next version's commencement (this
        # version stops the day the next one comes into force).  Mirrors the
        # band's From popup, which proves the START.
        "next_commencement": next_clause.commencement if next_clause else None,
        "amendment_chain": chain,
        "copy_text": copy_text,
        "band": None,
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


def _leading_part(provision_id: str) -> str:
    """The Part number a provision belongs to — its first numeric segment
    (``3.1.4.2.`` → ``3``, ``11.2.1.1.`` → ``11``).  Empty when the id
    doesn't start with a number."""
    match = re.match(r"\d+", provision_id)
    return match.group(0) if match else ""


# Appendix tables (``Table-A-<n>``) carry no Part in their id, but in the OBC
# they're all Part 9 housing tables — so they're grouped under their
# division's Part 9 alongside the Part 9 provisions.
_APPENDIX_TABLE_PART = "9"


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
    buckets: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}

    def _bucket(division: str, part: str) -> dict[str, list[dict[str, Any]]]:
        return buckets.setdefault(
            (division, part), {"provisions": [], "tables": []}
        )

    for p in provisions:
        _bucket(p["division"], _leading_part(p["provision_id"]))["provisions"].append(p)
    for t in tables or []:
        _bucket(t["division"], _APPENDIX_TABLE_PART)["tables"].append(t)

    def _group_key(key: tuple[str, str]) -> tuple[str, int, str]:
        division, part = key
        # Numeric Parts in order; any non-numeric Part sorts last.
        return (division, int(part) if part.isdigit() else 1_000_000, part)

    groups: list[dict[str, Any]] = []
    for division, part in sorted(buckets, key=_group_key):
        if division and part:
            group_label = f"Div {division} · Part {part}"
        elif part:
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
) -> str | None:
    """Permalink for ``provision`` as it reads on ``day`` — the version in
    force then, falling back to the earliest.  ``None`` when it has no
    versions (renders as plain text rather than a dead link)."""
    versions = sorted(provision.versions.all(), key=lambda v: v.version)
    if not versions:
        return None
    chosen = next(
        (v for v in versions if day and _version_contains(v, day)), versions[0]
    )
    return _provision_permalink_url(
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


def regulation_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show a single regulation with all its clauses."""
    regulation = get_object_or_404(
        Regulation.objects.select_related("edition__code", "amends"),
        pk=pk,
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
        "clauses": clauses,
        "commencement": commencement,
        "has_staggered_commencement": has_staggered_commencement,
    })


def provision_permalink(
    request: HttpRequest,
    code_edition: str,
    division: str,
    provision_id: str,
    version: int,
) -> HttpResponse:
    """A standalone view of one provision *at a specific version*.

    Targeted by regulation-clause links: ``version`` is the version that
    clause produced (v0 for a base regulation, v1+ for amendments).  There's
    no query date in this context, so the in-force / coverage chrome is
    omitted; the matched provision is pinned to the linked version and its
    descendants are shown as they read on that version's effective date.
    """
    code, _, edition_id = code_edition.partition("_")
    matched = get_object_or_404(
        CodeEditionProvision.objects.select_related("edition__code", "parent"),
        edition__code__code=code,
        edition__edition_id=edition_id,
        division=division,
        provision_id=provision_id,
    )
    target_version = get_object_or_404(
        CodeEditionProvisionVersion, provision=matched, version=version,
    )
    anchor_date = target_version.effective_date
    code_name = matched.edition.code_name

    # Engagement: a user opened a specific provision version, typically via a
    # regulation-clause link.  Pinned to the exact linked version.  Non-fatal.
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
        },
    )

    # Hierarchical navigation: up to the parent, down to the direct children.
    # Each neighbour links to every version whose in-force window overlaps the
    # pinned version's, so a long-lived parent can point at several child
    # versions (and vice-versa).
    nav_up: list[dict[str, Any]] = []
    if matched.parent_id:
        parent = (
            CodeEditionProvision.objects
            .prefetch_related("versions")
            .get(pk=matched.parent_id)
        )
        nav_up.append(_related_links(parent, target_version, code_name))
    child_provisions = (
        CodeEditionProvision.objects
        .filter(parent_id=matched.pk, edition=matched.edition, division=division)
        .prefetch_related("versions")
    )
    nav_down = [
        _related_links(child, target_version, code_name)
        for child in sorted(child_provisions, key=lambda p: _natural_key(p.provision_id))
    ]

    # Sibling pager: previous / next provision under the same parent, in
    # natural order, each shown as it reads on the pinned date.
    nav_prev: dict[str, Any] | None = None
    nav_next: dict[str, Any] | None = None
    if matched.parent_id:
        siblings = sorted(
            CodeEditionProvision.objects
            .filter(parent_id=matched.parent_id, edition=matched.edition, division=division)
            .prefetch_related("versions"),
            key=lambda p: _natural_key(p.provision_id),
        )
        pks = [p.pk for p in siblings]
        if matched.pk in pks:
            idx = pks.index(matched.pk)
            if idx > 0:
                nav_prev = _sibling_link(siblings[idx - 1], anchor_date, code_name)
            if idx < len(siblings) - 1:
                nav_next = _sibling_link(siblings[idx + 1], anchor_date, code_name)

    # Subtree: matched provision + all descendants (same edition/division).
    all_provisions: list[CodeEditionProvision] = [matched]
    frontier = [matched.pk]
    while frontier:
        children = list(
            CodeEditionProvision.objects
            .filter(parent_id__in=frontier, edition=matched.edition, division=division)
        )
        if not children:
            break
        all_provisions.extend(children)
        frontier = [c.pk for c in children]

    # Descendants: the version in force on the linked version's effective
    # date.  The matched provision itself is pinned to exactly the linked
    # version (so a zero-duration base v0 still shows, which the date-based
    # in-force filter would otherwise drop).
    active = _active_versions(all_provisions, anchor_date)
    by_provision: dict[int, list[CodeEditionProvisionVersion]] = {}
    for v in active:
        by_provision.setdefault(v.provision_id, []).append(v)
    by_provision[matched.pk] = [target_version]

    sections: list[dict[str, Any]] = []
    for prov in sorted(all_provisions, key=lambda p: _natural_key(p.provision_id)):
        prov_versions = by_provision.get(prov.pk, [])
        sections.append({
            "provision_id": prov.provision_id,
            "node_id": prov.provision_id,
            "title": (prov_versions[-1].title if prov_versions else "") or prov.provision_id,
            "division": prov.division,
            "active_versions": prov_versions,
            "is_active": prov.pk == matched.pk,
        })

    return render(request, "regulation/provision_permalink.html", {
        "edition": matched.edition,
        "code_display_name": (
            f"{matched.edition.code.code} {matched.edition.edition_id}".strip()
        ),
        "division": division,
        "provision_id": provision_id,
        "version_number": version,
        "effective_date": anchor_date,
        "nav_up": nav_up,
        "nav_down": nav_down,
        "nav_prev": nav_prev,
        "nav_next": nav_next,
        "provenance": _provenance_result(
            matched, target_version, code_name, division, provision_id
        ),
        "sections": sections,
        "active_node_id": provision_id,
        "active_provision_id": provision_id,
        "transition_active": False,
    })


def edition_chain(request: HttpRequest, pk: int) -> HttpResponse:
    """Show the amendment chain timeline for a code edition."""
    edition = get_object_or_404(
        CodeEdition.objects.select_related("code"),
        pk=pk,
    )
    regulations = (
        edition.regulations
        .select_related("amends")
        .prefetch_related("clauses")
        .order_by("effective_date")
    )
    return render(request, "regulation/chain.html", {
        "edition": edition,
        "regulations": regulations,
    })
