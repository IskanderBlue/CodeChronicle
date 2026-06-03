# 1 — Schema Changes and Backfill

## What

Create the `Transition` model (commencement), the `Amendment` model
(amendment history), add `CodeMap.edition` FK, rename `ProvinceCodeMap` →
`ProvinceCodeSystem`, and backfill existing data.

## Transition Model (Commencement)

Answers "when did this come into force, and says who?"

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

**Node-level Transition semantics:** A node with its own Transition has a
non-default commencement (came into force on a different date than the edition
default). Nodes without their own Transition inherit from the edition-level
Transition. This is a single-value relationship per node per map version —
use `node.transitions.first()` or fall back to `edition.transitions`.

## Amendment Model

Answers "which regulation put this text here?" Full chain, most recent first.

```python
class Amendment(models.Model):
    """A regulation that introduced or modified a provision's text."""

    node = models.ForeignKey(
        CodeMapNode, on_delete=models.CASCADE, related_name="amendments"
    )

    # Source document
    regulation = models.CharField(max_length=200)
    source_url = models.CharField(max_length=500, blank=True, default="")

    # Which section of the amending regulation modified this provision
    provision_id = models.CharField(max_length=200, blank=True, default="")

    # When this amendment took effect
    effective_date = models.DateField()

    # Ordering: 0 = most recent, 1 = second most recent, etc.
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "amendments"
        ordering = ["order"]
        indexes = [
            models.Index(fields=["node", "order"]),
            models.Index(fields=["regulation"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["node", "order"],
                name="amendment_node_order_unique",
            ),
        ]
```

**Why a separate model (not Transition)?** Commencement and amendment are
different legal events. A provision can be *amended* by O. Reg. 139/17
but *commenced* per O. Reg. 332/12 s. 4.4.1.1(2). Mixing them in one
table would require a type discriminator and make queries less clear.

**Why ordered, not dated?** Multiple amendments can share an effective_date
(e.g., two regulations amending the same section on the same day). The
`order` field preserves the intended display sequence: most recent first.

**Base regulation provisions:** Sections that were in the original
regulation and never amended have **no Amendment records**. The UI shows
no amendment annotation for these — they're the default case.

**`jurisdiction` semantics (Transition):**
- Provincial codes (OBC, BCBC, ABC): `jurisdiction=""` — implied by CodeSystem
- National codes (NBC, NPC, NFC): `jurisdiction=""` for NRC publication;
  `jurisdiction="SK"` etc. for provincial adoption
- Query: `jurisdiction__in=["", province]` gets publication + province-specific

**`affected_provisions` note (Transition):** `section_id` requires `division`
to be unique (e.g., `1.1.1.1.` exists in multiple divisions). Matches the
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
2. Create `Amendment` model
3. Rename `ProvinceCodeMap` → `ProvinceCodeSystem`
4. Add `CodeMap.edition` FK (nullable initially)
5. Add `CodeMap.pdf_file`, `CodeMap.download_url`
6. Run data migration:
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
   g. Create node-level `Transition` records from map JSON
      `section.commencement` (CCM-produced per-section commencement).
   h. Create `Amendment` records from map JSON `section.amendments`
      (CCM-produced per-section amendment chain). Most recent first
      → `order=0`, second → `order=1`, etc.

## Verification

- Every `CodeEdition` has at least one `Transition` record
- Every `CodeMap` has an `edition` FK set
- Every `transitions.json` entry has a corresponding `Transition` record
- Every `CodeMapNode` with `provision_transitions` has corresponding
  `Transition` records with `node` FK set
- XOR constraint: no Transition has both edition and node set
- `Amendment` records are ordered correctly (order=0 is most recent)
- Nodes from base regulation have no `Amendment` records

## Notes

- Old fields are NOT removed in this step — that's task 3
- Both old and new code paths work during the transition period
- `Amendment` records are only created when CCM provides `amendments`
  data in map JSON — not backfilled from `metadata.json` (which only
  has edition-level amendment lists, not per-section)
