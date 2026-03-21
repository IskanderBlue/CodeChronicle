# 3 — Remove Old Fields and Cleanup

## What

Drop fields and files that are now redundant with the `Transition` model
and `CodeMap.edition` FK.

## Prerequisites

- Task 1 complete (schema + backfill)
- Task 2 complete (all code paths use Transition)
- All tests passing against new code paths

## Changes

### Migration: CodeMap
- [ ] Make `CodeMap.edition` FK non-nullable

### Migration: CodeEdition — drop fields
- [ ] `effective_date` — derived from `edition.transitions`
- [ ] `superseded_date` — derived from `edition.transitions` (end_date)
- [ ] `regulation` — on Transition record
- [ ] `source_url` — on Transition record
- [ ] `map_codes` — replaced by `edition.maps.all()`
- [ ] `pdf_files` — moved to `CodeMap.pdf_file`
- [ ] `download_url` — moved to `CodeMap.download_url`
- [ ] `amendments` — never consumed by any code. Drop entirely, or rename
      to `legislative_history` if we want to preserve "which regulations
      were consolidated into this edition" for reference.

### Migration: CodeMapNode — drop field
- [ ] `provision_transitions` — replaced by `node.transitions.all()`

### Delete files
- [ ] `config/transitions.json` — data now in Transition table
- [ ] `config/transitions.py` — logic now in code_metadata / orchestration

### Code cleanup
- [ ] Remove any remaining references to dropped fields
- [ ] Remove `_populate_provision_transitions()` from `load_maps.py`
      (if not already removed in task 2)
- [ ] Remove `load_transitions()` imports

### metadata.json cleanup
- [ ] Remove fields from `metadata.json` that are now on Transition:
      `effective_date`, `superseded_date`, `regulation`, `source_url`
- [ ] Move `pdf_files` and `download_url` to per-map-code entries or
      remove if CodeMap.pdf_file is populated from another source
- [ ] Decide on `amendments` — keep as `legislative_history` or drop

## Verification

- All migrations run cleanly
- All tests pass
- No references to dropped fields in codebase (grep check)
- Search results still display correctly
- Transition provenance displays correctly in templates

## Depends On

- Task 2 (all code paths updated)

## Notes

- This is the "burn the bridges" step — after this, there's no going back
  to the old schema
- Consider running in staging first to verify no edge cases
