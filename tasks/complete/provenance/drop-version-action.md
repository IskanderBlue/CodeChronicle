# Drop `CodeEditionProvisionVersion.action`

## What

Remove the `action` field from `CodeEditionProvisionVersion`.  The
field is effectively write-only on the CC side: ingest writes it,
one non-critical log warning reads it, and no search, orchestration,
template, admin-filter, or API path consumes it.

## Why

CCM is collapsing its per-clause `ProvisionVersion` emission into
per-effective-date emission (see CCM `impl-20-one-version-per-effective-date.md`).
A version aggregating multiple clauses — possibly of different
amendment kinds (`revoke_and_substitute` + `amend_strike_sub` +
`amend_table` in the same window) — has no single `action` value.

Three ways to handle this: fuzz the field (pick one action via a
precedence ladder), pluralize it (`actions: list`), or drop it.
Audit of CC consumers supports dropping:

### Audit results

Searched the CC codebase for reads of `CodeEditionProvisionVersion.action`:

| Location | Kind of use |
|----------|-------------|
| `core/management/commands/load_edition.py:288` | **Write** (ingest) |
| `core/management/commands/load_edition.py:456` | **Read** — non-critical log warning: checks whether a `ProvisionMapping.introduced_by` points at a version with `action == RENUMBERED`.  Logs a warning either way; does not block or correct. |
| `core/tests/test_load_edition.py:114, 122` | Test assertions |
| `api/tests/test_tfidf.py:33, 39` | Test setup |

No reads in:
- `api/search/orchestration.py`, `api/search/engine.py`
- Views, URL routing, templates
- `core/admin.py` (only display, not filter)

Active/revoked filtering is done via `effective_date` /
`ineffective_date` (indexed), not via `action`.

### Derivability of the current values

| Current `action` value | Replacement |
|------------------------|-------------|
| `ORIGINAL` | `version == 0 AND clause IS NULL` |
| `ADDED`    | `version == 0 AND clause IS NOT NULL` (amend_add creator in FK) |
| `RENUMBERED` | Already captured by `ProvisionMapping.mapping_type == "renumbered"` |
| `REVOKE_AND_SUBSTITUTE` / `AMEND_STRIKE_SUB` / `AMEND_ADD` | Lives on `RegulationClause.action` (clause-level), which survives |
| `REVOKED` | Needs a narrow replacement — see open question below |

## How

### Schema changes

1. Migration to drop `CodeEditionProvisionVersion.action`.  No data
   backfill required — nothing reads it for correctness.
2. Remove the `Action` `TextChoices` inner class from the model.

### Ingest changes (`core/management/commands/load_edition.py`)

3. Remove `action=ver_data.get("action", ...)` at `:288`.
4. Rework the warning at `:456`.  Current check: "the version
   referenced by `introduced_by` should have `action == "renumbered"`."
   Replace with: "the mapping's own `mapping_type` should be
   `renumbered` if it carries an `introduced_by`."  Same smoke-test
   intent, read from `ProvisionMapping.mapping_type` instead.

### Test updates

5. `core/tests/test_load_edition.py:114, 122` — drop the `action`
   assertions or rewrite them as assertions on `version`,
   `clause_id`, or `mapping_type` as appropriate.
6. `api/tests/test_tfidf.py:33, 39` — drop the `action="original"`
   kwarg from the version factory calls.

### Producer coordination (CCM side)

7. CCM's `edition_assembler._version_to_dict` stops emitting the
   `action` key — tracked in CCM `impl-20-one-version-per-effective-date.md`.
   During the transition, ingest should tolerate either shape (key
   present → ignore; key absent → fine).  Easiest: just drop the
   `ver_data.get("action", ...)` line entirely so ingest ignores it
   whether present or absent.

## Acceptance criteria

- Migration applies cleanly on a dev DB with existing data.
- `load_edition` ingests the consolidated edition JSON whether or
  not the JSON carries an `action` key per version.
- All existing CC tests pass (with the updates above).
- The `ProvisionMapping.mapping_type`-based warning fires correctly
  on a seeded test fixture with a miswired `introduced_by`.

## Non-goals

- **Not touching `RegulationClause.action`.**  Clause-level intent
  is preserved — this is only about the *version-level* field.
- **Not backfilling data.**  The column is dropped outright; its
  values were never used for correctness, and reconstruction from
  the replacement derivations is straightforward if anyone ever
  needs it.

## "Revoked" signalling — derived, not stored

The one current `action` value that isn't trivially derivable from
inherent fields is `REVOKED`, but it *is* derivable one step
removed: through the version's contributing clauses.  CCM's new
output shape gives every version a `clauses[]` list (M2M to
`RegulationClause`).  A version is a revocation iff any clause in
that list has `RegulationClause.action == "revoke"`.

No new version-level field needed.  `RegulationClause.action` is
already required, enumerated, and round-trip-stable.  A computed
property is appropriate:

```python
class CodeEditionProvisionVersion(models.Model):
    # ...
    @property
    def is_revoked(self) -> bool:
        return self.clauses.filter(
            action=RegulationClause.Action.REVOKE,
        ).exists()
```

Or, for query-path efficiency in rendering, an annotation:

```python
CodeEditionProvisionVersion.objects.annotate(
    is_revoked=Exists(
        self.clauses.filter(action=RegulationClause.Action.REVOKE)
    )
)
```

Templates call `version.is_revoked` to toggle tombstone rendering.

## Sequencing

After CCM `impl-20-one-version-per-effective-date.md` lands the new
output shape (or is staged in a coordinated PR pair).  Order:

1. CCM `impl-20` implementation (changes JSON shape).
2. This task: CC migration + ingest update.
3. Regenerate OBC 1997 / NBC / etc. with the new shape.
4. Verify CC renders editions correctly end-to-end.
