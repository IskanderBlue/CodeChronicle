# Provision lineage: predecessor/successor links via ProvisionMapping

**Status: SPEC SETTLED 2026-06-10 — ready to implement.**
Supersedes `tasks/viewer-nav-via-provision-mapping.md` (now a stub pointing
here). Spec hashed out in conversation 2026-06-10; the 2006→2012 provision
mapping is about to land, which is the trigger.

## Goal

Help users navigate a provision's history **across edition boundaries**.
Anywhere a version chain is shown (search-results provenance rail, provision
permalink page, viewer), also show the provision's predecessor(s) and
successor(s) in the adjacent editions — links labelled as the previous/next
edition's equivalent.

The point is *showing users what follows/preceded*, not a single "next
edition" teleport button. The viewer's current prev/next-edition buttons get
**replaced** by these rows, not fixed.

## Data assumptions (confirmed with Iskander)

1. **Adjacency contract**: `ProvisionMapping` rows are only ever emitted
   between *adjacent* editions (one edition to the next). No chaining or
   skip-hop handling anywhere.
2. CCM emits mapping rows **only where identity changed**
   (renumber/split/merge/replace). On a *covered* transition, absence of a
   row is a positive assertion: "same division/id continues unchanged."
   **⚠️ Empirically false (found 2026-06-11):** the real payloads emit a
   *total* mapping — identity carries arrive as `renumbered` rows whose
   endpoints share the number (2,915 of 3,128 rows in 2006→2012; all
   2,198 same-number 1997→2006 rows differ only by the ""→B division
   introduction; the contract doc's own identity-carry example blesses
   this shape).  Consequence: the resolver words same-number rows as
   continuations ("continues as/from") regardless of their
   `mapping_type` — see step 4 item (c) — and the same-id fallback was
   **removed outright** (2026-06-11, see Key rules: number equality
   proves nothing, and total emission makes the fallback redundant
   anyway).  If CCM ever switches to delta emission, the covered-no-row
   default ("discontinued") must be revisited alongside it.
3. Real-world edition history extends beyond the corpus on both ends:
   OBC's first edition was in force **1975-12-31** (varies by code); OBC 2024
   exists but is unloaded/unmapped. An edge of our data window is just an
   uncovered transition, not "nothing exists."

## The resolver

New module `core/provision_lineage.py`, batch API:

```
resolve_lineage(provisions: list[CodeEditionProvision]) -> dict[int, Lineage]
```

One query for N provisions (same batching shape as
`_merge_provision_mapping_transitions`, `api/search/orchestration.py:243`)
so search results don't go N+1. Per provision, per direction
(predecessor / successor), exactly one of four states:

| State | Condition | UI |
|---|---|---|
| **linked** | Mapping row(s) (`mapped_forward` = successors, `mapped_back` = predecessors) — rows ONLY, no same-id inference | Link(s) labelled as the prev/next edition's equivalent; same-number rows (identity carries) worded "continues as/from"; **multiple links only for split/merged** |
| **discontinued** | Covered transition, no row | No link; marker — successor side "discontinued after this edition", predecessor side "new in this edition" |
| **no data yet** | A neighbouring edition exists in reality but the transition isn't covered (today: 2012→2024, and everything before 1997) | No link; "transition not yet mapped" marker |
| **endpoint** | No neighbouring edition exists in reality | Predecessor side: "first edition"; successor side: "current edition" (or render nothing) |

Key rules:

- **No same-id fallback — links come from mapping rows ONLY** (Iskander,
  2026-06-11, superseding the original covered-transition fallback): the
  same bare number does not consistently map to the same provision across
  editions, so number equality never produces a link, covered or not.
  Workable because CCM emits a *total* mapping (every carried provision
  has a row); on a covered transition, no row = discontinued (forward) /
  new in this edition (backward), with forward dispositions refining the
  marker.  Real-data check after removal: successor tallies unchanged
  (the fallback was contributing zero links).
- **Link targets**: successor → its **v0** (birth in the new edition);
  predecessor → its **last version** (the version that handed off);
  intra-edition renumber → `introduced_by_version` (exact new-side version).
- URLs resolved in Python via `_provision_permalink_url`
  (`core/views/regulation.py:46` — already handles the empty-division route
  split for OBC 1997). Never built in the template: edition/division/id vary
  per entry.
- **Intra-edition renumbers** (`same_edition` mappings) render uniformly as
  pred/succ rows ("renumbered from 9.10.18.6., this edition") — they *are*
  predecessors/successors; no special interleaving into the chain timeline.
- **No chaining**, ever (assumption 1 makes it meaningless).

### Endpoint detection — where each boundary fact comes from

- **Successor end** (does the corpus cover present day?): derivable from
  loaded data. Newest loaded edition open-ended (still in force — the same
  distinction `CorpusCurrency.refresh` draws for "… – present" vs a closed
  span) → **endpoint**. Newest edition closed/superseded → a real successor
  exists we haven't mapped → **no data yet**.
- **Predecessor end** (is this the first edition ever?): *not* derivable
  from loaded data — needs a new seeded fact `Code.first_edition_date`
  (OBC: 1975-12-31). Earliest loaded edition == first edition → **endpoint**;
  otherwise **no data yet**. Until seeded, default to "no data yet" (the
  honest fallback).

## Coverage record

Distinguishing "discontinued" from "no data yet" requires knowing whether a
transition is covered. Nothing records this today.

- New model `EditionTransition` (old_edition FK, new_edition FK, loaded_at),
  persisted by `load_edition` from a **new CCM payload key**
  `mapping_coverage: [{"old_edition": "2006", "new_edition": "2012"}]`.
- Explicit declaration preferred over inferring from row existence (clean
  data over runtime transforms; inference conflates "not mapped yet" with
  "mapped, zero changes", and a partial/failed load silently reads as
  covered). Inference is an acceptable stopgap if the CCM contract change
  lags — note the failure modes at the site.
- Requires a CCM contract addition (update
  `tasks/complete/provenance/ccm-output-contract.md` or its successor doc;
  coordinate emission with CCM).

## Render sites — one row vocabulary, three sites

1. **Provenance rail** — `templates/partials/_provenance_rail.html`, already
   shared by the search-results right rail (`_result_rail.html`) and the
   provision permalink page (`provision_permalink.html:78`). Predecessor
   rows **above** the Base row, successor rows **below** the `next_version`
   row, visually marked as crossing the edition boundary (edition badge +
   mapping-type verb / state marker).
   **Do NOT splice entries into `amendment_chain`** — that list means
   "versions of this provision in this edition"; the template builds every
   permalink from the enclosing result's `code_edition`/`division`/`id` and
   treats `.0` as the base row. Lineage entries carry their own identity →
   separate keys `lineage_predecessors` / `lineage_successors` (or a single
   `lineage` object with both directions + states).
2. **Viewer chrome** — REPLACE the prev/next-edition buttons
   (`_build_viewer_navigation` / `_build_viewer_url_params` heuristic in
   `core/views/search.py:32-145`) with the same lineage rows. (The
   `(edition, provision_id)` + division-preference lookup initially
   survived inside the resolver as the same-id fallback; both are gone
   as of 2026-06-11 — see Key rules.)
3. **Context builders**: search path — orchestration calls the resolver once
   for the whole result set; formatter copies per-provision lineage into the
   result dict next to `amendment_chain` (`api/formatters.py:468` area).
   Permalink path — `_provenance_result` (`core/views/regulation.py:334`)
   calls the same resolver for the single matched provision.

Transition-compare cards: each pane's rail will show lineage rows pointing
at the other pane. Mildly redundant; ship it, suppress only if it reads
noisy.

### Free-tier gating (cross-cutting, landed 2026-06-10)

Lineage links are inherently cross-edition, so every rendered row must go
through `core.access.edition_allowed(user, code_name)` (the free-tier gate,
behind `FREE_TIER_GATING_ENABLED`, default off): a target edition outside
the user's scope renders as a **locked upsell link to pricing** (lock icon +
"— Pro"), never a raw link that 403s after click-through (the
`locked_edition.html` teaser on the permalink view is only the backstop).
The viewer's current prev/next-edition buttons already do exactly this
(`viewer_edition_nav` + `_viewer_edition_nav.html` locked branch) — step 3's
replacement rows must preserve that behaviour, and steps 2–3 should take the
gate as a rendering input from day one. See
`tasks/free-tier-obc2006-scope.md`.

## Implementation order

1. ✅ **DONE 2026-06-10.** Resolver + `EditionTransition` +
   `Code.first_edition_date` (+ seed for OBC), with tests — including a
   mapping whose endpoints differ in division across editions, a split
   (N successor rows), same-id fallback on a covered transition, and the
   discontinued / no-data-yet / endpoint states.
   - `core/provision_lineage.py` — `resolve_lineage(provisions) ->
     dict[pk, Lineage]`, ≤6 queries for any batch size (asserted in tests).
   - `EditionTransition` + `Code.first_edition_date` in `core/models.py`;
     migration `0030_provision_lineage` (includes OBC seed RunPython).
   - `load_edition`: ingests `mapping_coverage` → `EditionTransition`
     (warn-skip on unloaded editions); seeds `FIRST_EDITION_DATES` on every
     load (survives a codes wipe); the edition-reload wipe clears coverage
     rows touching the edition (symmetric with the mapping-row CASCADE, so
     a stale claim can't mint false "discontinued" verdicts).
   - `_provision_permalink_url` moved to `core/permalinks.py` as
     `provision_permalink_url` (resolver needs it; importing from the view
     module would be circular once step 2 lands).
   - Tests: `core/tests/test_provision_lineage.py` (18) + coverage/seed
     loader tests in `test_load_edition.py`.
1.5. ✅ **DONE 2026-06-10.** Disposition ingest — one mechanism for both
   verification findings.  No fifth state (Iskander's call).
   - `ProvisionDisposition` model (`core/models.py`): provision FK +
     new_edition FK + status (`discontinued` / `not_processed`) +
     source/reasoning; unique (provision, new_edition); migration
     `0031_provision_disposition`.
   - `load_edition._load_provision_dispositions`: ingests CCM's
     `provision_discontinuations` *and* `provision_mappings` rows whose
     `new_provision_id == "not_processed"` (those rows are skipped by the
     mapping loader — they were never mappings).  Warn-skip on unknown
     provision/edition; reload wipe: old-side rows die via the provisions
     CASCADE, rows *targeting* the reloaded edition wiped explicitly.
   - Resolver precedence: **mapping rows > dispositions > same-id
     fallback**, in both directions — a disposed provision never gets a
     forward fallback link, and is disqualified as a backward fallback
     candidate (id reuse).  `discontinued` → DISCONTINUED,
     `not_processed` → NO_DATA_YET ("not yet covered").  One extra
     batched query (now ≤7 for any batch size, asserted).
   - Tests: `TestDispositions` (4, incl. both real-data traps and the
     rows-outrank-dispositions rule) + `TestProvisionDispositions` (4
     loader tests).
   - Real-data verification (re-run `.tmp/verify_lineage.py`): the 143
     fabricated links and 36/38 false "discontinued" are gone — resolver
     discontinued now matches CCM exactly for 2006→2012 (67=67) and
     194/195 for 1997→2006.  Both traps verified: 2006 C 1.3.5.4. →
     discontinued while 2012's reused id links back to its true
     predecessor 1.3.5.5.; SB-12 rows → "not yet covered" while 2012 B
     12.3.1.2. links back to old 12.3.1.3. (the windows article).
2. ✅ **DONE 2026-06-10.** Rail rows (search results + permalink page).
   - Resolver render fields: per-link ``verb`` (direction-aware, set in
     ``_link``: renumbered to/from, split into/from, merged into/from,
     replaced by/replaces, continues as/from) and ``locked`` — stamped by
     the new ``annotate_lineage_locks(lineages, user)`` post-pass (the
     resolver stays user-agnostic).
   - Search path: ``api.formatters._attach_lineage`` — ONE batched
     resolver call per result set, on the still-flat formatted list
     *before* grouping/pairing/nesting (compare panes and nested children
     reference the same dicts, so every rail include sees the keys).
     ``format_search_results`` gained ``user=`` (None = anonymous);
     ``search_service`` passes the searcher through.
   - Permalink path: ``_provenance_result`` gained ``user``; calls the
     resolver for the matched provision and adds the same two keys
     (``lineage_predecessors`` / ``lineage_successors``); the
     ``_build_copy_text`` inline import hoisted while there (no cycle).
   - Templates: predecessor block above the Base row / successor block
     below the next-version row in ``_provenance_rail.html``, each behind
     a rule; shared ``_lineage_link_row.html`` (edition badge or "This
     edition", verb, target link with cross-division "Div. X" label only
     when it differs); locked links render the pricing upsell ("— Pro"),
     never the raw URL.
     **No version chip** (Iskander, 2026-06-11): the other edition's
     version numbering reads as this edition's — the URL still pins the
     hand-off version (pred → vmax, succ → v0), it's just not displayed.
     ``same_id`` means "target shares the bare number" (identity-carry
     row *or* fallback), and same-number ``renumbered`` rows are worded
     "continues as/from" (see step 4 item (c)).  **No "(same number)"
     suffix** (Iskander, 2026-06-11) — the continues verb carries it.
     Markers: "New in this edition — no X predecessor" /
     "Discontinued — no X successor" / "Transition from/to X not yet
     mapped" ("Earlier/Later editions not yet mapped" when the neighbour
     is beyond the corpus) / "First edition"; a successor endpoint
     (still-current edition) renders nothing.
   - Tests: ``TestRenderFields`` (verbs + gating locks, 4),
     ``TestLineageRows`` template renders (7), formatter attach test
     (incl. provision-less results get None keys), permalink view
     integration (2).  Full gate green: 308 passed, ruff/mypy/pyright 0.
   - Real-data check: ``.tmp/verify_lineage_ui.py`` renders live
     permalink pages — both traps, the SB-12 sentinel, the 1997 corpus
     edge, and the closed-2012 "Later editions not yet mapped" marker
     all render as designed.
3. ✅ **DONE 2026-06-11.** Viewer replacement; heuristic nav deleted.
   - `viewer_edition_nav` (core/views/search.py) rewritten: looks up the
     viewed provision exactly (code/division/id — no division-preference
     guessing; that tiebreak lives only inside the resolver's same-id
     fallback now), calls the resolver + lock annotator, and ships
     per-direction dicts via `_lineage_nav_direction` (state,
     edition_label, links with verb/payload).  Link titles = latest
     version title (one batched query), matching the old label rule.
   - `_build_viewer_navigation` / `_build_viewer_url_params` DELETED.
   - `_viewer_edition_nav.html` rewritten wholesale: one row per lineage
     link (predecessors above successors) — linked rows stay in-viewer
     load buttons via the same `data-edition-result` payload contract
     (id/title/code/code_display_name/division; query_date/query_code
     re-stamped by the click handler in search.html, which is unchanged);
     locked rows keep the free-tier pricing teaser (lock icon + "— Pro").
     Markers as on the rail, plus an explicit "Current edition" /
     "First edition" in this dedicated box (unlike the rail, which stays
     silent on the successor endpoint).  Fallback "No lineage is
     available" when the provision isn't found.
   - The overlay box in search.html was already titled "Edition lineage".
   - Tests: new `core/tests/test_viewer_nav.py` (6); the two
     `test_access.py` viewer-nav lock tests updated to the new vocabulary
     (they now create the `EditionTransition` their same-id link needs).
   - Real-data check `.tmp/verify_viewer_nav.py`: real renumber
     (2006 B 9.10.18.6. → 2012 B 9.10.18.3.) both directions, tombstone,
     reused-id true predecessor, SB-12 sentinel, 1997 corpus edge — all
     render correctly.
4. ◐ **Doc done 2026-06-11; CCM coordination outstanding.**
   `tasks/complete/provenance/ccm-output-contract.md` now documents
   `provision_discontinuations[]` (shape, status table, default/skip
   rules), `mapping_coverage[]` (semantics, why explicit, reload note,
   emit-from-the-newer-payload guidance), the deprecated
   `not_processed` sentinel-row form, and the row+tombstone producer
   requirement with the one live contradiction:
   (a) 1997 `9.23.9.6.` has BOTH a `renumbered` mapping row
   (→ 2006 `9.23.9.7.`) and a discontinuation tombstone — rows outrank,
   benign on our side, but a producer bug.  (b) **reclassified
   2026-06-11 (Iskander)**: 2006 B `12.3.4.6.` (split row → 2012 B
   `12.3.1.4.` + SB-10 `not_processed` sentinel) is NOT a double
   emission — it's one split verdict with two successors, one of them
   outside the corpus.  Both legs now render: linked row(s) +
   "Some content moved to a document not yet covered"
   (`LineageDirection.outside_corpus`).  The mirror case (merge with an
   out-of-corpus predecessor leg) has no emission shape yet — define
   one with CCM if it arises.  **(c) added 2026-06-11**: identity carries are typed
   `renumbered` in a *total* cross-edition mapping (2,915 same-number
   2006→2012 rows; see Data assumptions ⚠️).  Iskander's position for
   the CCM discussion: universal `renumbered` is right for 1997→2006
   (every provision genuinely renumbered into a division), but probably
   not for 2006→2012 (same number, same division — nothing renumbered).
   CC is robust either way: total emission is now load-bearing for the
   no-fallback resolver, and same-number rows are worded "continues
   as/from" regardless of type (`_link`'s verb override).  If CCM goes
   delta for 2006→2012, revisit the covered-no-row default together.
   **Remaining (external)**: get CCM to emit `mapping_coverage`,
   prefer `provision_discontinuations` over sentinel rows, and fix
   the `9.23.9.6.` row+tombstone contradiction + item (c).

## Current state (2026-06-11, after step 3 + review fixes)

- Step 1 committed as `df5df9f` on branch `provision-mapping` (scoped
  pathspec; a parallel session's free-tier work was staged alongside —
  untouched).  Steps 1.5, 2 and 3 implemented and verified, not yet
  committed.
- Post-review fixes (2026-06-11, Iskander): no version chip on lineage
  rows; no "(same number)" suffix; same-number `renumbered` rows worded
  "continues as/from"; **same-id fallback removed** (resolver now ≤6
  queries; links from rows only; covered-no-row = discontinued/new,
  forward dispositions refine).  Successor tallies unchanged by the
  removal; predecessor sides now read "new in this edition" where no
  row points in (2006: 310, 2012: 286).  Multi-leg verdicts
  (2026-06-11, Iskander): a `not_processed` disposition coexisting with
  rows is the verdict's out-of-corpus leg, not a contradiction —
  `LineageDirection.outside_corpus` renders an extra leg row on both
  surfaces (live case: 2006 B 12.3.4.6.).  The markers name the target
  document when known (Iskander, 2026-06-11):
  `ProvisionDisposition.target_reference` (migration 0032; loader takes
  it from the sentinel's `new_division`, or an optional
  `target_reference` key on explicit entries) →
  `LineageDirection.outside_reference` → "Some content moved to SB-10,
  not yet covered" (multi-leg) / "Content moved to SB-12, not yet
  covered" (standalone not_processed; falls back to the generic
  wording when unknown).  Dev DB's 38 existing rows backfilled from the
  payloads (`.tmp/backfill_target_reference.py`) — a reload populates
  them natively.
  ⚠️ Steps 2–3 touched files that ALSO carry the parallel session's
  uncommitted free-tier edits — `services/search_service.py` (the
  `user=` arg), `core/views/regulation.py` (imports +
  `_provenance_result`), `core/views/search.py` (nav rewrite),
  `core/tests/test_access.py` (the two viewer-nav tests are lineage;
  the pricing-copy assertion fix in `test_gating_on_serves_plan_cards`
  belongs with the free-tier work — it tracks that session's plan-card
  rewording),
  `templates/partials/_viewer_edition_nav.html` (rewritten wholesale;
  the free-tier locked branch is preserved inside the new rows) — a
  lineage commit must stage only the lineage hunks in the first four;
  the nav template's new content is entirely step 3.
- Dev DB: all three editions loaded from the 2026-06 payloads
  (2,976 + 3,128 cross-edition mappings, 5 intra; 262 discontinued +
  38 not_processed dispositions); the two `EditionTransition` rows
  (1997→2006, 2006→2012) were re-inserted **manually** after the
  reloads (stopgap — payloads don't emit `mapping_coverage` yet, and
  every reload wipes coverage rows touching the edition);
  migrations 0030 + 0031 applied.
- Re-runnable corpus checks: `.tmp/verify_lineage.py` (resolver states;
  needs the sys.path-root insert it already has — .tmp scripts don't see
  the `services/` package otherwise) and `.tmp/verify_lineage_ui.py`
  (renders live permalink pages via the test client; `HTTP_HOST=
  "localhost"` because dev ALLOWED_HOSTS lacks "testserver").
- UI surfaces live: search-results provenance rail (incl. transition
  panes) and the permalink page.  Next: step 3 (viewer replacement).

## Findings from first real-data verification (2026-06-10)

**Both findings below are resolved by step 1.5** (disposition ingest);
kept for the record.  The only residuals are the two CCM contradictions
noted under step 4.

Loaded the new 1997/2006/2012 payloads (2,976 + 3,166 cross-edition
mappings, 5 intra-edition); created the two `EditionTransition` rows
manually (stopgap — payloads don't emit `mapping_coverage` yet).
State tallies: 1997 successors 3,050 linked / 99 discontinued; 2006
successors 3,169 / 56; 2012 successors all no-data-yet (closed edition,
OBC 2024 unmapped) — all as designed.  Re-runnable check:
`.tmp/verify_lineage.py`.

Two data findings to act on:

1. **CCM now emits `provision_discontinuations`** (195 for 1997→2006,
   67 for 2006→2012): explicit per-provision tombstones with
   status/source/reasoning.  Cross-check showed **143 provisions where
   the resolver's same-id fallback fabricates a "continues as" link
   that CCM explicitly marks discontinued** (e.g. 2006 C 1.3.5.4. — an
   edition-specific transition article whose id is *reused* by a
   different provision in 2012).  The fallback can't see reuse;
   the tombstones can.  Ingest them (new tombstone record or
   ProvisionMapping variant) and have the resolver treat them as
   authoritative DISCONTINUED, overriding the same-id fallback.
   Resolver-side inference found 0 false negatives the other way for
   1997→2006 — every resolver-discontinued is on CCM's list.
2. **38 mapping rows carry the sentinel `new_provision_id:
   "not_processed"` with `new_division: "SB-12"`** (2006→2012, Part 12).
   Per CCM's row notes, the 2006 Part 12 prescriptive energy-efficiency
   content was delegated to Supplementary Standard SB-12 (via
   12.2.1.1.(3)(b)) — a document outside our corpus.  **Decision
   (Iskander, 2026-06-10): no new disposition state — SB-12 isn't in
   our data, so these render as the existing "not yet covered" marker.**
   They still must be *ingested* (not skipped) because, inside an
   otherwise covered transition, the record has two jobs plain absence
   can't do: (a) per-provision override of the covered-transition
   default ("no row = same id continues"), and (b) suppressing the
   same-id fallback — new 2012 B 12.3.1.2. *reuses the old id for
   different content* (the windows article), so without the record the
   fallback fabricates a confident wrong link.  Same mechanism as the
   discontinuation tombstones in finding 1: one per-provision
   disposition record with a status; `discontinued` → discontinued
   marker, `not_processed` → "not yet covered" marker.

## Do NOT

- No chaining / multi-hop resolution.
- No same-id links, EVER — links come from mapping rows only (the
  covered-transition fallback was removed 2026-06-11; same number does
  not consistently mean same provision).
- Don't show the target's version number on lineage rows — the other
  edition's numbering reads as this edition's (URLs still pin it).
- Don't merge lineage entries into `amendment_chain`.
- Don't keep the viewer prev/next-edition *buttons* — the rows replace them.
