# 5 — Cleanup: Drop Old Models and Fields

## What

Remove models, fields, and files made redundant by the provenance model.

## Depends On

- Task 3 (all code paths use provenance models)
- Task 4 (display uses provenance models)
- All tests passing against new code paths

## Drop Models

- [ ] `CodeMap` — provisions no longer FK here
- [ ] `CodeMapNode` — replaced by `CodeEditionProvision` +
      `CodeEditionProvisionVersion`

## Drop CodeEdition Fields

- [ ] `map_codes` — no maps
- [ ] `pdf_files` — images on version
- [ ] `download_url` — images on version
- [ ] `regulation` (CharField) — `edition.regulations.get(role="base")`
- [ ] `superseded_date` — replaced by `ineffective_date`
- [ ] `amendments` (JSONField) — replaced by `Regulation` records
- [ ] `amendments_applied` (JSONField) — derivable from `Regulation` query
- [ ] `source_url` — on `Regulation.source_pdf` / S3

## Drop Files

- [ ] `config/transitions.json` — data on version date ranges
- [ ] `config/transitions.py` — logic in code_metadata / orchestration
- [ ] `core/management/commands/load_maps.py` — replaced by `load_edition`
- [ ] `core/management/commands/load_code_metadata.py` — merged into
      `load_edition`

## Code Cleanup

- [ ] Remove `_normalize_node_id()` and related workarounds
- [ ] Remove `_populate_provision_transitions()`
- [ ] Remove `load_transitions()` imports
- [ ] Remove all `CodeMap` / `CodeMapNode` imports and references
- [ ] Remove `ProvinceCodeMap` references (now `ProvinceCode`)
- [ ] Remove `CodeSystem` references (now `Code`)

## Verification

- All migrations run cleanly
- All tests pass
- Grep confirms no references to dropped models/fields
- Search results display correctly via provenance models

## Notes

- This is the point of no return — after this, old data paths are gone
- Run in staging first
