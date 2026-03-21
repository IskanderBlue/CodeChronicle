# 1 — Schema Changes and Backfill

## What

Create the `Transition` model, add `CodeMap.edition` FK, rename
`ProvinceCodeMap` → `ProvinceCodeSystem`, and backfill existing data.

## Transition Model

```python
class Transition(models.Model):
    """A provision of law that establishes when something is in force."""

    # Source document
    regulation = models.CharField(max_length=200)
    source_url = models.CharField(max_length=500, blank=True, default="")

    # Provision within the document
    provision_id = models.CharField(max_length=200)
    provision_quote = models.TextField(blank=True, default="")

    # When this legal state applies
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)  # null = still in effect

    # What it applies to — exactly one of these is set:
    edition = models.ForeignKey(
        CodeEdition, null=True, blank=True,
        on_delete=models.CASCADE, related_name="transitions"
    )
    node = models.ForeignKey(
        CodeMapNode, null=True, blank=True,
        on_delete=models.CASCADE, related_name="transitions"
    )

    # For provision-scoped edition transitions
    scope = models.CharField(
        max_length=20, default="whole_code",
        choices=[("whole_code", "whole_code"), ("provisions", "provisions")]
    )
    affected_provisions = models.JSONField(null=True, blank=True)
        # [{"section_id": "8.6.2.2.", "division": "B",
        #   "old_provision_ref": "Sentence 8.6.2.2.(5)"}]

    # Jurisdiction (for national codes adopted by multiple provinces)
    jurisdiction = models.CharField(max_length=10, blank=True, default="")
        # "ON", "SK", "MB", etc. Empty = not jurisdiction-specific.

    # Human-friendly summary
    applicability_text = models.TextField(blank=True, default="")

    class Meta:
        db_table = "transitions"
        indexes = [
            models.Index(fields=["edition", "jurisdiction", "effective_date"]),
            models.Index(fields=["node"]),
            models.Index(fields=["regulation"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(edition__isnull=False, node__isnull=True)
                    | models.Q(edition__isnull=True, node__isnull=False)
                ),
                name="transition_edition_xor_node",
            ),
        ]
```

**`jurisdiction` semantics:**
- Provincial codes (OBC, BCBC, ABC): `jurisdiction=""` — implied by CodeSystem
- National codes (NBC, NPC, NFC): `jurisdiction=""` for NRC publication;
  `jurisdiction="SK"` etc. for provincial adoption
- Query: `jurisdiction__in=["", province]` gets publication + province-specific

**`affected_provisions` note:** `section_id` requires `division` to be unique
(e.g., `1.1.1.1.` exists in multiple divisions). Matches the
`(code_map, node_id, division)` constraint on `CodeMapNode`.

## CodeMap FK

```python
class CodeMap(models.Model):
    edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="maps"
    )
    map_code = models.CharField(max_length=100, unique=True)
    pdf_file = models.CharField(max_length=200, blank=True, default="")
    download_url = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

## ProvinceCodeSystem rename

```python
class ProvinceCodeSystem(models.Model):
    """Map a province to its primary code system(s)."""
    province = models.CharField(max_length=2, unique=True)
    code_system = models.ForeignKey(
        CodeSystem, on_delete=models.CASCADE, related_name="provinces"
    )
```

Rename only — structurally identical to current `ProvinceCodeMap`.

## Migration Steps

1. Create `Transition` model
2. Rename `ProvinceCodeMap` → `ProvinceCodeSystem`
3. Add `CodeMap.edition` FK (nullable initially)
4. Add `CodeMap.pdf_file`, `CodeMap.download_url`
5. Run data migration:
   a. Backfill `CodeMap.edition` from `CodeEdition.map_codes` array
   b. Backfill `CodeMap.pdf_file` from `CodeEdition.pdf_files` dict
   c. Backfill `CodeMap.download_url` from `CodeEdition.download_url`
   d. Create edition-level `Transition` records from `CodeEdition`
      effective/superseded dates. Provenance fields (`provision_id`,
      `provision_quote`) left blank — populated later by CCM.
      `jurisdiction=""` for all (provincial implied by system; national =
      publication only).
   e. Create `Transition` records from `transitions.json` entries.
      Provenance fields left blank.
   f. Create node-level `Transition` records from
      `CodeMapNode.provision_transitions` JSONField.

## Verification

- Every `CodeEdition` has at least one `Transition` record
- Every `CodeMap` has an `edition` FK set
- Every `transitions.json` entry has a corresponding `Transition` record
- Every `CodeMapNode` with `provision_transitions` has corresponding
  `Transition` records with `node` FK set
- XOR constraint: no Transition has both edition and node set

## Notes

- Old fields are NOT removed in this step — that's task 3
- Both old and new code paths work during the transition period
