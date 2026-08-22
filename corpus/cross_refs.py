"""Within-edition cross-references: anchoring, inline linking, cite lists.

CCM ships :class:`~core.models.ProvisionCrossReference` records naming a
citation's text, its resolved target version(s), and **where it sits** —
``container`` (the version body, or a table's html / notes) plus ``start`` /
``end`` character offsets into that string.  Rendering a citation is then
"slice, wrap": :func:`linkify` needs no matching at all.

One wrinkle the spans make explicit rather than hide: a span may contain
markup, because the printed citation straddles a block boundary
(``…in Section</p><p>9.38.``).  Those anchor as one link per text run inside
the span (:func:`_span_runs`) rather than being dropped.

**Pre-span payloads.**  Editions built before CCM shipped spans carry only
``surface_text``, so the load derives a position instead: :func:`locate_surfaces`
finds each surface's occurrences (longest-first, claimed spans masked, tag
spans excluded) and :func:`assign_occurrences` pins each record to one.  That
path is a fallback, and a lossy one — it is blind to the ~1.5% of citations
whose text doesn't occur literally, and to the handful of surfaces that also
appear as *external* citations the detector deliberately excluded.  It exists
so a payload already on disk still links; it goes away when the editions
rebuild.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Sequence

from django.template.defaultfilters import date as format_date
from django.utils.html import escape

from core.models import (
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionCrossReference,
    ProvisionVersionTable,
    natural_provision_key,
)
from corpus.permalinks import provision_permalink_url
from corpus.seo import last_governed_day
from shared.html import HTML_TAG_RE


def locate_surfaces(
    html: str, surfaces: Iterable[str]
) -> dict[str, list[tuple[int, int]]]:
    """Find each surface text's occurrences in ``html``, longest-first.

    Returns ``{surface: [(start, end), ...]}`` in document order.  Matches
    inside tags are excluded, and a span claimed by a longer surface is not
    offered to a shorter one — so ``Sentence 3.7.4.3.`` never anchors onto the
    tail of ``Sentence 3.7.4.3.(5)``.  Deterministic for a given (html,
    surfaces) pair: load and render both call this and get the same spans.
    """
    if not html:
        return {}

    text_spans = _text_spans(html)
    claimed: list[tuple[int, int]] = []
    found: dict[str, list[tuple[int, int]]] = {}

    # Longest first so a nested surface can't steal its container's text;
    # the secondary sort makes ties deterministic rather than set-ordered.
    for surface in sorted({s for s in surfaces if s}, key=lambda s: (-len(s), s)):
        spans: list[tuple[int, int]] = []
        for start in _iter_matches(html, surface, text_spans):
            span = (start, start + len(surface))
            if any(c[0] < span[1] and span[0] < c[1] for c in claimed):
                continue
            spans.append(span)
            claimed.append(span)
        found[surface] = spans
    return found


def _text_spans(html: str) -> list[tuple[int, int]]:
    """Character ranges of ``html`` that are text, not markup."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    for tag in HTML_TAG_RE.finditer(html):
        if tag.start() > cursor:
            spans.append((cursor, tag.start()))
        cursor = tag.end()
    if cursor < len(html):
        spans.append((cursor, len(html)))
    return spans


def _iter_matches(
    html: str, surface: str, text_spans: Sequence[tuple[int, int]]
) -> list[int]:
    """Start offsets of ``surface`` in ``html``, wholly inside one text span."""
    starts: list[int] = []
    pos = html.find(surface)
    while pos != -1:
        end = pos + len(surface)
        if any(s <= pos and end <= e for s, e in text_spans):
            starts.append(pos)
        pos = html.find(surface, pos + 1)
    return starts


def _span_runs(html: str, start: int, end: int) -> list[tuple[int, int]]:
    """The text runs of ``html[start:end]`` — the span minus any markup it spans.

    A producer span is exact but not necessarily contiguous text: a citation
    printed across a block boundary spans ``Section</p><p>9.38.``.  Wrapping
    that whole slice in an anchor would nest a block element inside an inline
    one, so the citation links as one anchor per run instead.  Whitespace-only
    runs are dropped (they'd render as a stray clickable gap).
    """
    return [
        (max(start, s), min(end, e))
        for s, e in _text_spans(html)
        if s < end and start < e and html[max(start, s):min(end, e)].strip()
    ]


def assign_occurrences(
    html: str, records: Sequence[ProvisionCrossReference]
) -> int:
    """Set ``occurrence`` on each pre-span record of one container, in place.

    Records sharing a surface text take that surface's occurrences in emission
    order.  A record with no occurrence left to claim keeps ``occurrence=None``
    — either the surface straddles a block boundary, or the producer emitted
    more records than the html has literal occurrences (18 such records in OBC
    1997, 2 in 2012, always with an identical target).  Returns the number of
    records left unanchored, for the loader's log line.

    Records that already carry producer spans are skipped: their position is
    known, and deriving a second one could only disagree.
    """
    records = [r for r in records if r.start is None]
    if not records:
        return 0
    spans = locate_surfaces(html, (r.surface_text for r in records))
    next_index: dict[str, int] = {}
    unanchored = 0
    for record in records:
        index = next_index.get(record.surface_text, 0)
        if index < len(spans.get(record.surface_text, ())):
            record.occurrence = index
            next_index[record.surface_text] = index + 1
        else:
            record.occurrence = None
            unanchored += 1
    return unanchored


def target_on(
    record: ProvisionCrossReference, day: date | None
) -> dict[str, Any] | None:
    """The target slice in force on ``day`` — the last slice when unknown.

    ``targets`` is already clipped to the citing version's window, so for a
    reader looking at that version on ``day`` some slice always covers it.  A
    day outside every slice (a caller passing an unrelated date) falls back to
    the last, rather than dropping the link.
    """
    return _targets_on(record.targets or [], day)


def _targets_on(
    targets: list[dict[str, Any]], day: date | None
) -> dict[str, Any] | None:
    """The slice of a raw ``targets`` list in force on ``day`` — last when unknown.

    Shared by the primary citation and its alternates: both carry a ``targets``
    list the producer clipped and date-sliced identically, so both pick a slice
    the same way.
    """
    if not targets:
        return None
    if day is not None:
        for slice_ in targets:
            start = _parse(slice_.get("effective_date"))
            end = _parse(slice_.get("ineffective_date"))
            if start is not None and start <= day and (end is None or day < end):
                return slice_
    return targets[-1]


def _parse(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _provision_url(
    provision: CodeEditionProvision | None,
    slice_: dict[str, Any],
    code_name: str,
) -> str | None:
    if provision is None:
        return None
    return provision_permalink_url(
        code_name, provision.division, provision.provision_id, slice_["version"]
    )


def _slice_url(
    record: ProvisionCrossReference, slice_: dict[str, Any], code_name: str
) -> str | None:
    return _provision_url(record.to_provision, slice_, code_name)


def _window_title(slice_: dict[str, Any]) -> str:
    start = _parse(slice_.get("effective_date"))
    end = _parse(slice_.get("ineffective_date"))
    if start is None:
        return f"v{slice_['version']}"
    if end is not None and end <= start:
        return f"v{slice_['version']} — never in force"
    # The last day governed, not the stored end: the window is half-open, so
    # the stored date is the first day this text did not apply.
    last = last_governed_day(end)
    tail = f" to {format_date(last, 'j M Y')}" if last else " onward"
    return f"v{slice_['version']} — in force {format_date(start, 'j M Y')}{tail}"


def render_citation(
    record: ProvisionCrossReference,
    code_name: str,
    *,
    label: str | None = None,
    on_date: date | None = None,
    fan_out: bool = False,
    with_chips: bool = True,
) -> str:
    """The html for one citation: ``label`` (default the surface text), linked.

    ``fan_out=False`` (search) links the single target version in force on
    ``on_date`` — the reader asked for a date, so the citation reads as it did
    then.  ``fan_out=True`` (permalink, which pins a version rather than a day)
    links the first slice and follows it with a ``v1`` chip per further slice,
    the presentation ``_permalink_nav_item.html`` already uses for a neighbour
    that read differently across the pinned version's lifetime.

    ``label`` is passed verbatim (it is a slice of the already-escaped source
    html) when a span is being wrapped; ``with_chips=False`` suppresses the
    fan-out chips on all but the last run of a split anchor, so a citation
    broken across a block boundary grows one set of chips, not one per run.

    A no-link record renders as plain text carrying the curator's note.
    """
    text = escape(record.surface_text) if label is None else label
    if record.to_provision is None or not record.targets:
        title = f' title="{escape(record.note)}"' if record.note else ""
        return f'<span class="cross-ref-nolink"{title}>{text}</span>'

    note_suffix = f" — {record.note}" if record.note else ""
    slices = record.targets if fan_out else [target_on(record, on_date)]
    first = slices[0]
    if first is None:
        return text
    url = _slice_url(record, first, code_name)
    if url is None:
        return text

    parts = [
        f'<a href="{url}" class="cross-ref ui-cite" '
        f'data-cross-ref="{escape(record.to_provision.provision_id)}" '
        f'title="{escape(_window_title(first) + note_suffix)}">{text}</a>'
    ]
    if with_chips:
        for slice_ in slices[1:]:
            if slice_ is None:
                continue
            chip_url = _slice_url(record, slice_, code_name)
            if chip_url is None:
                continue
            parts.append(
                f'<a href="{chip_url}" class="cross-ref-chip ui-cite" '
                f'title="{escape(_window_title(slice_) + note_suffix)}">'
                f'v{slice_["version"]}</a>'
            )
        parts.extend(_alternate_chips(record, code_name, on_date, fan_out))
    return "".join(parts)


def _alternate_chips(
    record: ProvisionCrossReference,
    code_name: str,
    on_date: date | None,
    fan_out: bool,
) -> list[str]:
    """Chips for the curator's intended reading(s), hung off the printed link.

    The primary anchor is *what the Code printed*; each alternate is a provision
    a human judged was actually meant.  It reads as a distinct chip (labelled
    with the intended provision id, not a version), carrying the record's
    ``note`` so a hover says why the printed and intended ids differ.  An
    alternate whose provision or slice does not resolve is skipped silently —
    the printed link still stands.
    """
    # An unsaved record (the pure-render tests) can carry no child rows, and
    # its reverse manager would raise on a null pk — nothing to render.
    if record.pk is None:
        return []
    note_tail = f" — {record.note}" if record.note else ""
    chips: list[str] = []
    for alt in record.alternates.all():
        provision = alt.to_provision
        targets = alt.targets or []
        if provision is None or not targets:
            continue
        slice_ = targets[0] if fan_out else _targets_on(targets, on_date)
        if slice_ is None:
            continue
        url = _provision_url(provision, slice_, code_name)
        if url is None:
            continue
        title = f"Reading we believe was intended: {_window_title(slice_)}{note_tail}"
        chips.append(
            f'<a href="{url}" class="cross-ref-alt ui-cite" '
            f'data-cross-ref-alt="{escape(provision.provision_id)}" '
            f'title="{escape(title)}">{escape(provision.provision_id)}</a>'
        )
    return chips


def linkify(
    html: str,
    records: Sequence[ProvisionCrossReference],
    code_name: str,
    *,
    on_date: date | None = None,
    fan_out: bool = False,
) -> str:
    """Splice citation links into ``html`` at each record's position.

    Position comes from the producer's ``start``/``end`` span when the payload
    has one, else from the load-derived ``occurrence`` (see the module
    docstring).  A span containing markup — the block-straddling citations —
    links as one anchor per text run.

    Must run **before** ``search.formatters.formatters.highlight_terms``: highlighting
    inserts ``<mark>`` mid-text and would split a surface string out from under
    the fallback matcher, whereas running this first leaves the anchor's inner
    text as just another text node for highlighting to mark up.
    """
    if not html or not records:
        return html

    fallback = [r for r in records if r.start is None and r.occurrence is not None]
    located = (
        locate_surfaces(html, (r.surface_text for r in fallback)) if fallback else {}
    )

    edits: list[tuple[int, int, str]] = []
    for record in records:
        for start, end, is_last in _record_runs(html, record, located):
            edits.append((start, end, render_citation(
                record, code_name,
                label=html[start:end],
                on_date=on_date,
                fan_out=fan_out,
                with_chips=is_last,
            )))

    # Apply right-to-left so earlier offsets stay valid.
    out = html
    for start, end, replacement in sorted(edits, reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def _record_runs(
    html: str,
    record: ProvisionCrossReference,
    located: dict[str, list[tuple[int, int]]],
) -> list[tuple[int, int, bool]]:
    """Where one record anchors: ``(start, end, is_last_run)`` per anchor."""
    if record.start is not None and record.end is not None:
        if record.end > len(html):
            # The html and its spans ship together, so this means the stored
            # rows outlived the body they indexed (an edited/partial reload).
            return []
        runs = _span_runs(html, record.start, record.end)
    else:
        spans = located.get(record.surface_text, [])
        if record.occurrence is None or record.occurrence >= len(spans):
            return []
        runs = [spans[record.occurrence]]
    return [(s, e, index == len(runs) - 1) for index, (s, e) in enumerate(runs)]


def cites(
    records: Iterable[ProvisionCrossReference],
    code_name: str,
    *,
    on_date: date | None = None,
) -> list[dict[str, Any]]:
    """Outbound citations, deduplicated by target provision.

    The list form of the same records the inline links use — the only
    cross-reference affordance available on a version rendered as page images
    (OBC 1997's scanned base versions), where there is no html to link into.
    """
    rows: dict[str, dict[str, Any]] = {}
    for record in records:
        provision = record.to_provision
        if provision is None:
            continue
        slice_ = target_on(record, on_date) or (record.targets or [None])[-1]
        if slice_ is None:
            continue
        key = f"{provision.division}|{provision.provision_id}"
        rows.setdefault(key, {
            "provision_id": provision.provision_id,
            "division": provision.division,
            "surface_text": record.surface_text,
            "url": _slice_url(record, slice_, code_name),
            "title": _window_title(slice_),
            "note": record.note,
            "provision_pk": provision.pk,
            "version": slice_["version"],
            "alternates": _alternate_rows(record, code_name, on_date),
        })
    out = list(rows.values())
    _stamp_provision_titles(out)
    return out


def _version_titles(
    pairs: Iterable[tuple[int, int]],
) -> dict[tuple[int, int], str]:
    """Provision title for each ``(provision pk, version)`` pair, in one query.

    Keyed by the pair, not by the provision, because a title can change
    between versions: a link must name the title of the version it points at,
    never the provision's latest title.  Untitled versions are left out, so a
    caller's ``.get`` falls back to the id on its own.
    """
    wanted = set(pairs)
    if not wanted:
        return {}
    return {
        (provision_pk, version): title
        for provision_pk, version, title in (
            CodeEditionProvisionVersion.objects
            .filter(provision_id__in={pk for pk, _ in wanted})
            .values_list("provision_id", "version", "title")
        )
        if title and (provision_pk, version) in wanted
    }


def _stamp_provision_titles(rows: list[dict[str, Any]]) -> None:
    """Fill ``provision_title`` on each row and its alternates, in one query.

    The lists name provisions other than the one being read, so the link text
    carries the title (``tasks/c-lineage-anchor-text.md``).  Stamped after the
    rows are built rather than inside the loop: one query for the whole list.
    """
    targets = [r for row in rows for r in (row, *row.get("alternates", ()))]
    titles = _version_titles((r["provision_pk"], r["version"]) for r in targets)
    for row in targets:
        row["provision_title"] = titles.get((row["provision_pk"], row["version"]), "")


def _alternate_rows(
    record: ProvisionCrossReference,
    code_name: str,
    on_date: date | None,
) -> list[dict[str, Any]]:
    """The intended-reading rows for a ``cites`` entry (image-only fallback)."""
    if record.pk is None:
        return []
    out: list[dict[str, Any]] = []
    for alt in record.alternates.all():
        provision = alt.to_provision
        targets = alt.targets or []
        if provision is None or not targets:
            continue
        slice_ = _targets_on(targets, on_date) or targets[-1]
        url = _provision_url(provision, slice_, code_name)
        if url is None:
            continue
        out.append({
            "provision_id": provision.provision_id,
            "division": provision.division,
            "url": url,
            "title": _window_title(slice_),
            "provision_pk": provision.pk,
            "version": slice_["version"],
        })
    return out


def in_container(
    records: Iterable[ProvisionCrossReference],
    container: str,
    table_id: str = "",
) -> list[ProvisionCrossReference]:
    """The records whose spans index the named emitted string.

    A version body, a table's html, and that table's notes are three separately
    emitted strings; a record's offsets index exactly one of them.
    """
    return [
        r for r in records
        if r.container == container and (not table_id or r.table_id == table_id)
    ]


def annotate_tables(
    tables: Iterable[ProvisionVersionTable],
    records: Iterable[ProvisionCrossReference],
    code_name: str,
    *,
    on_date: date | None = None,
    fan_out: bool = False,
) -> None:
    """Attach ``linked_html`` / ``linked_notes`` to each table, in place."""
    rows = list(records)
    for table in tables:
        table.linked_html = linkify(
            table.html,
            in_container(
                rows, ProvisionCrossReference.Container.TABLE, table.table_id
            ),
            code_name, on_date=on_date, fan_out=fan_out,
        )
        table.linked_notes = linkify(
            table.notes,
            in_container(
                rows, ProvisionCrossReference.Container.NOTE, table.table_id
            ),
            code_name, on_date=on_date, fan_out=fan_out,
        )


def annotate_versions(
    versions: Sequence[CodeEditionProvisionVersion],
    code_name: str,
    *,
    on_date: date | None = None,
    fan_out: bool = False,
) -> None:
    """Attach ``linked_html`` and ``cross_ref_cites`` to each version (and
    ``linked_html`` / ``linked_notes`` to its tables), in place.

    One query for the whole page.  The search path doesn't use this — it warms
    ``cross_references__to_provision`` in the result prefetch instead (see
    ``search.engine.orchestration``) and formats from that cache.
    """
    if not versions:
        return
    records = (
        ProvisionCrossReference.objects
        .filter(from_version__in=versions)
        .select_related("to_provision")
        .prefetch_related("alternates__to_provision")
    )
    by_version: dict[int, list[ProvisionCrossReference]] = {}
    for record in records:
        by_version.setdefault(record.from_version_id, []).append(record)

    for version in versions:
        rows = by_version.get(version.pk, [])
        version.linked_html = linkify(
            version.html,
            in_container(rows, ProvisionCrossReference.Container.BODY),
            code_name, on_date=on_date, fan_out=fan_out,
        )
        version.cross_ref_cites = cites(
            rows, code_name, on_date=on_date,
        )
        annotate_tables(
            version.tables.all(), rows, code_name,
            on_date=on_date, fan_out=fan_out,
        )


def cited_by(
    version: CodeEditionProvisionVersion,
    provision: CodeEditionProvision,
    code_name: str,
) -> list[dict[str, Any]]:
    """Provision versions citing ``provision`` whose window overlaps ``version``.

    The fan-in is the half of this data the printed code and e-Laws do not
    carry: 947 distinct provisions are cited somewhere in OBC 2006.  Restricted
    to citing versions in force alongside the one on screen, so the panel
    answers "who pointed here *then*", not "ever".

    One query; deduplicated per citing provision-version.
    """
    records = (
        ProvisionCrossReference.objects
        .filter(to_provision=provision)
        .select_related("from_version__provision")
    )
    return _cited_by_rows(records, version, code_name)


def cited_by_map(
    versions: Sequence[CodeEditionProvisionVersion],
) -> dict[int, list[dict[str, Any]]]:
    """:func:`cited_by` for a whole result set — one query, keyed by version pk.

    The search page shows many provisions at once, so the fan-in is fetched in
    a single ``to_provision__in`` query rather than per result.  Each version's
    rows are still filtered to the citing versions in force alongside *it*.
    """
    if not versions:
        return {}
    by_provision: dict[int, list[ProvisionCrossReference]] = {}
    records = (
        ProvisionCrossReference.objects
        .filter(to_provision_id__in={v.provision_id for v in versions})
        .select_related("from_version__provision")
    )
    for record in records:
        by_provision.setdefault(record.to_provision_id or 0, []).append(record)

    return {
        version.pk: _cited_by_rows(
            by_provision.get(version.provision_id, []),
            version,
            version.provision.edition.code_name,
        )
        for version in versions
    }


def _cited_by_rows(
    records: Iterable[ProvisionCrossReference],
    version: CodeEditionProvisionVersion,
    code_name: str,
) -> list[dict[str, Any]]:
    rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        citing = record.from_version
        if not citing.overlaps(version):
            continue
        key = (
            citing.provision.division,
            natural_provision_key(citing.provision.provision_id),
            citing.version,
        )
        if key in rows:
            continue
        rows[key] = {
            "provision_id": citing.provision.provision_id,
            "division": citing.provision.division,
            "version": citing.version,
            "version_label": f"v{citing.version}",
            "title": f"cites “{record.surface_text}”",
            # The citing provision is a *different* provision, so its title
            # belongs in the link text — see tasks/c-lineage-anchor-text.md.
            # Free here: ``from_version`` is already selected.
            "provision_title": citing.title,
            "surface_text": record.surface_text,
            "url": provision_permalink_url(
                code_name,
                citing.provision.division,
                citing.provision.provision_id,
                citing.version,
            ),
        }
    return [rows[key] for key in sorted(rows)]
