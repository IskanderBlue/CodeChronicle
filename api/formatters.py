"""
Format search results for frontend display.
"""

import difflib
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from api.band import compute_band_geometry, parse_iso_date
from config.code_metadata import get_code_display_name
from core.models import CodeEditionProvision

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
        In force: 1998-04-06 (O. Reg. 403/97)
        Amended by: O. Reg. 22/98, cl. 1.(1) (1998-04-06)
        Next amendment: O. Reg. 152/99 (1999-04-01) -- not in force at query date
    """
    code_display = _build_code_display_name(code_edition).strip() or code_edition
    div_label = f"Div {division}, " if division else ""
    header = f"{code_display}, {div_label}S {provision_id} -- {title}".strip()

    lines = [header]
    if version and version.effective_date:
        in_force = version.effective_date.isoformat()
        if base_regulation:
            lines.append(
                f"In force: {in_force} (O. Reg. {base_regulation.reg_id})"
            )
        else:
            lines.append(f"In force: {in_force}")
    if most_recent_clause and most_recent_clause.regulation:
        reg = most_recent_clause.regulation
        date_part = (
            f" ({reg.effective_date.isoformat()})"
            if getattr(reg, "effective_date", None) else ""
        )
        lines.append(
            f"Amended by: O. Reg. {reg.reg_id}, cl. {most_recent_clause.clause_id}{date_part}"
        )
    if next_version and next_version.contributing_clauses.exists():
        first_clause = next_version.contributing_clauses.all()[0]
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


def _format_single_result(
    result: Dict[str, Any],
    query_date: date | None = None,
    terms: Iterable[str] | None = None,
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

    return {
        "id": result.get("id"),
        "title": result.get("title", "No title"),
        "code": code_edition,
        "code_display_name": _build_code_display_name(code_edition),
        "code_edition": code_edition,
        "parent_id": parent_id,
        "source_date": result.get("source_date"),
        "score": result.get("score", 0),
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
        "version": version,
        "provision": provision,
        "base_regulation": base_regulation,
        "next_version": next_version,
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


def _load_group_hierarchy(
    formatted_results: Iterable[Dict[str, Any]],
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
        # Get the latest version title for the parent
        parent_title = parent_id
        if parent_prov:
            latest_version = parent_prov.versions.order_by("-version").first()
            if latest_version:
                parent_title = latest_version.title or parent_id

        child_provs = CodeEditionProvision.objects.filter(
            parent=parent_prov, **{
                k: v for k, v in prov_filter.items()
                if k not in ("edition__code__code", "edition__edition_id")
            }
        ) if parent_prov else CodeEditionProvision.objects.none()

        child_nodes = []
        for child in child_provs:
            latest = child.versions.order_by("-version").first()
            child_nodes.append({
                "node_id": child.provision_id,
                "title": (latest.title if latest else "") or child.provision_id,
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
            "viewer_node_id": top_scoring_child.get("id"),
            "viewer_title": top_scoring_child.get("title"),
            "child_match_count": child_match_count,
            "child_total_count": child_total_count,
            "matched_child_ids": [item.get("id") for item in matched_results if item.get("id")],
        }
    )
    return grouped


def group_formatted_results(
    formatted_results: List[Dict[str, Any]],
    hierarchy_by_group: Dict[tuple[str, str, str], Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    if hierarchy_by_group is None:
        hierarchy_by_group = _load_group_hierarchy(formatted_results)

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
        output.append(result)

    return output


def merge_transition_compare_results(
    formatted_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    transition_groups: Dict[tuple[str, str, str], Dict[str, Dict[str, Any]]] = {}
    for result in formatted_results:
        transition_context = result.get("transition_context")
        if not transition_context or result.get("group_type") == "parent_children":
            continue
        key = (
            str(result.get("id") or ""),
            str(transition_context.get("new_edition") or ""),
            str(transition_context.get("old_edition") or ""),
        )
        edition = str(result.get("code") or "")
        transition_groups.setdefault(key, {})[edition] = result

    consumed_keys: set[tuple[str, str, str]] = set()
    output: List[Dict[str, Any]] = []
    for result in formatted_results:
        transition_context = result.get("transition_context")
        if not transition_context or result.get("group_type") == "parent_children":
            output.append(result)
            continue

        key = (
            str(result.get("id") or ""),
            str(transition_context.get("new_edition") or ""),
            str(transition_context.get("old_edition") or ""),
        )
        grouped_versions = transition_groups.get(key, {})
        if key in consumed_keys:
            continue

        new_version = grouped_versions.get(str(transition_context.get("new_edition") or ""))
        old_version = grouped_versions.get(str(transition_context.get("old_edition") or ""))
        if not new_version or not old_version:
            output.append(result)
            continue

        consumed_keys.add(key)
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
        if key[2]:  # has an id
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
            })
            absorbed_child_keys.add(_nest_result_key(child))

        parent["group_type"] = "parent_children"
        parent["children"] = child_entries
        parent["top_scoring_child_id"] = str(top_child.get("id", ""))
        parent["active_child"] = {
            "id": top_child.get("id"),
            "title": top_child.get("title"),
        }
        parent["viewer_node_id"] = top_child.get("id")
        parent["viewer_title"] = top_child.get("title")
        parent["child_match_count"] = len(children)
        parent["child_total_count"] = len(children)
        parent["matched_child_ids"] = [str(c.get("id", "")) for c in children]
        # Carry over content fields from the top-scoring child for the document block
        for field in ("html_content", "page_images", "tables", "notes_html",
                      "page", "page_end"):
            if top_child.get(field) is not None:
                parent[field] = top_child[field]

    return [r for r in results if _nest_result_key(r) not in absorbed_child_keys]


def format_search_results(
    results: List[Dict[str, Any]],
    query_date: date | str | None = None,
    terms: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """Transform raw search results into a format suitable for the frontend.

    ``query_date`` (a ``date`` or ISO string) drives the IN FORCE band's
    query tick + coverage; omit it and the band still renders its date span.
    ``terms`` (parsed query keywords) are highlighted in the provision body;
    omit or pass empty to skip highlighting.
    """
    parsed_query_date = parse_iso_date(query_date)
    formatted = [
        _format_single_result(result, parsed_query_date, terms) for result in results
    ]
    formatted.sort(key=lambda item: item.get("score", 0), reverse=True)
    grouped = group_formatted_results(formatted)
    merged = merge_transition_compare_results(grouped)
    return _nest_child_results(merged)


def get_amendments_for_provision(provision_id: str, code_edition: str) -> List[Dict[str, Any]]:
    """Placeholder for amendment chain lookup. Will be populated from regulation data."""
    return []
