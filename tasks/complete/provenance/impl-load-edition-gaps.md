# impl — Close `load_edition` gaps against the CCM contract

**Status: PROPOSED** — 2026-05-27.
**Parent:** [`2-ingestion.md`](2-ingestion.md), [`ccm-output-contract.md`](ccm-output-contract.md).
**Depends on (CCM side):** impl-53 (inline-image asset mirroring), impl-57
(`transition_provision_ref` reshape — already adopted CC-side in commit
`e064e45`).

## Motivation

`core/management/commands/load_edition.py` and the provenance models
(`Regulation`, `RegulationClause`, `CodeEditionProvision`,
`CodeEditionProvisionVersion`, `ProvisionVersionTable`,
`ProvisionMapping`) are live, and a recent commit (`e064e45`) adopted
the `transition_provision_ref` record shape.  But several pieces of the
[CCM output contract](ccm-output-contract.md) are not yet honoured
end-to-end — most visibly for **e-Laws-derived editions (OBC mid-1997
through 2024)**, whose inline HTML carries CSS classes, embedded
`<table>`s, and `<img>` references that today's loader and renderer
silently drop or refuse to display.

Goal: make `load_edition` faithfully ingest the consolidated edition
JSON for every Ontario edition CCM currently emits (`OBC_1997.json`,
`OBC_2006.json`, `OBC_2012.json`, future `OBC_2024.json`), including
the elaws HTML payload and its inline image assets.

## In scope

1. **`versions[].clauses[]` → M2M.**
   - Schema migration: add
     `CodeEditionProvisionVersion.contributing_clauses` M2M to
     `RegulationClause`, ordered by `(regulation.filed_date, clause_id)`
     via an explicit through model so application order is preserved.
   - Backfill: existing single-FK `clause` populates the M2M (one
     entry).  Keep `clause` as a denormalised "primary" pointer or
     drop in the same migration — decide at implementation time once
     callers are audited.
   - Loader: replace `reg_id, clause_id = ver_data.get("regulation"),
     ver_data.get("clause_id")` (`load_edition.py:281-284`) with a
     loop over `ver_data.get("clauses", [])` resolving each tuple
     through `clause_lookup`.
2. **Drop version-level `action`.**
   See sister card [`drop-version-action.md`](drop-version-action.md)
   for the full audit and migration plan.  Track here so it doesn't
   get forgotten — both the model field and `_load_versions` reading
   `ver_data.get("action", ...)` come out together.  Reason in
   brief: CCM impl-20 collapses emission to one version per
   `(provision_id, effective_date)`, so a version can aggregate
   clauses of mixed kinds and no single `action` value is well-
   defined.  Atoms live on `RegulationClause.action`; aggregate views
   derive from the M2M in step 1.  Active/revoked filtering already
   rides on `effective_date` / `ineffective_date`, not on `action`.
3. **`regulations[].assets[]`** (per
   [`inline-html-image-assets.md`](inline-html-image-assets.md), still
   marked PROPOSED in the contract but already emitted by CCM in
   `OBC_2012.json`).
   - New model `RegulationAsset(regulation FK, path, original_url,
     sha256, bytes, content_type)`.  Unique on `(regulation, path)`.
   - Loader: ingest into the new table.
   - Sync step: on ingest, copy bytes from
     `<source-root>/<path>` (e.g. `.../data/outputs/laws/images/...`)
     to a CodeChronicle-served local directory at the **same
     relative path** (e.g. `<MEDIA_ROOT>/laws/images/...`), verifying
     `sha256` against the manifest entry.  Skip when the destination
     already exists with a matching hash.  Refuse to ingest the
     edition if any asset fails verification — broken inline images
     are a real bug, not a soft case.
   - Public serving: Django serves the local directory at the host
     root with the same prefix (`/laws/images/...`), so the inline
     `<img src>` references in `versions[].html` resolve without HTML
     rewriting (the contract is explicit on this: "no rewrite of
     `<img src>` is needed").
   - **Later: S3.**  The sync step is intentionally storage-backend
     agnostic — swap the destination writer for a `boto3` upload
     once everything else is working.  Path layout doesn't change,
     so the inline `<img src>` references and templates stay
     untouched across the migration.
4. **Image pipeline for `page_images` + `tables[].images`.**
   - Mirror `documents/{pdf_name}/{page}.webp` and `amended/...`
     trees from CCM's build artifact root to the same local
     `<MEDIA_ROOT>/documents/...` and `<MEDIA_ROOT>/amended/...`
     paths.
   - Idempotent, content-addressed (`sha256` check before copy).
   - Manifest log (e.g. `image_sync_log.jsonl` per edition) so reruns
     are O(diff) not O(N).
   - Frontend serves the same paths from the local directory;
     templates already use the paths verbatim — no template changes
     expected.  S3 migration comes later via the same storage-backend
     swap as step 3.
5. **Meta-amendment stub merge.**
   When the same `(regulation, clause_id)` appears as both a full
   clause and a back-pointer stub (`amended_by` only), merge in the
   loader before `bulk_create` so the unique constraint isn't tripped.
   Drop the stub if a full clause is present; otherwise persist the
   stub.  Add a test case off `OBC_2006.json` (where 360/13 meta-
   amendments live).
6. **HTML rendering for elaws editions.**
   - The HTML coming out of `versions[].html` is rendered **verbatim**
     via `{{ version.html|safe }}` — no sanitisation, no rewriting.
     e-Laws is a trusted government source; CCM mirrors its bytes
     faithfully, and any drift in that contract is CCM's bug to fix,
     not CC's to paper over.
   - Today's old `load_maps`-era `notes_html` path runs through
     python-markdown (`load_maps.py:25`); that path goes away with
     `load_maps` itself (see [`5-cleanup.md`](5-cleanup.md)) and is
     not in scope here.
   - CSS: ship a small stylesheet that maps the e-Laws class
     namespace (`Psection-e`, `subsection-e`, `MsoNormalTable`, etc.)
     to readable equivalents — the source classes don't carry CSS, so
     unstyled they collapse to default block flow.
7. **Idempotency cleanup.**
   In `_load_edition`, when deleting an edition's provisions also
   delete `ProvisionMapping` rows referencing them on either side
   (cross-edition mappings included).  Otherwise FK targets dangle on
   re-ingest.
8. **Sanity guards.**
   - Refuse to ingest when `amendment_chain_complete: false` (contract
     §"What CodeChronicle Does NOT Expect" — incomplete chains are
     out-of-spec).
   - Refuse to ingest a path under `snapshots/`; those are CCM's raw
     e-Laws scrapes, not the consolidated output (the file shape is
     identical, so the loader would *appear* to succeed).

## Out of scope (separate cards)

- Killing `load_maps` / `CodeMap` / `CodeMapNode` / `KeywordIDF` once
  search is migrated to `CodeEditionProvisionVersion`.  Tracked by
  [`5-cleanup.md`](5-cleanup.md).
- Search migration to the new schema (`3-code-paths.md`, `4-display.md`).
- Cross-edition matcher output (CCM impl-?).  This card assumes
  `provision_mappings[]` arrives shaped per contract.
- NBC editions — Ontario-first per
  [`project_provenance_design`](../../../.claude/projects/C--Users-victu-Documents-repos-CodeChronicle/memory/project_provenance_design.md).

## Verification

- `load_edition --source ../CodeChronicleMapping/data/outputs/OBC_1997.json`
  loads without error; row counts logged match the JSON's emitted
  counts (regulations, clauses, provisions, versions, tables, mappings,
  assets).
- `load_edition --source ../CodeChronicleMapping/data/outputs/OBC_2012.json`
  succeeds, and a sample provision known to have an inline equation
  (e.g. `4.1.6.5.` per the impl-53 contract addition) renders the
  `<img>` against a real S3 object.
- Re-running either command produces zero net DB writes for unchanged
  payloads (idempotency).
- `ProvisionMapping` rows for OBC 1997 → OBC 2006 survive a re-ingest
  of either edition.
- A trivial Django check: pick a same-date amendment cluster (multiple
  clauses on one effective date) and confirm
  `version.contributing_clauses.count() > 1` for the resulting version.

## File touchpoints (anticipated)

- `core/models.py` — add `RegulationAsset`, M2M on
  `CodeEditionProvisionVersion`, drop `action`.
- `core/migrations/0018_*` (M2M + RegulationAsset + drop action).
- `core/management/commands/load_edition.py` — clauses[] loop, asset
  ingest, stub merge, dangling-mapping cleanup, snapshots/ guard.
- `core/management/commands/sync_images.py` *(new)* — S3 mirror for
  `documents/`, `amended/`, and `laws/images/` trees.
- `templates/partials/provision_render.html` (or wherever versions
  display) — `|safe` path for trusted e-Laws HTML, plus the e-Laws
  CSS shim.
- `static/css/elaws.css` *(new)* — class shim.

## Open questions

- **Single-clause "primary" FK on versions** (keep vs. drop after M2M
  migration): keeping it lets templates render the most-recent
  amending clause without traversing the M2M.  Drop unless display
  code actually depends on it — audit during step 2.
- **Asset bucket layout**: serve under `/laws/images/...` and
  `/documents/...` at the host root verbatim (per impl-53), or behind
  a versioned prefix (`/static/codes/v1/laws/images/...`) so we can
  cache-bust per edition release?  Spec the URL prefix here before
  step 4 lands so the contract addendum can be promoted from PROPOSED
  to RATIFIED.
- **Stub-merge ordering**: CCM emits both stub and full on the same
  regulation in a single file, but does it guarantee they're adjacent?
  If not, the merge needs a two-pass over `clauses[]`.
