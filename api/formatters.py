"""
Format search results for frontend display.
"""

import difflib
import logging
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from api.band import compute_band_geometry, parse_iso_date
from api.search.engine import _ref_parts
from config.code_metadata import get_code_display_name
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EditionTransition,
    Regulation,
)
from core.provision_lineage import annotate_lineage_locks, resolve_lineage

logger = logging.getLogger(__name__)

# Structural container levels: these are heading nodes (Division A / Part 3 /
# Section 3.2 / Subsection 1.3.7.) whose substantive text lives in their child
# articles — they legitimately carry no body, so the empty-content notice must
# not read as a data gap for them.  See _result_document_block.html.
_CONTAINER_LEVELS = frozenset({
    CodeEditionProvision.Level.DIVISION,
    CodeEditionProvision.Level.PART,
    CodeEditionProvision.Level.SECTION,
    CodeEditionProvision.Level.SUBSECTION,
})

_HTML_TAG_RE = re.compile(r"(<[^>]+>)")
# Splits text into words and whitespace runs, preserving both.
_WORD_SPACE_RE = re.compile(r"(\S+)")

_APPENDIX_REF_RE = re.compile(
    r'\(See Note (A-[\d.]+(?:\.\)?\(\d+(?:-\d+|(?:,\d+)*)\))?)\)',
    re.IGNORECASE,
)


def _linkify_appendix_refs(html: str) -> str:
    """Replace (See Note A-X.X.X.X.(N)) with clickable anchors."""
    def _replace(match: re.Match[str]) -> str:
        ref_id = match.group(1)
        return (
            f'(<a href="#" @click.prevent="'
            f"$dispatch('expand-appendix'); "
            f'document.getElementById(\'appendix-{ref_id}\')?.scrollIntoView({{behavior: \'smooth\'}})"'
            f' class="text-secondary hover:text-secondary-2 hover:underline">'
            f'See Note {ref_id}</a>)'
        )
    return _APPENDIX_REF_RE.sub(_replace, html)


def highlight_terms(html: str, terms: Iterable[str]) -> str:
    """Wrap occurrences of query ``terms`` in provision HTML with ``<mark>``.

    Phrase-aware and case-insensitive. Only the text *between* tags is
    processed (via the same tag split used for diffing), so tags and their
    attributes are never corrupted. Longer terms match first, so
    "fire-resistance rating" wins over a bare "rating". ``\\w`` lookarounds
    give word boundaries that respect hyphens inside a term.

    The emitted ``mark.match-highlight`` class is styled by a role-variable
    CSS rule in base.html (paper-yellow in light, amber in dark).
    """
    cleaned = sorted(
        {t.strip() for t in terms if t and t.strip()},
        key=len,
        reverse=True,
    )
    if not html or not cleaned:
        return html
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(t) for t in cleaned) + r")(?!\w)",
        re.IGNORECASE,
    )
    parts = _HTML_TAG_RE.split(html)
    out: list[str] = []
    for part in parts:
        if _HTML_TAG_RE.fullmatch(part):
            out.append(part)  # tag — leave untouched
        else:
            out.append(pattern.sub(r'<mark class="match-highlight">\1</mark>', part))
    return "".join(out)


def _tokenize_html_for_diff(html: str) -> list[tuple[str, str]]:
    """Split HTML into (token_text, token_type) pairs.

    token_type is one of: "tag", "word", "space".
    Tags and whitespace are pass-through; only words participate in the diff.
    """
    tag_parts = _HTML_TAG_RE.split(html)
    tokens: list[tuple[str, str]] = []
    for part in tag_parts:
        if _HTML_TAG_RE.fullmatch(part):
            tokens.append((part, "tag"))
        else:
            # Split into alternating whitespace and word runs
            segments = _WORD_SPACE_RE.split(part)
            for seg in segments:
                if not seg:
                    continue
                if _WORD_SPACE_RE.fullmatch(seg):
                    tokens.append((seg, "word"))
                else:
                    tokens.append((seg, "space"))
    return tokens


def _diff_html_content(
    old_html: str | None,
    new_html: str | None,
) -> Tuple[str | None, str | None]:
    """Diff two HTML strings with asymmetric styling per pane.

    Old (comparison) pane: unchanged text is lowlighted, changed text is normal.
    New (current) pane: unchanged text is normal, changed text is highlighted.
    All HTML tags and original whitespace are preserved.
    Returns (annotated_old, annotated_new); both None if either input is empty.
    """
    if not old_html or not new_html:
        return (None, None)

    old_tokens = _tokenize_html_for_diff(old_html)
    new_tokens = _tokenize_html_for_diff(new_html)

    # Extract just the words for diffing
    old_words = [t[0] for t in old_tokens if t[1] == "word"]
    new_words = [t[0] for t in new_tokens if t[1] == "word"]

    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    opcodes = list(matcher.get_opcodes())

    def _render_side(
        tokens: list[tuple[str, str]],
        words: list[str],
        opcodes: Sequence[tuple[str, int, int, int, int]],
        *,
        is_old: bool,
    ) -> str:
        word_status: list[str] = ["equal"] * len(words)
        for op, i1, i2, j1, j2 in opcodes:
            if is_old:
                for idx in range(i1, i2):
                    word_status[idx] = op
            else:
                for idx in range(j1, j2):
                    word_status[idx] = op

        parts: list[str] = []
        word_idx = 0
        for token_text, token_type in tokens:
            if token_type != "word":
                # Tags and whitespace pass through unchanged
                parts.append(token_text)
            else:
                status = word_status[word_idx] if word_idx < len(word_status) else "equal"
                word_idx += 1
                if status == "equal":
                    side = "old" if is_old else "new"
                    parts.append(
                        f'<span class="diff-{side}-unchanged">{token_text}</span>'
                    )
                else:
                    parts.append(token_text)
        return "".join(parts)

    old_result = _render_side(old_tokens, old_words, opcodes, is_old=True)
    new_result = _render_side(new_tokens, new_words, opcodes, is_old=False)
    return (old_result, new_result)


def _build_code_display_name(code_edition: str) -> str:
    """Turn 'OBC_2024' into 'Ontario Building Code 2024'."""
    parts = code_edition.split("_", 1)
    prefix = parts[0]
    year = parts[1] if len(parts) > 1 else ""
    display = get_code_display_name(prefix)
    return f"{display} {year}".strip()


def _code_order_key(value: str) -> Tuple[Any, ...]:
    parts = re.split(r"(\d+)", value or "")
    key: list[Any] = []
    for part in parts:
        if not part:
            continue
        key.append(int(part) if part.isdigit() else part.lower())
    return tuple(key)


def _build_copy_text(
    *,
    code_edition: str,
    division: str,
    provision_id: str,
    title: str,
    version: Any,
    most_recent_clause: Any,
    base_regulation: Any,
    next_version: Any,
) -> str:
    """Reference string for the clipboard copy button.

    Per ``tasks/provenance/4-display.md`` §"Copy Button"::

        OBC 1997, Div B, S 3.1.4.7. -- Fire Separations
        Base: O. Reg. 403/97
        Amended by: O. Reg. 22/98, cl. 1.(1) (1998-04-06)
        Next amendment: O. Reg. 152/99 (1999-04-01) -- not in force at query date

    The in-force date sits with whatever regulation is currently *operative*:
    the amending clause when the provision has been amended, otherwise the base
    regulation. The base reg is always shown for provenance, labelled ``Base:``
    (undated unless it is itself the operative one).
    """
    code_display = _build_code_display_name(code_edition).strip() or code_edition
    div_label = f"Div {division}, " if division else ""
    header = f"{code_display}, {div_label}S {provision_id} -- {title}".strip()

    lines = [header]
    in_force = (
        version.effective_date.isoformat()
        if version and version.effective_date else None
    )
    in_force_suffix = f" ({in_force})" if in_force else ""

    if most_recent_clause and most_recent_clause.regulation:
        # Amended: the current text was put in force by this clause, so the
        # in-force date belongs on the "Amended by" line (not the regulation's
        # own filing date, which is a different event). The base reg is still
        # shown for provenance, labelled and undated — it isn't operative now.
        if base_regulation:
            lines.append(f"Base: O. Reg. {base_regulation.reg_id}")
        reg = most_recent_clause.regulation
        lines.append(
            f"Amended by: O. Reg. {reg.reg_id}, "
            f"cl. {most_recent_clause.clause_id}{in_force_suffix}"
        )
    elif base_regulation:
        # Unamended: the base regulation is what's currently in force, so the
        # in-force date sits with it.
        lines.append(f"Base: O. Reg. {base_regulation.reg_id}{in_force_suffix}")
    elif in_force:
        # No linked regulation (e.g. a base-enactment gap): the date has no
        # operative reg to attach to, so it stands alone.
        lines.append(f"In force: {in_force}")
    if next_version:
        # Earliest-filed contributing clause (apply_order==0), not the
        # heap-order contributing_clauses.all()[0] — see
        # CodeEditionProvisionVersion.first_contributing_clause.
        first_clause = next_version.first_contributing_clause
        if first_clause and first_clause.regulation:
            reg = first_clause.regulation
            date_part = (
                f" ({next_version.effective_date.isoformat()})"
                if next_version.effective_date else ""
            )
            lines.append(
                f"Next amendment: O. Reg. {reg.reg_id}{date_part} "
                "-- not in force at query date"
            )
    return "\n".join(lines)


def _join_terms(terms: Sequence[str]) -> str:
    """Join terms readably: 'a' · 'a and b' · 'a, b, and c'."""
    items = [t for t in terms if t]
    if not items:
        return "your search"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _reference_label(ref: str) -> str:
    """Human label for a matched reference: 'table-3.1.4.7' -> 'Table 3.1.4.7'."""
    is_table, segs = _ref_parts(ref)
    core = ".".join(segs)
    return f"Table {core}" if is_table else core


def _build_score_explanation(
    match_type: str | None,
    matched_terms: Sequence[str],
    matched_terms_indirect: Sequence[str] = (),
) -> str:
    """One plain-English sentence explaining why a result matched.

    Driven by the engine's ``match_type`` so the card can say *why* a provision
    ranked rather than show an opaque score the user can't calibrate.  Keyword
    results distinguish *direct* hits (terms the user typed) from *indirect*
    ones (LLM-added variants and synonyms), so the sentence never claims the
    user searched for a word they didn't type.
    """
    direct = list(matched_terms or [])
    indirect = list(matched_terms_indirect or [])
    first = direct[0] if direct else ""
    if match_type == "exact_id":
        return f"You referenced {_reference_label(first)} — this is that provision."
    if match_type == "ancestor_id":
        return f"A sub-provision of {_reference_label(first)}, which you referenced."
    if match_type == "table_ref":
        return f"Contains {_reference_label(first)}, the table you referenced."
    if match_type == "fuzzy":
        return f"Close approximate match on {_join_terms(direct or indirect)}."
    if match_type in ("exact", "synonym"):
        if direct and indirect:
            return (
                f"Directly matched your search for {_join_terms(direct)}; "
                f"indirectly matched {_join_terms(indirect)}."
            )
        if direct:
            return f"Directly matched your search for {_join_terms(direct)}."
        if indirect:
            return f"Indirectly matched {_join_terms(indirect)} (synonym of your search)."
    return "Matched your search."


def _record_covers_provision(
    record: Dict[str, Any], provision_id: str, division: str
) -> bool:
    """Does a commencement record's ``resolved_provisions`` name this provision?

    Refs arrive as ``"<ref>|<division>"`` with the ref at whatever granularity
    the commencement clause resolved — a sentence (``1.10.2.3.(2)``), a whole
    article (``1.10.2.4.``) — and with an inconsistent trailing dot
    (``4.2.1.1.(1).|C`` vs ``1.10.2.3.(2)|C``).  Reduce the ref to its dotted
    address and prefix-match, so a record resolving a sentence also covers its
    article and a record resolving an article covers its containers.
    """
    target = provision_id.rstrip(".")
    if not target:
        return False
    for raw in record.get("resolved_provisions") or []:
        ref, _, ref_division = raw.partition("|")
        if ref_division != (division or ""):
            continue
        address = ref.split("(", 1)[0].rstrip(".")
        if address == target or address.startswith(target + "."):
            return True
    return False


def select_commencement_record(
    records: Any,
    provision_id: str,
    division: str,
    on_date: date | None,
) -> Dict[str, Any] | None:
    """The commencement record that explains why ``on_date`` is the date.

    A record can only explain a date it actually sets, so candidates are
    filtered to ``effective_date == on_date`` first — a schedule that doesn't
    mention the date yields None rather than a plausible-but-wrong popup.
    Among candidates, one naming this provision wins (staggered schedules pin
    later dates onto specific provisions), then the default record, then a
    sole survivor.
    """
    if not records or on_date is None:
        return None
    iso = on_date.isoformat()
    candidates = [r for r in records if r.get("effective_date") == iso]
    for record in candidates:
        if _record_covers_provision(record, provision_id, division):
            return record
    for record in candidates:
        if record.get("is_default"):
            return record
    return candidates[0] if len(candidates) == 1 else None


def replacement_commencement(
    edition: CodeEdition,
    provision_id: str,
    division: str,
    on_date: date | None,
    records_memo: Dict[int, Any] | None = None,
) -> Dict[str, Any] | None:
    """Why an edition-final version ends: the NEXT edition's base regulation.

    A provision's last version has no next version to prove its end — the
    edition itself was replaced.  ``EditionTransition`` names the replacing
    edition (it isn't derivable from the version chain), and that edition's
    base regulation's commencement schedule carries the record for the
    takeover date.  The same date guard as ``select_commencement_record``
    applies, so staggered old-edition endings (e.g. a 2016 ineffective date
    inside a 2014 replacement) simply yield no record rather than a wrong one.

    ``records_memo`` (old-edition pk → base-reg commencement records) lets a
    results page resolve many provisions with one lookup per edition.
    """
    if records_memo is not None and edition.pk in records_memo:
        records = records_memo[edition.pk]
    else:
        transition = (
            EditionTransition.objects.filter(old_edition=edition)
            .order_by("new_edition__effective_date")
            .first()
        )
        base = (
            Regulation.objects.filter(
                edition=transition.new_edition_id, role=Regulation.Role.BASE
            ).first()
            if transition is not None
            else None
        )
        records = base.commencement if base is not None else None
        if records_memo is not None:
            records_memo[edition.pk] = records
    return select_commencement_record(records, provision_id, division, on_date)


def _format_single_result(
    result: Dict[str, Any],
    query_date: date | None = None,
    terms: Iterable[str] | None = None,
    replacement_memo: Dict[int, Any] | None = None,
) -> Dict[str, Any]:
    code_edition = result.get("code_edition", "Unknown")
    provision = result.get("provision")
    version = result.get("version")
    parent_id = ""
    if provision and provision.parent:
        parent_id = provision.parent.provision_id

    # Derive provenance from prefetched relationships
    base_regulation = None
    all_versions = []
    appendix_notes = []
    contributing_clauses: list = []
    if provision:
        # Base regulation: from prefetched edition.regulations
        for reg in provision.edition.regulations.all():
            if reg.role == "base":
                base_regulation = reg
                break
        # Full version chain: from prefetched provision.versions
        all_versions = list(provision.versions.all())
        # Appendix notes: from prefetched provision.appendix_entries
        for ap in provision.appendix_entries.all():
            latest = ap.versions.order_by("-version").first() if ap.versions.all() else None
            appendix_notes.append({
                "id": ap.provision_id,
                "title": latest.title if latest else "",
                "html": latest.html if latest else "",
            })

    if version:
        contributing_clauses = list(version.contributing_clauses.all())

    # Next-version-not-in-force: orchestration prefetches into
    # provision.next_versions (to_attr).
    next_version = None
    if provision is not None and hasattr(provision, "next_versions"):
        nexts = getattr(provision, "next_versions", []) or []
        next_version = nexts[0] if nexts else None
    # Fallback: pick the next version from the full chain when the
    # to_attr prefetch wasn't applied (e.g. test setups not going
    # through orchestration).
    if next_version is None and version and all_versions:
        for v in all_versions:
            if v.version > version.version:
                next_version = v
                break

    transition_provision_version = (
        version.transition_provision if version else None
    )

    # The representative "amended by" clause is the last one applied to this
    # version, ordered by the through model's apply_order (see
    # CodeEditionProvisionVersion.last_contributing_clause). Using that
    # property keeps the header, amendment chain, and next-version rows
    # consistent — a plain contributing_clauses[-1] is non-deterministic.
    most_recent_clause = (
        version.last_contributing_clause if version else None
    ) or result.get("clause")

    # IN FORCE band rail geometry. The "until" edge is the version's own
    # ineffective date, falling back to the next version's effective date;
    # None means open-ended (still current). Geometry is None when there's
    # no effective date to anchor on.
    until_date = None
    if version is not None:
        until_date = getattr(version, "ineffective_date", None)
        if until_date is None and next_version is not None:
            until_date = next_version.effective_date
    band = compute_band_geometry(
        version.effective_date if version else None,
        until_date,
        query_date,
    )

    html_content = result.get("html_content")
    if html_content and appendix_notes:
        html_content = _linkify_appendix_refs(html_content)
    if html_content and terms:
        html_content = highlight_terms(html_content, terms)

    copy_text = _build_copy_text(
        code_edition=code_edition,
        division=result.get("division", ""),
        provision_id=str(result.get("id", "")),
        title=result.get("title", "No title"),
        version=version,
        most_recent_clause=most_recent_clause,
        base_regulation=base_regulation,
        next_version=next_version,
    )

    # Commencement provenance for the band's two edges, so every version can
    # show why it started AND ended — amended or not.
    #
    # From: the producing clause's resolved entry; a base version (no clause)
    # falls back to the base regulation's own commencement schedule, picking
    # the record for this provision (staggered schedules pin later dates onto
    # specific provisions).
    #
    # Until: this version ends exactly when the NEXT version comes into force,
    # so the proof is the next version's clause entry.  An edition-final
    # version (no next version, ineffective) ends because the next edition's
    # base regulation replaced it — that schedule carries the record.
    provision_ref = str(result.get("id", ""))
    division_ref = result.get("division", "")
    from_commencement = most_recent_clause.commencement if most_recent_clause else None
    if from_commencement is None and most_recent_clause is None and version and base_regulation:
        from_commencement = select_commencement_record(
            base_regulation.commencement,
            provision_ref,
            division_ref,
            version.effective_date,
        )
    next_clause = next_version.last_contributing_clause if next_version else None
    until_commencement = next_clause.commencement if next_clause else None
    until_commencement_date = next_version.effective_date if next_version else None
    if (
        until_commencement is None
        and next_version is None
        and version is not None
        and version.ineffective_date is not None
        and provision is not None
    ):
        until_commencement = replacement_commencement(
            provision.edition,
            provision_ref,
            division_ref,
            version.ineffective_date,
            replacement_memo,
        )
        until_commencement_date = version.ineffective_date if until_commencement else None

    return {
        "id": result.get("id"),
        "title": result.get("title", "No title"),
        "code": code_edition,
        "code_display_name": _build_code_display_name(code_edition),
        "code_edition": code_edition,
        "parent_id": parent_id,
        "source_date": result.get("source_date"),
        "score": result.get("score", 0),
        "match_type": result.get("match_type"),
        "matched_terms": result.get("matched_terms") or [],
        "matched_terms_indirect": result.get("matched_terms_indirect") or [],
        # Term chips reinforce keyword matches; for reference matches the
        # sentence already names the provision/table, so chips are redundant.
        "show_matched_terms": result.get("match_type") in ("exact", "synonym", "fuzzy"),
        "score_explanation": _build_score_explanation(
            result.get("match_type"),
            result.get("matched_terms") or [],
            result.get("matched_terms_indirect") or [],
        ),
        "html_content": html_content,
        "page_images": result.get("page_images") or [],
        "tables": result.get("tables") or [],
        "group_type": None,
        "result_type": None,
        "transition_context": result.get("transition_context"),
        "division": result.get("division", ""),
        # Single-clause back-compat for existing templates; most_recent_clause
        # carries the same value via the contributing_clauses[-1] selection.
        "clause": most_recent_clause,
        "most_recent_clause": most_recent_clause,
        "contributing_clauses": contributing_clauses,
        "is_base": result.get("is_base", True),
        # Structural heading node (part/section/subsection/division): never
        # carries body text, so the document block suppresses the
        # "Content not yet available" notice rather than implying a data gap.
        "is_structural": bool(provision and provision.level in _CONTAINER_LEVELS),
        "version": version,
        "provision": provision,
        "base_regulation": base_regulation,
        "next_version": next_version,
        "from_commencement": from_commencement,
        "until_commencement": until_commencement,
        "until_commencement_date": until_commencement_date,
        "amendment_chain": all_versions,
        "appendix_notes": appendix_notes,
        "transition_provision_version": transition_provision_version,
        "copy_text": copy_text,
        "band": band,
    }


def _build_group_lookup_key(result: Dict[str, Any]) -> tuple[str, str, str] | None:
    parent_id = result.get("parent_id")
    code = result.get("code")
    if not parent_id or not code:
        return None
    division = result.get("division", "")
    return str(code), str(parent_id), str(division)


def _in_force_title(
    versions: list[CodeEditionProvisionVersion],
    query_date: date | None,
    fallback_id: str,
    *,
    log_label: str,
) -> str:
    """Title of the version in force on ``query_date`` (for a group label).

    Group labels must read as the provision did on the queried date, not as
    it ends up — otherwise a provision that is later *revoked* shows its
    "Revoked: …" sentinel title even when the query lands while it was
    substantively in force (see ``order_by("-version")`` regression).

    Falls back to the latest version when there's no as-of date, when the
    provision has no versions, or when *nothing* is in force on the date —
    the last case is a data anomaly for a provision search just surfaced, so
    it's logged as an error.  Zero-width "as-filed but superseded same day"
    versions (``ineffective == effective``) are skipped, mirroring the
    in-force search filter.
    """
    if not versions:
        return fallback_id
    latest = max(versions, key=lambda v: v.version)
    if query_date is None:
        return latest.title or fallback_id
    in_force = next(
        (
            v
            for v in versions
            if v.effective_date <= query_date
            and (v.ineffective_date is None or query_date < v.ineffective_date)
            and v.ineffective_date != v.effective_date
        ),
        None,
    )
    if in_force is None:
        logger.error(
            "Group label: no version of %s in force on %s; "
            "falling back to latest (v%s) title.",
            log_label,
            query_date.isoformat(),
            latest.version,
        )
        return latest.title or fallback_id
    return in_force.title or fallback_id


def _load_group_hierarchy(
    formatted_results: Iterable[Dict[str, Any]],
    query_date: date | None = None,
) -> Dict[tuple[str, str, str], Dict[str, Any]]:
    group_keys = {
        key for result in formatted_results if (key := _build_group_lookup_key(result)) is not None
    }
    hierarchy: Dict[tuple[str, str, str], Dict[str, Any]] = {}

    for code_edition, parent_id, division in group_keys:
        system_code = code_edition.split("_", 1)[0] if "_" in code_edition else code_edition
        edition_id = code_edition.split("_", 1)[1] if "_" in code_edition else ""

        prov_filter: Dict[str, Any] = {
            "edition__code__code": system_code,
            "edition__edition_id": edition_id,
        }
        if division:
            prov_filter["division"] = division

        parent_prov = (
            CodeEditionProvision.objects.filter(provision_id=parent_id, **prov_filter)
            .first()
        )
        # Title the group as the parent read on the query date — not its
        # latest (possibly "Revoked: …") version. See _in_force_title.
        parent_title = parent_id
        if parent_prov:
            parent_title = _in_force_title(
                list(parent_prov.versions.all()),
                query_date,
                parent_id,
                log_label=f"{code_edition} {division} {parent_id}".strip(),
            )

        child_provs = CodeEditionProvision.objects.filter(
            parent=parent_prov, **{
                k: v for k, v in prov_filter.items()
                if k not in ("edition__code__code", "edition__edition_id")
            }
        ) if parent_prov else CodeEditionProvision.objects.none()

        child_nodes = []
        for child in child_provs:
            child_nodes.append({
                "node_id": child.provision_id,
                "title": _in_force_title(
                    list(child.versions.all()),
                    query_date,
                    child.provision_id,
                    log_label=f"{code_edition} {division} {child.provision_id}".strip(),
                ),
                "page": None,
                "page_end": None,
            })
        child_nodes.sort(key=lambda item: _code_order_key(str(item.get("node_id") or "")))

        hierarchy[(code_edition, parent_id, division)] = {
            "parent_title": parent_title,
            "children": child_nodes,
        }

    return hierarchy


def _build_grouped_result(
    matched_results: List[Dict[str, Any]],
    hierarchy: Dict[str, Any],
    group_key: tuple[str, str, str],
) -> Dict[str, Any] | None:
    if len(matched_results) <= 1:
        return None

    child_nodes = hierarchy.get("children") or []
    child_total_count = len(child_nodes)
    if child_total_count <= 1:
        return None

    matched_by_id = {str(item.get("id")): item for item in matched_results if item.get("id")}
    child_match_count = sum(
        1 for child in child_nodes if str(child.get("node_id")) in matched_by_id
    )
    if child_match_count <= 1:
        return None
    if (child_match_count / child_total_count) <= 0.8:
        return None

    top_scoring_child = max(
        matched_results,
        key=lambda item: (item.get("score", 0), -matched_results.index(item)),
    )
    parent_id = group_key[1]
    children = []
    for child in child_nodes:
        child_id = str(child.get("node_id"))
        matched = matched_by_id.get(child_id)
        children.append(
            {
                "id": child_id,
                "title": child.get("title") or child_id,
                "page": (matched or child).get("page"),
                "page_end": (matched or child).get("page_end"),
                "score": (matched or {}).get("score", 0),
                "is_match": matched is not None,
                "is_top_scoring": child_id == top_scoring_child.get("id"),
                # Full formatted result for matched children so the template can
                # accordion each open to its own content (provenance + body +
                # justification) — grouping is a UI aide, not a content drop.
                # Unmatched "context" children weren't search hits, so they have
                # no formatted body and stay label-only.
                "result": matched,
            }
        )

    grouped = dict(top_scoring_child)
    grouped.update(
        {
            "id": parent_id,
            "title": hierarchy.get("parent_title") or parent_id,
            "group_type": "parent_children",
            "parent_id": parent_id,
            "children": children,
            "top_scoring_child_id": top_scoring_child.get("id"),
            "active_child": {
                "id": top_scoring_child.get("id"),
                "title": top_scoring_child.get("title"),
            },
            "child_match_count": child_match_count,
            "child_total_count": child_total_count,
            "matched_child_ids": [item.get("id") for item in matched_results if item.get("id")],
        }
    )
    return grouped


def group_formatted_results(
    formatted_results: List[Dict[str, Any]],
    hierarchy_by_group: Dict[tuple[str, str, str], Dict[str, Any]] | None = None,
    query_date: date | None = None,
) -> List[Dict[str, Any]]:
    if hierarchy_by_group is None:
        hierarchy_by_group = _load_group_hierarchy(formatted_results, query_date)

    matched_results_by_group: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
    for result in formatted_results:
        key = _build_group_lookup_key(result)
        if key is None:
            continue
        matched_results_by_group.setdefault(key, []).append(result)

    grouped_results_by_key: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for key, matched_results in matched_results_by_group.items():
        grouped = _build_grouped_result(matched_results, hierarchy_by_group.get(key, {}), key)
        if grouped is not None:
            grouped_results_by_key[key] = grouped

    collapsed_keys: set[tuple[str, str, str]] = set()
    output: List[Dict[str, Any]] = []
    for result in formatted_results:
        key = _build_group_lookup_key(result)
        if key in grouped_results_by_key:
            if key in collapsed_keys:
                continue
            output.append(grouped_results_by_key[key])
            collapsed_keys.add(key)
            continue
        # A provision that matches on its own AND is the parent of a built group
        # is already represented by that group card (id == parent_id).  Don't
        # leave it as a second standalone row — that duplicates the parent and
        # collides on the accordion key (code + id).  Instead absorb its match
        # onto the group as ``parent_result`` so the group can still surface the
        # parent provision's own title/provenance/content (it isn't lost, just
        # not a separate row).
        identity = (
            str(result.get("code") or ""),
            str(result.get("id") or ""),
            str(result.get("division") or ""),
        )
        if identity in grouped_results_by_key:
            group = grouped_results_by_key[identity]
            group["parent_result"] = result
            # The group card header shows the *parent's* score (the child it was
            # cloned from lent its score); each child keeps its own in its
            # accordion.  Phase-3 groups already carry the parent's score.
            group["score"] = result.get("score", group.get("score", 0))
            continue
        output.append(result)

    return output


def merge_transition_compare_results(
    formatted_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collapse each transition pair into a single ``transition_compare`` card.

    Orchestration (``_group_transitions`` / ``_merge_provision_mapping_transitions``)
    is the authority on *which* two results form a pair — it stamps both members
    with a shared ``pair_key`` and an ``is_primary`` flag (True on the newer
    member).  We group on that token rather than re-deriving the pairing from
    ``id``/edition, so pairs whose members carry different provision ids
    (cross- or intra-edition renumbers) group correctly instead of colliding.
    """
    # Pass 1: bucket paired members by their upstream pair_key, split by role.
    pairs: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for result in formatted_results:
        transition_context = result.get("transition_context")
        if not transition_context or result.get("group_type") == "parent_children":
            continue
        pair_key = transition_context.get("pair_key")
        if not pair_key:
            continue
        role = "new" if transition_context.get("is_primary") else "old"
        pairs.setdefault(pair_key, {})[role] = result

    # Pass 2: emit one card per complete pair, at the first member's position.
    consumed_keys: set[str] = set()
    output: List[Dict[str, Any]] = []
    for result in formatted_results:
        transition_context = result.get("transition_context")
        if not transition_context or result.get("group_type") == "parent_children":
            output.append(result)
            continue

        pair_key = transition_context.get("pair_key")
        members = pairs.get(pair_key, {}) if pair_key else {}
        new_version = members.get("new")
        old_version = members.get("old")
        # Unpaired (only one member surfaced) or degenerate (both roles point at
        # the same result) -> render plainly rather than compare-to-self.
        if not new_version or not old_version or new_version is old_version:
            output.append(result)
            continue
        if pair_key in consumed_keys:
            continue

        consumed_keys.add(pair_key)
        has_renderable_content = bool(
            old_version.get("html_content")
            or old_version.get("page_images")
            or new_version.get("html_content")
            or new_version.get("page_images")
        )
        old_diff, new_diff = _diff_html_content(
            old_version.get("html_content"),
            new_version.get("html_content"),
        )
        if old_diff is not None:
            old_version["diff_html"] = old_diff
        if new_diff is not None:
            new_version["diff_html"] = new_diff
        # Explain the pair using whichever version actually earned the score.
        top_version = max(
            (old_version, new_version), key=lambda v: v.get("score", 0)
        )
        output.append(
            {
                "id": result.get("id"),
                "title": new_version.get("title")
                or old_version.get("title")
                or result.get("title"),
                "code": new_version.get("code")
                or old_version.get("code")
                or result.get("code"),
                "code_display_name": new_version.get("code_display_name")
                or result.get("code_display_name"),
                "score": max(new_version.get("score", 0), old_version.get("score", 0)),
                "match_type": top_version.get("match_type"),
                "matched_terms": top_version.get("matched_terms") or [],
                "matched_terms_indirect": top_version.get("matched_terms_indirect") or [],
                "show_matched_terms": top_version.get("show_matched_terms", False),
                "score_explanation": top_version.get("score_explanation"),
                "result_type": "transition_compare",
                "transition_context": transition_context,
                "has_renderable_content": has_renderable_content,
                "versions": [old_version, new_version],
            }
        )

    return output


def _nest_result_key(
    result: Dict[str, Any],
) -> tuple[str, str, str]:
    """Build a (code, id, division) key that scopes nesting per edition."""
    return (
        str(result.get("code") or ""),
        str(result.get("id") or ""),
        str(result.get("division") or ""),
    )


def _nest_child_results(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Group child results under their parent when both appear in the result list.

    Unlike the >80% Phase 2 grouping which fills in context siblings, this only
    includes children that were actually returned by the search.

    Keys are scoped by (code, map_code, id, division) so that identically-numbered
    sections across different editions (OBC vs NBC, or transition pairs) never
    collide.
    """
    # Full composite key → result
    results_by_key: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for result in results:
        key = _nest_result_key(result)
        if key[1]:  # has an id
            results_by_key[key] = result

    # Collect children per parent (only when the parent itself is also a result)
    children_by_parent: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
    for result in results:
        parent_id = result.get("parent_id")
        if not parent_id:
            continue
        result_id = str(result.get("id") or "")
        if str(parent_id) == result_id:
            continue
        if result.get("group_type") == "parent_children":
            continue
        parent_key = (
            str(result.get("code") or ""),
            str(parent_id),
            str(result.get("division") or ""),
        )
        if parent_key not in results_by_key:
            continue
        parent = results_by_key[parent_key]
        if parent.get("group_type") == "parent_children":
            continue
        children_by_parent.setdefault(parent_key, []).append(result)

    # Convert each parent + children set into a grouped card
    absorbed_child_keys: set[tuple[str, str, str]] = set()
    for parent_key, children in children_by_parent.items():
        parent = results_by_key[parent_key]
        # Snapshot the parent's own match before we mutate it into the group
        # card, so the template can still surface the parent provision (its
        # title/provenance/content) — parity with the Phase-2 ``parent_result``.
        parent_self = dict(parent)
        top_child = max(children, key=lambda c: (c.get("score", 0),))
        child_entries = []
        for child in sorted(children, key=lambda c: _code_order_key(str(c.get("id", "")))):
            child_id = str(child.get("id", ""))
            child_entries.append({
                "id": child_id,
                "title": child.get("title") or child_id,
                "page": child.get("page"),
                "page_end": child.get("page_end"),
                "score": child.get("score", 0),
                "is_match": True,
                "is_top_scoring": child_id == str(top_child.get("id", "")),
                # Full formatted child so the template accordions it open to its
                # own content — parity with Phase-2 grouping.
                "result": child,
            })
            absorbed_child_keys.add(_nest_result_key(child))

        parent["group_type"] = "parent_children"
        parent["children"] = child_entries
        parent["parent_result"] = parent_self
        parent["top_scoring_child_id"] = str(top_child.get("id", ""))
        parent["active_child"] = {
            "id": top_child.get("id"),
            "title": top_child.get("title"),
        }
        parent["child_match_count"] = len(children)
        parent["child_total_count"] = len(children)
        parent["matched_child_ids"] = [str(c.get("id", "")) for c in children]
        # The card keeps the parent's own score (header) — its content is no
        # longer rendered at card level, so nothing is carried from the child;
        # each child shows its own body and score in its accordion.

    return [r for r in results if _nest_result_key(r) not in absorbed_child_keys]


def _attach_lineage(formatted: List[Dict[str, Any]], user: Any = None) -> None:
    """Stamp lineage rows onto every result, one batched resolver call.

    Runs on the still-flat list, BEFORE grouping/pairing/nesting: transition
    panes and nested children keep references to these same dicts, so every
    rail render site (result rail, compare panes, banner) sees the keys
    without walking the grouped structure.  Kept as separate keys next to
    ``amendment_chain`` — never spliced into it (that list means "versions
    of this provision in this edition"; lineage entries carry their own
    edition/division/id and prebuilt URLs).
    """
    lineage = resolve_lineage(
        [r["provision"] for r in formatted if r.get("provision")]
    )
    annotate_lineage_locks(lineage.values(), user)
    for result in formatted:
        provision = result.get("provision")
        lin = lineage.get(provision.pk) if provision is not None else None
        result["lineage_predecessors"] = lin.predecessors if lin else None
        result["lineage_successors"] = lin.successors if lin else None


def format_search_results(
    results: List[Dict[str, Any]],
    query_date: date | str | None = None,
    terms: Iterable[str] | None = None,
    user: Any = None,
) -> List[Dict[str, Any]]:
    """Transform raw search results into a format suitable for the frontend.

    ``query_date`` (a ``date`` or ISO string) drives the IN FORCE band's
    query tick + coverage; omit it and the band still renders its date span.
    ``terms`` (parsed query keywords) are highlighted in the provision body;
    omit or pass empty to skip highlighting.  ``user`` feeds the free-tier
    gate on lineage links (None reads as anonymous — most restrictive).
    """
    parsed_query_date = parse_iso_date(query_date)
    # Shared per-call memo: edition-final results resolve their replacing
    # edition's base-reg commencement once per edition, not once per result.
    replacement_memo: Dict[int, Any] = {}
    formatted = [
        _format_single_result(result, parsed_query_date, terms, replacement_memo)
        for result in results
    ]
    _attach_lineage(formatted, user)
    formatted.sort(key=lambda item: item.get("score", 0), reverse=True)
    grouped = group_formatted_results(formatted, query_date=parsed_query_date)
    merged = merge_transition_compare_results(grouped)
    return _nest_child_results(merged)


def get_amendments_for_provision(provision_id: str, code_edition: str) -> List[Dict[str, Any]]:
    """Placeholder for amendment chain lookup. Will be populated from regulation data."""
    return []
