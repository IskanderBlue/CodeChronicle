# 3 — Code Paths: Search, API, Applicable Codes

## What

Update all code that reads from old models (`CodeMapNode`, `CodeEdition`
fields, `transitions.json`) to use the provenance models instead.

## Depends On

- Task 1 (schema exists)
- Task 2 (data ingested)

## Changes

### `config/code_metadata.py` — `get_applicable_codes()`

Rewrite to query `CodeEdition` directly:

```python
province_codes = ProvinceCode.objects.filter(
    province=province
).values_list("code", flat=True)
national_codes = Code.objects.filter(is_national=True)

editions = CodeEdition.objects.filter(
    system__in=[*province_codes, *national_codes],
    effective_date__lte=search_date,
).filter(
    Q(ineffective_date__isnull=True) | Q(ineffective_date__gt=search_date)
).select_related("system").prefetch_related("regulations")
```

Rename `ProvinceCodeMap` → `ProvinceCode`, `CodeSystem` → `Code`.

### `config/transitions.py` → removed

Transition detection is now a version query:

```python
# Two versions in force = transition active
versions = CodeEditionProvisionVersion.objects.filter(
    provision=provision,
    effective_date__lte=query_date,
).filter(
    Q(ineffective_date__isnull=True) | Q(ineffective_date__gt=query_date)
).select_related(
    "clause__regulation",
    "transition_provision__provision",
)
```

If this returns 2 rows, there's an active transition. The newer version's
`transition_provision` FK gives the applicability text.

### `api/search/orchestration.py`

- For each search result, resolve the active version(s) via
  `prefetch_related` / `select_related`:
  ```python
  provisions = CodeEditionProvision.objects.filter(
      edition__in=applicable_editions,
      # ... search criteria ...
  ).prefetch_related(
      Prefetch(
          "versions",
          queryset=CodeEditionProvisionVersion.objects.filter(
              effective_date__lte=query_date,
          ).filter(
              Q(ineffective_date__isnull=True) | Q(ineffective_date__gt=query_date)
          ).select_related("clause__regulation")
          .prefetch_related("tables"),
      ),
      # Appendix notes with their active versions
      Prefetch(
          "appendix_entries",
          queryset=CodeEditionProvision.objects.prefetch_related(
              Prefetch("versions", queryset=active_versions_qs),
          ),
      ),
  )
  ```
- Detect transitions (2 active versions in prefetched set)
- Include next version not yet in force (for proof):
  ```python
  Prefetch(
      "versions",
      queryset=CodeEditionProvisionVersion.objects.filter(
          effective_date__gt=query_date,
      ).order_by("effective_date")[:1],
      to_attr="next_versions",
  )
  ```

### `api/formatters.py`

- Build result context from prefetched version data
- Provenance data for templates:
  ```python
  {
      "version": active_version,
      "regulation": active_version.clause.regulation
          if active_version.clause
          else edition.regulations.get(role="base"),
      "clause": active_version.clause,
      "next_version": next_version,  # may be None
      "is_base": active_version.version == 0,
      "regulation_chain": edition.regulations.all(),
      "tables": active_version.tables.all(),
  }
  ```
- Copy-button reference string:
  ```
  OBC 1997, Div B, S 3.1.4.7. -- Fire Separations
  In force: 1998-04-06 (O. Reg. 403/97)
  Amended by: O. Reg. 22/98, cl. 1.(1)
  Next amendment: O. Reg. 152/99 (1999-04-01) -- not in force at query date
  ```

### Tests

- [ ] Test version query returns correct version for a given date
- [ ] Test transition detection (2 overlapping versions)
- [ ] Test "next version not in force" proof
- [ ] Test cross-edition transition (different editions)
- [ ] Test `get_applicable_codes()` returns correct editions
- [ ] Rename `ProvinceCodeMap` → `ProvinceCode` in all fixtures
- [ ] Rename `CodeSystem` → `Code` in all fixtures

## Verification

- `get_applicable_codes()` returns same editions as before
- Search results include provenance data (regulation, clause, chain)
- Transition detection works for overlapping versions
- "Next amendment" shown when one exists but isn't in force
- All queries use prefetch/select_related (no N+1)
- All existing tests pass with updated fixtures
