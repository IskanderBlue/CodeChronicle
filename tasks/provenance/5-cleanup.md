# 5 — Cleanup: Drop Old Models and Fields

**Status: DONE — 2026-06-02.** Migration `0024` applied cleanly, no model
drift, `ruff` clean, full suite green (182 passed).

## What

Remove models, fields, and files made redundant by the provenance model.

## Depends On

- Task 3 (all code paths use provenance models)
- Task 4 (display uses provenance models)
- All tests passing against new code paths

## Drop Models

- [x] `CodeMap` — provisions no longer FK here
- [x] `CodeMapNode` — replaced by `CodeEditionProvision` +
      `CodeEditionProvisionVersion`
- [x] `KeywordIDF` + the `keyword_idf` materialized view — not in the original
      list, but the matview was defined `FROM code_map_nodes` (so it blocked the
      table drop) and the live search path computes IDF on the fly from
      `CodeEditionProvisionVersion.keyword_counts` (`api/search/engine.compute_idf`),
      not from the view. Dropped via `RunSQL` ordered before the table delete.

## Drop CodeEdition Fields

- [x] `map_codes` — no maps
- [x] `pdf_files` — images on version
- [x] `download_url` — images on version
- [x] `regulation` (CharField) — `edition.regulations.get(role="base")`
- [x] `superseded_date` — replaced by `ineffective_date`
- [x] `amendments` (JSONField) — replaced by `Regulation` records
- [x] `amendments_applied` (JSONField) — derivable from `Regulation` query
- [x] `source_url` — on `Regulation.source_pdf` / S3

## Drop Files

- [x] `config/transitions.json` — data on version date ranges
- [x] `config/transitions.py` — logic in code_metadata / orchestration
- [x] `config/metadata.json` — orphaned old seed format; only reader was
      `load_code_metadata` (deleted). `load_edition` reads CCM `data/outputs`.
- [x] `core/management/commands/load_maps.py` — replaced by `load_edition`
- [x] `core/management/commands/load_code_metadata.py` — merged into
      `load_edition`
- [x] `core/management/commands/wipe_legacy_data.py` — its job (empty legacy
      tables before the drop) is now done by the migration itself
- [x] `core/management/commands/check_data_integrity.py` — every check it ran
      targeted `CodeMap`/`CodeMapNode`/`map_codes`, all now gone
- [x] Obsolete tests: `config/tests/test_transitions.py`,
      `core/tests/test_load_maps.py`, `core/tests/test_viewer_navigation.py`

## Code Cleanup

- [x] Remove `_normalize_node_id()` and related workarounds (gone with `load_maps`)
- [x] Remove `_populate_provision_transitions()` (gone with `load_maps`)
- [x] Remove `load_transitions()` imports
- [x] Remove all `CodeMap` / `CodeMapNode` imports and references
      (`admin.py`, `views/search.py`, `code_metadata.py`, test fixtures)
- [x] Remove `ProvinceCodeMap` references (already `ProvinceCode`)
- [x] Remove `CodeSystem` references (already `Code`)
- [x] Removed now-dead `code_metadata` helpers: `get_map_codes`,
      `get_source_url`, `get_pdf_filename`, `get_download_url`,
      `get_pdf_expectations`, `_find_edition`
- [x] Templates: `_viewer_edition_dates.html` + `regulation/chain.html`
      switched `superseded_date` → `ineffective_date`; dropped the
      `edition.regulation` (CharField) header
- [x] Docs: `CLAUDE.md` / `AGENTS.md` point at `load_edition`

## Verification

- [x] All migrations run cleanly (`migrate` + `makemigrations --check` → no drift)
- [x] All tests pass (182)
- [x] Grep confirms no references to dropped models/fields (outside historical
      migrations / archived notes)
- [x] Search results display correctly via provenance models

## Follow-up (belongs to the display-migration card, not this one)

- `search.html` still has the viewer PDF/`source_url` Alpine block. The server
  no longer emits those keys, so the block stays hidden (`x-show` → falsy) —
  inert, not broken. Removing it is part of the images-on-versions viewer swap
  owned by `impl-display-migration.md`.

## Notes

- This is the point of no return — after this, old data paths are gone.
- Migration `0024` is reversible: the `RunSQL` reverse recreates the matview,
  and op replay order restores the tables before that runs.
