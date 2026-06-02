# impl — Display Migration: Wire `CodeEditionProvisionVersion` into the UI

**Status: READY FOR IMPLEMENTATION** — 2026-05-27.
**Supersedes the implementation plan in:** [`3-code-paths.md`](3-code-paths.md).
**Consumes the visual spec from:** [`4-display.md`](4-display.md) (still
authoritative for layout, typography, motion, color).
**Depends on:** [`impl-load-edition-gaps.md`](impl-load-edition-gaps.md)
applied — provenance tables populated by `load_edition` for at least
OBC 1997 / 2006 / 2012.
**Unblocks:** [`5-cleanup.md`](5-cleanup.md) — the old
`load_maps` / `CodeMap` / `CodeMapNode` / `KeywordIDF` stack can only
die after this lands.

## Why this card exists

`impl-load-edition-gaps` populated the provenance warehouse
(`Regulation`, `RegulationClause`, `RegulationAsset`,
`CodeEditionProvision`, `CodeEditionProvisionVersion`,
`CodeEditionProvisionVersionClause`, `ProvisionVersionTable`,
`ProvisionMapping`) but the user-facing surface still reads from the
old map abstraction (`CodeMapNode`) via `core/views/search.py`,
`templates/partials/_viewer_section_content.html`, and the search
result chain.  Until those swap over, the work is invisible.

The contract decisions already baked into the data layer constrain
this card and **must not be revisited** here:

- **Version HTML renders verbatim** via `{{ version.html|safe }}` — no
  sanitiser, no filter, no transformation.  See
  [[feedback-no-html-sanitisation]].
- **Version-level `action` is gone**; kind-of-change is derived from
  `version.contributing_clauses` (M2M, ordered by `apply_order`).  See
  [[drop-version-action]].
- **Image references resolve at the URL layer** (`ASSET_ROOT` mounted at
  host root in dev; nginx alias in prod).  Templates use the paths
  verbatim from `version.page_images[].image` and
  `table.images[].image`; no rewriting at render time.
- **`transition_provision_ref` is an FK now** (`version.transition_provision`
  is a `CodeEditionProvisionVersion`); no JSON unpacking at render time.

## In scope

### 1. `config/code_metadata.get_applicable_codes()`

Audit the current implementation against the new schema.  It already
queries `CodeEdition` directly per the comment in `CLAUDE.md`, but
verify:

- Uses `effective_date <= search_date AND (ineffective_date IS NULL OR
  ineffective_date > search_date)`.
- Joins `ProvinceCode` for the province and `Code.is_national = True`
  for national codes.
- Prefetches `regulations` so the formatter's provenance line doesn't
  N+1 on the regulation chain.

If it's already correct, this step is a no-op verification.

### 2. Retire `config/transitions.py` reads

The file still exists and is the source for `_populate_provision_transitions()`
in `load_maps.py`.  Audit consumers:

```bash
grep -rn "from config.transitions\|config\.transitions\|load_transitions" --include="*.py"
```

Every consumer's question — *"is there a transition active for this
provision at this date?"* — is now answered by:

```python
active_versions = CodeEditionProvisionVersion.objects.filter(
    provision=provision,
    effective_date__lte=query_date,
).filter(
    Q(ineffective_date__isnull=True) | Q(ineffective_date__gt=query_date)
)
# count > 1 → transition active.  The version whose
# transition_provision FK is set carries the applicability pointer.
```

Replace each call site with the version query.  Don't delete
`config/transitions.py` itself in this card — that's
[`5-cleanup.md`](5-cleanup.md)'s job once `load_maps.py` is gone.  Just
stop reading from it.

### 3. `core/views/search.py` — viewer section content

The viewer's "what's in this section" panel (`viewer_section_content`,
line ~243-260) currently queries `CodeMapNode` by `(map_code, node_id)`.
Rewrite to query `CodeEditionProvisionVersion`:

```python
# request carries: code (e.g. "OBC"), edition_id (e.g. "1997"),
# division, provision_id, query_date (default: today)
versions = CodeEditionProvisionVersion.objects.filter(
    provision__edition__code__code=code,
    provision__edition__edition_id=edition_id,
    provision__division=division or "",
    provision__provision_id=provision_id,
    effective_date__lte=query_date,
).filter(
    Q(ineffective_date__isnull=True) | Q(ineffective_date__gt=query_date)
).select_related(
    "provision__edition__code",
    "transition_provision__provision",
).prefetch_related(
    "tables",
    "contributing_clauses__regulation",
    "provision__appendix_entries__versions",
).order_by("-effective_date")
```

The returned context dict shape (consumed by
`_viewer_section_content.html`):

```python
{
    "active_versions": list[version],   # 1 normally, 2 during transition
    "appendix_versions": list[version], # active versions of appendix_entries
    "active_node_id": provision_id,
    "transition_active": len(active_versions) > 1,
}
```

The URL parameters need to change too — `node_id` + `map_code` become
`code` + `edition_id` + `division` + `provision_id`.  Update
`core/urls.py` (`viewer/section-content/`), `core/views/search.py`,
and every caller (search results, viewer edition-nav, history links).

`map_code` is *gone* as a URL parameter.  Internal-detail leakage
per [[feedback-no-internal-url-params]] — the public URL should carry
edition identity (`code`, `edition_id`), not the CCM map artefact
name.

### 4. `core/views/search.py` — viewer edition nav & dates

Same translation: `viewer_edition_nav` (line ~270+) currently walks the
`CodeMapNode.parent_id` tree per `map_code`.  Rewrite to walk
`CodeEditionProvision.parent` per `(edition, division)`.  Active
provisions for navigation come from "any version is in force at
`query_date`" — same active-versions filter as step 3.

`viewer_edition_dates` (effective-date dropdown) queries distinct
`Regulation.effective_date` per edition; this is unchanged in spirit
but should now use the `Regulation` model rather than reading from
`config/transitions.py` or `CodeEdition.amendments` JSON.

### 5. `api/search/orchestration.py` — already partially migrated

`impl-load-edition-gaps` already swapped:
- `select_related("clause__regulation")` →
  `prefetch_related("contributing_clauses__regulation")`
- `mapping.introduced_by_version.clause` →
  `mapping.introduced_by_version.contributing_clauses.filter(action=RENUMBER).first()`

Remaining work in this card:

- **Active version selection per provision** (the contract-defined
  filter from step 3) — currently the orchestration already filters by
  `effective_date` / `ineffective_date`, but verify it handles the
  zero-width window case correctly (a version with
  `ineffective_date == effective_date` is the "as-filed but superseded
  same day" emission; consumers that only want in-force windows filter
  it out — see contract §"`versions[].effective_date` /
  `ineffective_date`").
- **Next-version-not-in-force lookup** — for the "Next amendment" line
  in the provenance header.  Add a prefetch:
  ```python
  Prefetch(
      "provision__versions",
      queryset=CodeEditionProvisionVersion.objects
          .filter(effective_date__gt=query_date)
          .order_by("effective_date")[:1],
      to_attr="next_versions",
  )
  ```
- **Appendix prefetch** — same active-versions pattern applied to
  `provision__appendix_entries__versions`.

### 6. `api/formatters.py` — provenance context for templates

Format active version + provenance into the dict shape expected by the
new templates (per [`4-display.md`](4-display.md)):

```python
{
    "version": active_version,
    "provision": active_version.provision,
    "code_edition": active_version.provision.edition.code_name,
    "title": active_version.title,
    "html_content": active_version.html,     # rendered |safe verbatim
    "page_images": active_version.page_images or [],
    "tables": list(active_version.tables.all()),
    "contributing_clauses": list(
        active_version.contributing_clauses.all()
    ),
    "most_recent_clause": (
        active_version.contributing_clauses.all().last()
    ),
    "next_version": (
        active_version.provision.next_versions[0]
        if getattr(active_version.provision, "next_versions", None)
        else None
    ),
    "is_base": active_version.version == 0,
    "regulation_chain": list(
        active_version.provision.edition.regulations.all()
    ),
    "transition_provision_version": active_version.transition_provision,
    "appendix_entries": [...],  # active versions of appendix_entries
}
```

The `"clause"` key that templates currently consume (`result.clause`)
is satisfied by `most_recent_clause`; keep the name `clause` in the
template context dict for compatibility with existing partials, then
do a follow-up renaming pass if desired.

The copy-button reference string (per [`4-display.md`](4-display.md)
§"Copy Button"):

```
OBC 1997, Div B, S 3.1.4.7. -- Fire Separations
In force: 1998-04-06 (O. Reg. 403/97)
Amended by: O. Reg. 22/98, cl. 1.(1) (1998-04-06)
Next amendment: O. Reg. 152/99 (1999-04-01) -- not in force at query date
```

Build it in the formatter (server-side) and pass as `result.copy_text`
— avoids JS having to know provenance shape.

### 7. Templates — verbatim HTML rendering

[`4-display.md`](4-display.md) is the visual spec; this section is just
the concrete file list and a few load-bearing implementation rules.

**Render rules — non-negotiable:**

- `{{ version.html|safe }}` — never `|bleach`, never a filter that
  rewrites, never a sanitiser.  e-Laws is the trust boundary; CCM is
  the producer-side contract.  See [[feedback-no-html-sanitisation]].
- `{{ table.html|safe }}` when populated; else iterate
  `table.images` and render each with the document-image partial.
- `{{ table.notes }}` rendered only when `table.html == ""`
  (contract: e-Laws-form tables embed notes in HTML, image-form tables
  carry notes separately).
- Inline `<img src="/laws/images/...">` in version HTML resolves
  through the URL-layer mount.  No template-side path mangling.
- `version.page_images[].image` and `table.images[].image` are
  served at host root with the same path layout CCM emitted (e.g.
  `/documents/obc_1997_v3.pdf/143.webp`).  No template-side prefix.

**New templates** (per [`4-display.md`](4-display.md) §Files):

- [ ] `templates/provenance/_provenance_header.html` — provision ID,
      title, in-force date, most recent amending clause, expandable
      amendment chain, next-amendment line, copy button.  Reads
      `version`, `most_recent_clause`, `regulation_chain`,
      `next_version`, `copy_text` from context.
- [ ] `templates/provenance/_provision_content.html` — page images
      (when `version.page_images` non-empty) OR `{{ version.html|safe }}`
      (when HTML present).  Includes table partials.
- [ ] `templates/provenance/_table.html` — table caption, HTML or
      images, notes (suppressed when HTML embeds them).
- [ ] `templates/provenance/_transition_view.html` — block-quote
      header from `version.transition_provision.html`, stacked active
      versions with one open / one collapsed.
- [ ] `templates/provenance/_appendix_notes.html` — collapsible list,
      `(See Note A-X.X.X.X.(N))` anchor targets (the existing
      `_linkify_appendix_refs()` in `api/formatters.py` stays as-is —
      it operates on raw HTML and the anchor IDs match this partial).
- [ ] `templates/regulation/detail.html` — clause browsing per
      regulation; uses `RegulationClause.action` (clause-level!), the
      `clause_text` field rendered `|safe` (also trusted e-Laws), and
      `regulation.assets` for inline asset bytes.
- [ ] `templates/regulation/chain.html` — edition regulation chain
      timeline.  Reads `edition.regulations.all().order_by("effective_date",
      "filed_date")`.

**Modified templates:**

- [ ] `templates/partials/_viewer_section_content.html` — replace the
      `CodeMapNode` loop with a `CodeEditionProvisionVersion` loop.
      Variable rename: `section` → `version`.  The transition case
      (two active versions) renders the `_transition_view.html`
      partial.
- [ ] `templates/partials/search_results_partial.html` — provenance
      banner uses `_provenance_header.html`; result body uses
      `_provision_content.html`.
- [ ] `templates/partials/_result_document_block.html` — page-image
      vs HTML branch.  Already calls `{{ table.html|safe }}`, fine.
- [ ] `templates/partials/_provenance_banner.html` — read
      `result.contributing_clauses` (list) and render the *list*, not
      just `result.clause`.  Most-recent-clause is at index `-1`.
      Earlier clauses collapse behind an "N earlier amendments" Alpine
      toggle.
- [ ] `templates/partials/_viewer_edition_nav.html` /
      `_viewer_edition_dates.html` — adjust for the new URL parameter
      shape (`code`/`edition_id`/`division`/`provision_id`).

### 8. CSS / static

- [ ] Wire the existing `static/css/elaws.css` into the base layout
      (`templates/base.html` or wherever the head block lives) via
      `<link rel="stylesheet" href="{% static 'css/elaws.css' %}">`.
- [ ] Add Literata + JetBrains Mono via Google Fonts (per
      [`4-display.md`](4-display.md) §Typography).  CDN link in the
      head; Tailwind utility classes (`font-serif` /
      `font-mono`) map to them via `tailwind.config.js` (if there is
      one — current CSS is CDN-Tailwind, so add a `<style>` block with
      `@layer base { :root { ... } }` or use inline class names like
      `font-[Literata]`).
- [ ] Provenance spine styling: `border-l-2 border-primary-400` for
      base versions, `border-l-2 border-amended` for amended.  Add the
      `amended` color to the Tailwind palette (brick/terracotta hex —
      pick one in implementation, document in the CSS).
- [ ] Action type pill colors per
      [`4-display.md`](4-display.md) §"Action type pills".

### 9. JavaScript

- [ ] Copy button: vanilla `navigator.clipboard.writeText(text)` where
      `text` comes from a `data-copy-text` attribute populated by the
      server-side `copy_text`.  No client-side provenance reconstruction.
- [ ] Amendment chain expand/collapse: Alpine.js `x-data`.
- [ ] Transition accordion: Alpine.js `x-data`.
- [ ] Appendix notes expand: Alpine.js, fires `expand-appendix` event
      that the existing `_linkify_appendix_refs()`-generated anchors
      dispatch on.

### 10. URL routing

`core/urls.py`:

- [ ] Update `viewer/section-content/` to consume `code` +
      `edition_id` + `division` + `provision_id` instead of `map_code`
      + `node_id`.  Backwards-compat redirect from the old shape is
      *not* needed — the old URLs are internal HTMX endpoints, no
      external bookmarks.
- [ ] Same for `viewer/edition-nav/` and `viewer/edition-dates/`.
- [ ] `regulation/<int:pk>/` view exists; verify it now reads
      `Regulation` (the new model), not the old amendments JSON on
      `CodeEdition`.
- [ ] Add `edition/<int:pk>/chain/` view if not present (per
      [`4-display.md`](4-display.md) §"Edition Regulation Chain View").

### 11. Tests

- [ ] `core/tests/test_views_search.py` (new or updated) — viewer
      `section_content` returns one version for a normal date, two for
      a transition date, includes appendix versions.
- [ ] `api/tests/test_search_provenance.py` (new) — search result
      formatter exposes `most_recent_clause`, `contributing_clauses`,
      `next_version`, `transition_provision_version`, and
      `copy_text` in the expected shapes.
- [ ] `api/tests/test_search_transitions.py` — same-edition transition
      (two active versions) and cross-edition transition (`ProvisionMapping`
      pair).
- [ ] `core/tests/test_templates.py` — golden-render test that takes a
      known provision version and asserts the rendered HTML contains
      the verbatim `version.html` substring (proves we didn't
      accidentally bleach it).  Cheap regression guard against future
      sanitiser additions.

### 12. Manual verification (visual)

- [ ] Search for "fire safety" → results render with provenance
      header, page images for OBC 1997 base, e-Laws HTML for OBC 2012
      amended.
- [ ] OBC 2012 provision known to have an inline equation (per
      `inline-html-image-assets.md`) renders the `<img>` against a real
      file under `ASSET_ROOT/laws/images/...`.
- [ ] Click a regulation citation in the provenance header → lands on
      `regulation/<pk>/` clause-browsing view.
- [ ] Edition chain page shows a vertical timeline with completeness
      badge for OBC 1997.
- [ ] A query date that falls in a transition period (e.g. 2014-12-15
      with OBC 2006 → 2012 overlap) renders the transition block-quote
      header with both versions stacked.
- [ ] Copy button puts the reference string on the clipboard.

## Out of scope (separate cards)

- **Killing `load_maps.py` / `CodeMap` / `CodeMapNode` /
  `KeywordIDF`** — [`5-cleanup.md`](5-cleanup.md).  Cannot start until
  every consumer in this card is migrated.
- **NBC editions** — Ontario-first per
  [[project-provenance-design]].
- **Search ranking refinements** (TF-IDF tuning against the new
  schema).  Existing TF-IDF code already works against
  `CodeEditionProvisionVersion`; rerank quality is a separate concern.
- **Mobile-specific work** — [`4-display.md`](4-display.md) §Mobile
  asserts the single-column layout is responsive without changes.

## Sequencing — pickup order for implementation

A reasonable pickup order that keeps the app working at each step:

1. Steps 1–2 (audit `get_applicable_codes`, retire `config.transitions`
   reads).  No template changes; pure backend swap.
2. Steps 5–6 (orchestration prefetches + formatter context).  Still
   reading old templates; the new context keys are additive.
3. Step 8 (CSS / static linking).  Visual no-op until templates use it.
4. Step 7 (new partials), wired one at a time:
   - `_provenance_header.html` first (consumed by search results).
   - `_provision_content.html` next.
   - `_table.html` last (only affects the inner table rendering).
5. Step 7 (modified partials) — flip `_viewer_section_content.html`
   and `search_results_partial.html` to use the new partials.
6. Steps 3–4 (viewer views), then step 10 (URL routing).  This is the
   breaking-change step; do it after the search-results path is
   already on the new shape.
7. New views: `_transition_view.html`, `_appendix_notes.html`,
   `regulation/detail.html`, `regulation/chain.html`.
8. Step 9 (JavaScript).  Pure additive; can land any time after step 6.
9. Step 11 (tests).  Some tests can be written ahead of the code
   they're validating; others (golden-render) want the templates to
   exist first.
10. Step 12 (manual visual verification).

## File touchpoints — quick reference

| File | Verb | Notes |
|---|---|---|
| `config/code_metadata.py` | audit | Verify `get_applicable_codes()` is on the new schema. |
| `config/transitions.py` | retire reads | Don't delete; just stop calling. |
| `core/views/search.py` | rewrite | `viewer_section_content`, `viewer_edition_nav`, `viewer_edition_dates`. |
| `core/views/regulation.py` | verify | `regulation_detail` reads `Regulation` (the new model). |
| `core/urls.py` | update | URL parameter shape change. |
| `api/search/orchestration.py` | extend | Active version filter, next-version prefetch, appendix prefetch. |
| `api/formatters.py` | extend | Build provenance context dict + `copy_text`. |
| `templates/provenance/*` | new | 5 partials per §7. |
| `templates/regulation/*` | new | 2 templates per §7. |
| `templates/partials/_viewer_section_content.html` | rewrite | Loop over versions, not nodes. |
| `templates/partials/search_results_partial.html` | rewrite | Use new provenance partials. |
| `templates/partials/_provenance_banner.html` | rewrite | Render `contributing_clauses` list. |
| `templates/partials/_viewer_edition_nav.html` | rewrite | New URL parameters. |
| `templates/partials/_viewer_edition_dates.html` | rewrite | Read from `Regulation`. |
| `templates/base.html` (or head block) | extend | `<link>` for `elaws.css`, Literata + JetBrains Mono. |
| `static/css/elaws.css` | wire up | Already exists; needs to be linked from base. |
| `static/js/*` | add | Copy button + Alpine snippets. |
| `core/tests/test_views_search.py` | new | Viewer section content tests. |
| `api/tests/test_search_provenance.py` | new | Formatter shape tests. |
| `api/tests/test_search_transitions.py` | new | Transition detection. |
| `core/tests/test_templates.py` | new | Golden-render regression guard. |

## Acceptance

- Every read of `CodeMapNode` / `CodeMap` outside of `load_maps.py`,
  `check_data_integrity.py`, and migrations is gone.  `grep -rn
  "CodeMapNode" --include="*.py"` returns only those three call sites.
- `pytest` passes including the new test files.
- Manual checks (§12) all pass.
- `load_maps.py` and its support tables are unused (verified via
  ripgrep); [`5-cleanup.md`](5-cleanup.md) is unblocked.

## Open questions

- **Font hosting** — Google Fonts CDN vs. self-hosted vs. Bunny Fonts?
  Resolve at implementation time; CDN is fastest to ship, self-hosted
  is best for privacy.  Doesn't affect any other step.
- **Variable rename `section` → `version`** in `_viewer_section_content.html`
  is a touchpoint for every other partial that includes it.  Worth
  doing as a single search/replace pass once all callers are
  identified; don't drag it across multiple commits.
- **Backwards-compat URL shims** for `viewer/section-content/` —
  declared not needed in §10 because it's HTMX-internal.  If telemetry
  ever shows external links to it, revisit.
