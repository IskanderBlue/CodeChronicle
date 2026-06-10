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
| **linked** | Covered transition: mapping row(s) (`mapped_forward` = successors, `mapped_back` = predecessors), *or* no row but same (division, provision_id) exists in the adjacent edition | Link(s) labelled as the prev/next edition's equivalent; same-id case worded as such ("continues as … (same number)"); **multiple links only for split/merged** |
| **discontinued** | Covered transition, no row, no same-id match | No link; marker — successor side "discontinued after this edition", predecessor side "new in this edition" |
| **no data yet** | A neighbouring edition exists in reality but the transition isn't covered (today: 2012→2024, and everything before 1997) | No link; "transition not yet mapped" marker |
| **endpoint** | No neighbouring edition exists in reality | Predecessor side: "first edition"; successor side: "current edition" (or render nothing) |

Key rules:

- **Same-id fallback is only trusted on covered transitions.** On an
  uncovered transition the id may have been renumbered away or reused, so we
  show "no data yet" — never a same-id guess. This is also what makes
  "discontinued" trustworthy.
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
   `core/views/search.py:32-145`) with the same lineage rows. The
   `(edition, provision_id)` + division-preference lookup survives **only
   inside the resolver** as the implementation of the same-id fallback (the
   division tiebreak is still needed: a bare id can exist in several
   divisions of the target edition).
3. **Context builders**: search path — orchestration calls the resolver once
   for the whole result set; formatter copies per-provision lineage into the
   result dict next to `amendment_chain` (`api/formatters.py:468` area).
   Permalink path — `_provenance_result` (`core/views/regulation.py:334`)
   calls the same resolver for the single matched provision.

Transition-compare cards: each pane's rail will show lineage rows pointing
at the other pane. Mildly redundant; ship it, suppress only if it reads
noisy.

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
2. Rail rows (search results + permalink page).
3. Viewer replacement; delete the heuristic nav functions.
4. CCM contract doc update; coordinate `mapping_coverage` emission.

## Do NOT

- No chaining / multi-hop resolution.
- No same-id links on uncovered transitions.
- Don't merge lineage entries into `amendment_chain`.
- Don't keep the viewer prev/next-edition *buttons* — the rows replace them.
