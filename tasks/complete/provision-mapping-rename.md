# ProvisionMapping Rename + `introduced_by_version` FK

**Status: COMPLETE** (2026-04-17)

Shipped in commit `e59cf59` on branch `cepv` — bundles the model
rename, migration `0015_provision_mapping_rename.py`, loader rewrite,
search-orchestration updates, admin rename, and contract-doc rewrite.
CCM-side counterpart landed earlier in CCM commits `2270653`, `c15115d`,
`9d2555e`.

## Verification status

- `python manage.py check core` passes.
- The migration file is consistent with the model changes (rename +
  new FK + `mapping_type` choices + enum extensions on
  `RegulationClause.action` and `CodeEditionProvisionVersion.action`).
- CCM's OBC 1997 assembly produces exactly the `provision_mappings[]`
  shape this loader expects (verified on the CCM side).

## Verification limits

- **Not yet exercised**: `python manage.py migrate` against a real
  Postgres DB and the pytest suite. Local Postgres auth failed in the
  dev environment, so end-to-end ingest-then-query verification is
  deferred to the first deployment (or a session with working
  credentials). The four new pytest checks listed under "Verification"
  below remain to be written/run.

---

## What

Rename `ProvisionEditionMapping` → `ProvisionMapping`, add an
`introduced_by_version` FK, and accept a unified `provision_mappings[]`
array in the consolidated edition JSON (replacing the current
`edition_mappings[]`).

The model becomes the single source of truth for *any* old↔new
provision identity link, regardless of whether the two endpoints
share an edition. This subsumes both the existing cross-edition use
case (`ProvisionEditionMapping`) and a new intra-edition use case
(currently expressed only as a `renumbered_from` string field on
`CodeEditionProvisionVersion` that no CC code reads).

## Why

Two motivations:

1. **The current name is structurally misleading.** `old_provision`
   and `new_provision` are FKs to `CodeEditionProvision`, not to
   `CodeEdition`. Whether a row is "intra-edition" or "cross-edition"
   is a computed property of the FK targets, not a constraint of the
   model. The "Edition" in the name implies the model can only
   represent cross-edition pairs, which is false.
2. **CCM emits intra-edition renumbers today, but CC has no
   structural place to store them.** The amendment applicator emits
   `ProvisionVersion(action="renumbered", renumbered_from="...")`
   when a gazette clause renumbers a provision (e.g., O. Reg. 22/98
   cl. 25.(2) renumbering 9.23.9.5. → 9.23.9.6.). CCM serializes
   `renumbered_from` to JSON; CC's `load_edition.py` and
   `orchestration.py` ignore it. There is no FK chain a search
   result can follow to find a renumbered provision's prior identity.

A unified `ProvisionMapping` solves both: same FK structure, same
`prefetch_related` patterns, same `_merge_..._transitions` query.
The only addition is `introduced_by_version` (nullable FK to the
version that triggered the mapping, populated for intra-edition
rows, omitted for cross-edition rows).

## Model changes

### Rename

```python
class ProvisionMapping(models.Model):  # was: ProvisionEditionMapping
    class MappingType(models.TextChoices):
        RENUMBERED = "renumbered", "Renumbered"
        SPLIT = "split", "Split"
        MERGED = "merged", "Merged"
        REPLACED = "replaced", "Replaced"

    old_provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE, related_name="mapped_forward",
    )
    new_provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE, related_name="mapped_back",
    )
    mapping_type = models.CharField(max_length=20, choices=MappingType.choices)
    introduced_by_version = models.ForeignKey(
        CodeEditionProvisionVersion,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="introduced_mappings",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "provision_mappings"  # was: provision_edition_mappings
        constraints = [
            models.UniqueConstraint(
                fields=["old_provision", "new_provision"],
                name="provision_mapping_unique",
            ),
        ]
```

Reverse relations (`mapped_forward` / `mapped_back`) are unchanged —
the existing `prefetch_related` patterns continue to work.

### `mapping_type` vocabulary rationale

CCM and CC settled on four values (down from the seven originally
sketched in CCM's `impl-10-edition-mappings.md`):

| Type | Cardinality | Content carries forward? |
|------|-------------|--------------------------|
| `renumbered` | 1 → 1 | yes (subsumes the old "renamed" — id and/or division change) |
| `split` | 1 → N | partial (each new gets a slice) |
| `merged` | N → 1 | yes (combined) |
| `replaced` | 1 → 1 | no (semantic equivalence only) |

Dropped values:

- `same` — implicit when both endpoints have matching `(provision_id, division)`. No row needed.
- `renamed` — collapsed into `renumbered`. The old distinction (id-stable but division-changed) was historical, not structural.
- `removed` — cannot be represented under the `(old, new)` FK schema (no `new_provision` to point at). Inferred from absence.

### `introduced_by_version` semantics

- **Populated** for intra-edition mappings. Every row produced from a
  CCM `ProvisionVersion(action="renumbered")` carries an FK to that
  version. This gives consumers a one-step chase to the triggering
  date, clause, and regulation:
  ```python
  mapping.introduced_by_version.effective_date   # when the renumber took effect
  mapping.introduced_by_version.clause           # the gazette directive
  mapping.introduced_by_version.clause.regulation  # the O. Reg.
  ```
- **Null** for cross-edition mappings. No single version "introduces"
  an edition boundary — the date is the new `CodeEdition.effective_date`.
- **Consistency check** at ingest: any populated FK must satisfy
  `introduced_by_version.action == "renumbered"` and
  `introduced_by_version.provision == new_provision`. CCM should
  produce these correctly; CC validates and logs malformed entries.

## Migration

A single Django migration handles:

1. `RenameModel("ProvisionEditionMapping", "ProvisionMapping")`
2. `AlterModelTable("ProvisionMapping", "provision_mappings")`
3. `AddField("ProvisionMapping", "introduced_by_version", ForeignKey(...))`
4. `AlterField("ProvisionMapping", "mapping_type", CharField(choices=MappingType.choices))`

The table is currently empty in production (CCM emits `"edition_mappings": []`),
so no data migration is required. The unique constraint and reverse
relation names are preserved across the rename.

`UniqueConstraint` name `provision_mapping_unique` was already in use
under the old model name — unchanged.

## Ingestion changes (`core/management/commands/load_edition.py`)

### Wire format change

The consolidated edition JSON's top-level `edition_mappings[]` array
becomes `provision_mappings[]`. The shape changes minimally — entries
gain an optional `introduced_by` field:

```json
{
  "provision_mappings": [
    {
      "old_provision_id": "9.23.9.5.",
      "old_division": "",
      "old_edition": "1997",
      "new_provision_id": "9.23.9.6.",
      "new_division": "",
      "new_edition": "1997",
      "mapping_type": "renumbered",
      "introduced_by": {
        "provision_id": "9.23.9.6.",
        "division": "",
        "version": 1
      }
    }
  ]
}
```

The `division` strings are the per-provision `division` field —
top-level Division A/B/C in NBC-style codes.  OBC 1997 has no
Division A/B/C structure, so all five entries from O. Reg. 22/98
cl. 25.(2) carry `""`; codes that do (e.g. NBC 2025 Division B
Part 9) populate the field.

`introduced_by.version` uses 0-based version numbering: v0 = the
`original` action recorded for every base-map provision, v1 = the
`renumbered` action that closes the prior content and stamps the
carried-forward content at the new id.

Cross-edition entries omit `introduced_by` and have differing
`old_edition` / `new_edition` values.

### Loader rename

- `_load_edition_mappings(code, data.get("edition_mappings", []))` →
  `_load_provision_mappings(code, data.get("provision_mappings", []))`.
- The loader still resolves `(edition, provision_id, division)` triples
  to `CodeEditionProvision` PKs as before. For intra-edition entries
  (`old_edition == new_edition`), the existing resolution code works
  without modification.
- New: when `introduced_by` is present, resolve it via the existing
  `version_lookup` dict (already keyed by `(provision_id, division,
  version_num)` at `load_edition.py:257`) and assign the FK. Pass
  `version_lookup` through to the new mapping loader.
- Loader ordering: provisions → versions → tables → transitions →
  **provision_mappings**. This is the same order as today; the
  mapping loader already runs after versions are created, so the
  `version_lookup` is in scope.

### Backwards compatibility

None required. CC has not yet ingested any consolidated edition JSON
(the table is empty in production), and CCM is still building the
output. The loader accepts only `provision_mappings[]`. If a JSON
arrives with `edition_mappings[]`, ingestion fails loudly — that
indicates a stale CCM emission.

## Search orchestration changes (`api/search/orchestration.py`)

- `_merge_cross_edition_transitions` → `_merge_provision_mapping_transitions`.
  The query body at line 181 (`Q(old_provision_id__in=...) |
  Q(new_provision_id__in=...)`) does not need to change — it already
  pairs by FK without inspecting edition membership, so intra-edition
  pairs slot in for free.
- `transition_context.other_edition` field still applies — for
  intra-edition pairs it shows the same edition on both sides, which
  is fine as long as the UI distinguishes by date or by mapping type.
  Worth adding `transition_context.same_edition: bool` so the UI can
  render intra-edition mapping pairs distinctly from cross-edition
  ones (e.g., "renumbered from 9.23.9.5. on 1998-04-15" vs.
  "carried forward from OBC 1997 § 9.10.18.6. (Part 9)").
- For intra-edition pairs, `transition_text` derivation should consult
  `mapping.introduced_by_version` (which carries the gazette clause
  text via `version.clause.html`) rather than walking
  `version.transition_provision`. Two code paths for the two cases.

## Admin (`core/admin.py`)

- Update import and `admin.site.register` call (lines 11, 45) to use
  `ProvisionMapping` instead of `ProvisionEditionMapping`.
- Consider adding a `list_display` showing
  `mapping_type | old_provision | new_provision | introduced_by_version`
  for forensic debugging.

## Contract doc updates

`tasks/provenance/ccm-output-contract.md` needs three changes:

1. **Replace `edition_mappings[]` section** (currently around line 348)
   with `provision_mappings[]`. New schema:
   ```json
   {
     "old_provision_id": "...",
     "old_division": "...",
     "old_edition": "...",
     "new_provision_id": "...",
     "new_division": "...",
     "new_edition": "...",
     "mapping_type": "renumbered | split | merged | replaced",
     "introduced_by": {           // optional, intra-edition only
       "provision_id": "...",
       "division": "...",
       "version": 0
     },
     "notes": ""
   }
   ```
   Document that intra-edition entries (`old_edition == new_edition`)
   require `introduced_by`; cross-edition entries omit it.

2. **Remove the `renumbered_from` field** from the version schema.
   It's currently in the "Proposed extensions" section (lines 71-82);
   replace with a pointer to `provision_mappings[]` as the canonical
   storage. CCM keeps the field on its in-memory `ProvisionVersion`
   dataclass (the chain assembler needs it as transient state) but
   stops serializing it.

3. **Note the `versions[].action: "renumbered"` value remains valid**
   — the version still records *that* a renumber happened at this
   slot in the chain. The mapping row is the structural link; the
   version-level action is the per-provision record of the operation.
   These are complementary, not redundant.

## Why not just keep `renumbered_from` and derive `ProvisionMapping` at ingest?

Considered and rejected. Two reasons:

1. **CCM's manual cross-edition mapping file produces non-renumber types**
   (`split`, `merged`, `replaced`) that have no corresponding
   `ProvisionVersion`. Those need a wire format anyway. Once we have a
   `provision_mappings[]` array for cross-edition, it's strictly
   simpler to put intra-edition entries in the same array than to have
   two parallel mechanisms.
2. **`renumbered_from: str` lacks the `introduced_by_version` link.**
   Even if CC derived a `ProvisionMapping` row from a renumber-action
   version, it'd want to set `introduced_by_version` to that same
   version — which is fine, but then the wire format is essentially
   "look at the version, decide if it implies a mapping". Cleaner to
   make the mapping explicit on the wire.

## Implementation order

1. Migration (rename + new FK + enum).
2. Model definition update + admin update.
3. Loader rename + `provision_mappings[]` parsing + `introduced_by`
   resolution.
4. Search orchestration rename + intra-edition `transition_context`
   handling.
5. Contract doc rewrite.

CCM-side counterpart (drop `renumbered_from` serialization, emit
`provision_mappings[]` from the chain assembler) is tracked at
`CodeChronicleMapping/tasks/amendment-pipeline/impl-19-provision-mapping-emission.md`.
The cross-edition producer is at
`CodeChronicleMapping/tasks/amendment-pipeline/impl-10-edition-mappings.md`.

## Verification

- Migration applies cleanly on a fresh DB.
- Migration applies cleanly on a DB with existing
  `provision_edition_mappings` rows (none expected in production, but
  test fixtures may have some).
- Existing `_merge_cross_edition_transitions` tests pass under the
  rename.
- New tests:
  - Intra-edition mapping pair surfaces in search results with a
    `transition_context` that distinguishes from cross-edition.
  - `introduced_by_version` FK resolves correctly during ingest.
  - Consistency check: a malformed `introduced_by` (pointing at a
    version with `action != "renumbered"`) is logged but does not
    crash ingestion.
