# Within-edition cross-references — inline citation links + a "Cited by" panel

CCM now ships a top-level `cross_references[]` array on every consolidated OBC
edition (CCM `e77daa68`, contract §"Top-level: `cross_references[]` — resolved
internal citations", marked *CC adoption pending*). Each record is one citation
in a provision's body, **resolved to the specific target version(s) in force
while the citing version stood**:

```json
{"from_provision_id":"3.2.2.10.","from_division":"B","from_version":0,
 "surface_text":"Subsection 3.2.5.","to_provision_id":"3.2.5.","to_division":"B",
 "targets":[{"version":0,"effective_date":"2006-12-31","ineffective_date":"2010-01-01"}],
 "note":""}
```

Adopt it for two distinct payoffs:

1. **Inline links** — "Subsection 3.2.5." in the body becomes a link to
   3.2.5. *as it read then*, on the search result and the permalink page.
2. **A "Cited by" panel** — the fan-in (947 distinct cited provisions in OBC
   2006) is information the printed code and e-Laws do not carry, and it works
   on every surface regardless of render mode, including the image-only
   versions where inline linking is impossible.

## What the shipped data supports (measured, 2026-07-23)

Probed against `data/outputs/OBC_{1997,2006,2012}.json`:

| | 1997 | 2006 | 2012 |
|---|---|---|---|
| records | 2,609 | 3,253 | 5,592 |
| citing versions carrying refs | 1,099 / 3,382 | 1,259 / 3,574 | 1,779 / 4,409 |
| distinct cited provisions (fan-in) | 845 | 947 | 1,077 |
| multi-target (needs a date to choose) | 323 (12%) | 627 (19%) | **2,174 (39%)** |
| curator `note` / no-link records | 9 / 2 | 5 / 1 | 0 / 0 |

Anchoring — can `surface_text` be located in the version's stored `html`?

- **~99% verbatim.** 2,587 / 3,253 (2006) are one record ↔ one occurrence.
- **~8%** are n records ↔ n occurrences → nth-occurrence anchoring.
- **24 apparently-ambiguous cases (2006)** are all *nesting*: `Sentence
  3.7.4.3.(5)` and `Sentence 3.7.4.3.` cited in the same version. Longest-first
  matching with span masking resolves every one.
- **Zero matches land inside a tag or attribute** — citations live in text
  nodes.
- **Misses**: 150 (1997), 0 (2006), 4 (2012) records whose surface text is not
  literally present, all one cause — the citation straddles a block boundary
  (`…in Section</p><p>9.41. and Part 11…`) because CCM matched on normalised
  text. 125 of the 1997 misses sit on versions that render as page images
  anyway. Same cause produces 18 (1997) / 2 (2012) records that *exceed* the
  literal occurrence count, always with an identical target.
- **No table-only citations in any edition** (36/24/46 records' surface text
  appears in both body and a table; **0** in a table alone). Records carry no
  container field, so a citation printed inside a table cell is not
  addressable — see the paired CCM card.

## Fix shape

### 1. Model + loader

`ProvisionCrossReference`:

- `from_version` → FK `CodeEditionProvisionVersion` (`related_name="cross_references"`)
- `to_provision` → FK `CodeEditionProvision`, **nullable** (a no-link
  correction has no target)
- `surface_text`, `note` (both verbatim from CCM)
- `targets` JSONField — the shipped slices, stored as received
- `occurrence` PositiveSmallIntegerField — **0-based index of which occurrence
  of `surface_text` in the version's html this record anchors to**, derived at
  load (below)
- `order` — emission order, so a stable render order exists

Loaded in `load_edition` from `data["cross_references"]`, alongside
`_load_provision_mappings` (`core/management/commands/load_edition.py:201`) —
same top-level-array shape, same transaction.

**Do not re-derive `targets`.** CCM resolved the timeline slice at assembly
with the whole edition in hand; `_overlaps()` (`core/views/regulation.py:235`)
computes the same thing for nav, and a second derivation is exactly the
divergence the transition `pair_key` rule exists to prevent. Store and trust.

**Anchoring is derived once, at load.** Group a version's records by
`surface_text`, match longest-surface-first over the html text nodes with
already-consumed spans masked, and record the resulting `occurrence` per
record. A record whose surface text cannot be located gets `occurrence = None`
and is skipped by the inline renderer — it still counts for "Cited by". Log the
count; today it should be 150/0/4, so a jump means the producer changed.
Records that duplicate (same surface, same target, more records than
occurrences) collapse to the occurrences available — do not invent anchors.

### 2. Inline rendering

One shared helper (`core/cross_refs.py`) that takes a version, its html, and a
per-surface href policy, and splices anchors in. Reuse the tag-split machinery
`highlight_terms` already uses (`api/formatters.py:84`) so tags and attributes
are never touched — the measurement above says all citations are in text nodes,
and this keeps it true by construction.

**Ordering matters: linkify cross-refs *before* `highlight_terms`.** Highlight
inserts `<mark>` mid-text and would split a surface string; run the other way
and highlighting simply treats the anchor's inner text as another text node.
Cross-ref linkification also composes with `_linkify_appendix_refs`
(`api/formatters.py:47`), which handles a disjoint pattern.

Href policy per surface:

- **Search results** — the target version **in force on the query date**.
  Because `targets` is clipped to the citing version's window, and the result's
  version is itself the one in force on that date, some slice always covers it;
  assert that invariant in a test. With no query date, use the last slice.
- **Permalink page** — the multi-version-neighbour presentation the page
  already uses (`_related_links` → `templates/regulation/_permalink_nav_item.html`):
  one target version → link the surface text itself, with the in-force window
  in the `title`; several → link the surface text to the first slice and follow
  it with one `v1` `v2` chip per further slice, each with its own window
  tooltip. A reader who has already seen this in the hierarchy nav reads it the
  same way inline.

A **no-link** record (`to_provision` null) renders the surface text plain with
the curator `note` as its tooltip — the citation is disclosed, not silently
dropped. A record with a `note` *and* a target renders as a normal link plus
the note (the printed id differs from where it points; say so).

### 3. "Cited by" panel

Built from the reverse FK — for the provision on screen, the versions that cite
it, restricted to citing versions whose window overlaps the one being viewed.
Renders as a collapsed disclosure below the body, on both the permalink page
and the expanded search result, and — crucially — **independently of whether
the body rendered as html or as page images**. OBC 1997 base v0 is scans
(`project_table_image_html_precedence`), so this is the only cross-reference
affordance those versions get.

Same treatment for outbound: an image-rendered version gets a "Cites" list
instead of inline links, from the same records.

### 4. Gating

Nothing to do. References are within-edition, so a cited provision is exactly
as locked as the page citing it (`core/access.py`). Note it in the tests so
nobody adds a redundant check.

## Tests

- Loader: records land with correct FKs; a no-link record stores
  `to_provision=None` with its note; `targets` round-trips verbatim.
- Anchoring: nested surfaces (`Sentence 3.7.4.3.(5)` vs `Sentence 3.7.4.3.` in
  OBC 2006 `A|1.4.1.2.` v5) each anchor to their own occurrence, longest first.
- Anchoring: an unlocatable surface text yields `occurrence=None` and renders
  as plain text, no exception.
- Render: linkified html is unchanged inside tags/attributes; cross-ref +
  highlight composition preserves both (`<mark>` inside `<a>`, anchors intact).
- Search: multi-target ref links the slice in force on the query date; a query
  date at a slice boundary picks the half-open-correct one.
- Permalink: single-target links the surface text; multi-target renders chips
  matching `_permalink_nav_item.html` semantics.
- Cited-by: window overlap filters correctly, including a zero-duration citing
  version (`never_in_force`) — reuse `_overlaps` for the *citing*-side filter;
  that one is ours to derive, unlike `targets`.

## Out of scope

- Citations inside tables and table notes. Not addressable from this payload
  (no container field, no table-only records) — the paired CCM card asks for
  it. When it lands, the table surface gets the same treatment.
- Cross-*edition* references. `cross_references[]` is within-edition by
  construction; cross-edition continuity is `ProvisionMapping`'s job.
- Re-deriving or "repairing" a `targets` slice locally.

Paired producer card: `CodeChronicleMapping/tasks/cross-ref-consumer-gaps.md`.

## Landed (2026-07-23)

Implemented as specced above.

- `ProvisionCrossReference` (migration `0041`) + `_load_cross_references`
  in `load_edition`; `targets` stored verbatim, `occurrence` derived at load.
- `core/cross_refs.py`: `locate_surfaces` (the one anchoring implementation,
  run at load and at render so the two can't disagree), `assign_occurrences`,
  `target_on`, `linkify`, `cites`, `cited_by` / `cited_by_map`,
  `annotate_versions`.
- Search: `cross_references__to_provision` prefetch, linkification in
  `_format_single_result` (before `highlight_terms`), batched fan-in via
  `_attach_cited_by`. Permalink: `annotate_versions(fan_out=True)` + a
  "Cited by" panel. `.cross-ref*` component classes in `base.html`.
- Shared helpers hoisted out of the view layer: `natural_provision_key` and
  `CodeEditionProvisionVersion.overlaps` now live on the models module;
  `views.regulation._natural_key` / `_overlaps` delegate.
- 29 tests (`core/tests/test_cross_refs.py`, `TestCrossReferences` in
  `test_load_edition.py`); ruff / mypy / pyright clean.

**Correction to the anchoring figures above.** Running the real loader path
over the shipped payloads gives **176 of 11,454 records (1.5%) unanchored**
— 170 / 0 / 6 for 1997 / 2006 / 2012 — not the 154 estimated from a raw
substring scan. The extra ~20 are the surplus-record cases (more records
than literal occurrences) landing in the same bucket, which is correct
behaviour: a record with no occurrence left to claim must not anchor onto
another citation's text. No version anywhere in the corpus produced
colliding anchors, and the nesting-heavy witness (OBC 2006 `A|1.4.1.2.` v5,
23 citations including both `Sentence 3.7.4.3.` forms) anchors all 23 with
its markup intact.

## Revision: producer spans (settled 2026-07-23, same day)

CCM's reply retired the `occurrence` design before it shipped. The producer
can map normalised-text detections back to the emitted html for free, so each
record now carries `container: "body" | "table" | "note"`, `table_id`, and
`start` / `end` offsets into that container's string. The consumer's whole
"derive anchoring at load" section collapses to slice-and-wrap; nesting,
duplicates, straddlers, and the five external-collision cases all dissolve,
because a span is the detector's own classification rather than a guess at
which occurrence it meant.

Implemented on top of the above, same session:

- `container` / `table_id` / `start` / `end` on the model (migration `0043`),
  read by the loader and preferred by `linkify` over any derived occurrence.
- **Split anchoring** (`_span_runs`): a span containing markup — the
  block-straddling citations — links as one anchor per text run, with the
  fan-out chips attached once, to the last run. Wrapping the whole slice in a
  single `<a>` would nest a block element inside an inline one.
- **Table and note containers wired end to end**: `annotate_tables` sets
  `linked_html` / `linked_notes`, rendered by `provenance/_table.html` and the
  search result block. The records don't exist yet (CCM scans body text only
  today), so this path is ready-but-unexercised by real data; it is covered by
  tests using synthetic spans.
- The occurrence path stays as the **pre-span fallback**, documented as lossy,
  so the payloads already on disk still link. It retires when the three
  editions rebuild.

**Contract doc updated** — `tasks/complete/provenance/ccm-output-contract.md`
§`cross_references[]` is authoritative for this shape (container/table_id/
start/end, spans may contain markup, offsets index the named container's
verbatim string).

**Still out of scope:** nothing on the CC side. The remaining work is
producer-side (scan `table.html` / `table.notes`, emit spans, rebuild the
three editions) — `CodeChronicleMapping/tasks/cross-ref-consumer-gaps.md`.

## Revision: `alternates[]` — printed vs. intended (settled 2026-07-28)

CCM changed `to_provision_id` to mean **what the Code printed** (was: the
curator's silent correction) and moved the corrected reading into a new,
omitted-when-empty `alternates[]` on each record. Required adoption — ignoring
it silently mis-links ~150 records to the uncorrected provision (both ids
resolve, so no gate fires). Full ask: `tasks/complete/b-cross-ref-alternates.md`.

Implemented:

- New child model `ProvisionCrossReferenceAlternate` (FK to the parent record,
  nullable FK to the target provision, `targets` JSON stored verbatim, `order`).
  Symmetric with the primary FK so the render layer reuses the same
  slice/url/date-window helpers.
- Loader resolves `ref_data.get("alternates", [])` per record and bulk-creates
  the children after the parents; skips + counts an alternate whose target
  provision is absent (`missing_alt_targets`), and logs "N cross-references
  carry a curator's intended-reading alternate".
- Render: `_alternate_chips` (inline, on both surfaces) emits a
  `.cross-ref-alt` chip per alternate — printed target stays the anchor, the
  chip's tooltip carries the version window and the record's `note`. `cites()`
  rows gain an `alternates` list; the `_cross_ref_list.html` partial renders
  them. Prefetches added on both the search (`orchestration`) and permalink
  (`annotate_versions`) paths.
- **Migration renumber.** The span-work migration described above as `0043` and
  this alternate model were **folded into a single `0041`** (CreateModel with
  container/start/end/table_id inline + the alternate CreateModel), so the whole
  cross-ref schema is one migration depending only on the last committed `0040`
  — decoupled from a parallel session's `0042`, no merge migration. `0043`/`0044`
  no longer exist.
- Reloaded all three OBC editions oldest→newest: **153 alternate rows** (29 /
  62 / 62), 0 unanchored.

Contract updated — `tasks/complete/provenance/ccm-output-contract.md`
§`cross_references[]` is authoritative for the new `to_provision_id` meaning and
the `alternates[]` shape.
