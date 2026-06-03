# 2 — Update Code Paths

## What

Update all code that reads `CodeEdition.effective_date`, `transitions.json`,
or `CodeMapNode.provision_transitions` to use the `Transition` model instead.

## Changes

### `core/management/commands/load_maps.py`
- [ ] Use `CodeMap.edition` FK instead of `_find_code_name_for_map_code()`
      string lookups
- [ ] Remove `_populate_provision_transitions()` — node-level Transitions
      are now created during `load_code_metadata` or data import, not
      stamped post-load
- [ ] If provision-level Transition data is present in map JSON (as
      `transitions` array on sections), create `Transition` records with
      `node` FK during node loading

### `core/management/commands/load_code_metadata.py`
- [ ] Create `Transition` records instead of setting
      `CodeEdition.effective_date` / `superseded_date`
- [ ] Set `jurisdiction` based on whether the CodeSystem is national
- [ ] Import transition overlap data as `Transition` records instead of
      relying on `transitions.json`

### `config/code_metadata.py`
- [ ] Rewrite `get_applicable_codes()` to query `Transition`:
  ```python
  systems = ProvinceCodeSystem.objects.filter(
      province=province
  ).values_list("code_system", flat=True)
  national = CodeSystem.objects.filter(is_national=True)

  active = Transition.objects.filter(
      edition__system__in=[*systems, *national],
      scope="whole_code",
      jurisdiction__in=["", province],
      effective_date__lte=search_date,
  ).filter(
      Q(end_date__isnull=True) | Q(end_date__gt=search_date)
  ).select_related("edition", "edition__system")
  ```
- [ ] Rename `ProvinceCodeMap` references → `ProvinceCodeSystem`

### `config/transitions.py`
- [ ] Rewrite `get_active_transitions()` as a database query instead of
      JSON file read:
  ```python
  Transition.objects.filter(
      edition__in=applicable_editions,
      scope="whole_code",
      jurisdiction__in=["", province],
      effective_date__lte=search_date,
      end_date__gt=search_date,
  ).select_related("edition")
  ```
- [ ] Keep module as a thin wrapper during transition; remove in task 3

### `api/search/orchestration.py`
- [ ] Replace `get_active_transitions()` JSON-based call with Transition
      query
- [ ] Attach Transition records to search results (all transitions for the
      edition + any node-specific transitions)
- [ ] Prefetch Amendment records for matched nodes (avoid N+1):
      `Amendment.objects.filter(node__in=matched_nodes).order_by("node", "order")`
- [ ] For national codes, include both publication and provincial adoption
      Transitions
- [ ] Build provenance context per result:
      - `result.commencement` — node-level Transition if exists, else
        edition-level Transition
      - `result.amendments` — Amendment queryset for the node
      - `result.is_provision_specific` — True if node has own Transition
        or any Amendments

### `api/formatters.py`
- [ ] Replace `transition_context` dict construction with Transition model
      fields
- [ ] Pass through `provision_quote`, `source_url`, `jurisdiction`
- [ ] Update `merge_transition_compare_results()` to use Transition data
- [ ] Build copy-button reference string data:
      `"{code} {year}, Div {div}, § {id} — {title}\n
       In force: {date} ({regulation}, {provision_id})\n
       Amended by: {amendment_reg}, {amendment_provision_id} ({date})"`

### `core/management/commands/load_maps.py`
- [ ] Import section-level `commencement` from map JSON as node-level
      Transition records
- [ ] Import section-level `amendments` from map JSON as Amendment records
      (ordered, most recent first → order=0)
- [ ] Clear and recreate Amendment records on re-import (idempotent)

### Tests
- [ ] Update `test_orchestration.py` — mock Transition + Amendment queries
      instead of `transitions.json`
- [ ] Update `test_search.py`, `test_integration.py` — use Transition +
      Amendment fixtures
- [ ] Update `test_load_maps.py` — CodeMap.edition FK, no provision stamping,
      Amendment import
- [ ] Rename `ProvinceCodeMap` in all test fixtures

## Verification

- All existing tests pass with updated fixtures
- Search results include Transition provenance data
- `get_applicable_codes()` returns same editions as before
- Transition overlaps detected same as before

## Depends On

- Task 1 (schema exists, data backfilled)

## Notes

- During this phase, old fields still exist — code reads from Transition
  model but old fields haven't been dropped yet
- This is the largest task — touches most of the query/display pipeline
