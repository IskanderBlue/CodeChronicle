# 1 — Schema: New Models

## What

Create the provenance model set, adopting CCM's design wholesale. Drop-in
replacement for the old CodeMapNode + planned Transition/Amendment models.

## Models

### Regulation

An Ontario regulation — base code enactment or amendment.

```python
class Regulation(models.Model):
    class Role(models.TextChoices):
        BASE = "base", "Base"
        AMENDMENT = "amendment", "Amendment"

    reg_id = models.CharField(max_length=50, unique=True)  # "22/98", "403/97"
    edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="regulations"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    amends = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="amended_by",
    )
    filed_date = models.DateField(null=True, blank=True)
    effective_date = models.DateField()
    source_pdf = models.CharField(max_length=200, blank=True, default="")
    source_pages = models.JSONField(null=True, blank=True)  # [29, 51]

    class Meta:
        db_table = "regulations"
        indexes = [
            models.Index(fields=["edition", "effective_date"]),
        ]
```

`reg_id` is globally unique — Ontario regulation numbers are not reused.

### RegulationClause

A single amendment directive within a regulation.

```python
class RegulationClause(models.Model):
    class Action(models.TextChoices):
        REVOKE_AND_SUBSTITUTE = "revoke_and_substitute", "Revoke and substitute"
        AMEND_ADD = "amend_add", "Amend by adding"
        AMEND_STRIKE_SUB = "amend_strike_sub", "Amend by striking and substituting"
        REVOKE = "revoke", "Revoke"

    class TargetLevel(models.TextChoices):
        ARTICLE = "article", "Article"
        SENTENCE = "sentence", "Sentence"
        CLAUSE = "clause", "Clause"
        SUBCLAUSE = "subclause", "Subclause"
        SUBSECTION = "subsection", "Subsection"
        SECTION = "section", "Section"
        PART = "part", "Part"
        TABLE = "table", "Table"
        # No "regulation" level — "The Regulation is amended by adding
        # the following Part" uses target_level="part" with empty target_id

    regulation = models.ForeignKey(
        Regulation, on_delete=models.CASCADE, related_name="clauses"
    )
    clause_id = models.CharField(max_length=50)  # "1.(1)", "9", "38"
    parent_clause = models.CharField(max_length=50, blank=True, default="")
    action = models.CharField(max_length=50, choices=Action.choices)
    target_level = models.CharField(
        max_length=50, choices=TargetLevel.choices, blank=True, default=""
    )
    target_id = models.CharField(max_length=200, blank=True, default="")
        # "1.1.3.2.", "9.10.18.6.(1)"
    clause_text = models.TextField(blank=True, default="")
        # The directive text from the gazette, e.g.:
        # "The definitions of 'Alternative measure'... in Article 1.1.3.2.
        #  of the Regulation are revoked and the following substituted"
    strike_text = models.TextField(null=True, blank=True)
    sub_text = models.TextField(null=True, blank=True)
    page = models.IntegerField(null=True, blank=True)
    bbox = models.JSONField(null=True, blank=True)
    overlay = models.JSONField(null=True, blank=True)
        # For table amendments: {base_coverage, replacement_source}

    class Meta:
        db_table = "regulation_clauses"
        indexes = [
            models.Index(fields=["regulation"]),
            models.Index(fields=["target_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["regulation", "clause_id"],
                name="clause_regulation_clause_id_unique",
            ),
        ]
```

`target_level` includes `table` because amendment directives can target
tables directly ("Table 2.5.1.1. is amended by..."). The clause resolves
to the parent provision for versioning.

`clause_text` is the gazette directive text, populated by CCM's amendment
parser.

### CodeEditionProvision

Structural identity of a provision within an edition. No content — that
lives on versions.

```python
class CodeEditionProvision(models.Model):
    class Level(models.TextChoices):
        DIVISION = "division", "Division"
        PART = "part", "Part"
        SECTION = "section", "Section"
        SUBSECTION = "subsection", "Subsection"
        ARTICLE = "article", "Article"
        SENTENCE = "sentence", "Sentence"
        CLAUSE = "clause", "Clause"

    edition = models.ForeignKey(
        CodeEdition, on_delete=models.CASCADE, related_name="provisions"
    )
    provision_id = models.CharField(max_length=200)  # "1.1.3.2."
    level = models.CharField(max_length=20, choices=Level.choices)
    division = models.CharField(max_length=50, blank=True, default="")
    parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.CASCADE, related_name="children",
    )
    appendix_of = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="appendix_entries",
    )
    version_count = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "code_edition_provisions"
        constraints = [
            models.UniqueConstraint(
                fields=["edition", "provision_id", "division"],
                name="provision_edition_id_division_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["edition", "division", "provision_id"]),
            models.Index(fields=["parent"]),
        ]
```

No `table` level — tables are content within provisions, not provisions
themselves. See `ProvisionVersionTable`.

`sentence` and `clause` levels are used by appendix provisions
(e.g., `A-1.1.1.1.(2)` is sentence-level, `A-3.2.2.9.(1)(a)` is
clause-level). Body provisions collapse sub-article IDs into the parent
article during tree building, but appendix notes are standalone entries
at these levels.

### CodeEditionProvisionVersion

The core entity. A frozen snapshot of a provision's content at a specific
point in the amendment chain.

```python
class CodeEditionProvisionVersion(models.Model):
    class Action(models.TextChoices):
        ORIGINAL = "original", "Original"
        ADDED = "added", "Added"
        REVOKE_AND_SUBSTITUTE = "revoke_and_substitute", "Revoke and substitute"
        AMEND_ADD = "amend_add", "Amend by adding"
        AMEND_STRIKE_SUB = "amend_strike_sub", "Amend by striking and substituting"
        REVOKED = "revoked", "Revoked"

    provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveSmallIntegerField(default=0)
        # 0 = original, 1+ = amendments
    clause = models.ForeignKey(
        RegulationClause, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="provision_versions",
    )
    action = models.CharField(max_length=50, choices=Action.choices,
                              default=Action.ORIGINAL)
    effective_date = models.DateField()
    ineffective_date = models.DateField(null=True, blank=True)
        # null = still in force (edition not revoked, no later amendment)
    transition_provision = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="transition_targets",
    )
        # FK to Div C / Part 12 provision version defining transition terms

    # Content
    title = models.CharField(max_length=500, blank=True, default="")
    html = models.TextField(blank=True, default="")
    page_images = models.JSONField(null=True, blank=True)
        # List of {image, bboxes} objects:
        #   [{"image": "documents/obc_1997_v3.pdf/42.webp",
        #     "bboxes": [{"l": 50, "t": 400, "r": 380, "b": 120},
        #                {"l": 400, "t": 30, "r": 750, "b": 350}]}]
        # Multiple bboxes per page (column flow). Multiple entries for
        # provisions spanning pages.

    # Search support
    keyword_counts = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "code_edition_provision_versions"
        ordering = ["version"]
        constraints = [
            models.UniqueConstraint(
                fields=["provision", "version"],
                name="version_provision_version_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["provision", "effective_date"],
            ),
            models.Index(fields=["clause"]),
            models.Index(
                fields=["effective_date", "ineffective_date"],
            ),
        ]
```

### ProvisionVersionTable

Table content associated with a provision version. Separate model for
proper FK relationships and queryability.

```python
class ProvisionVersionTable(models.Model):
    version = models.ForeignKey(
        CodeEditionProvisionVersion, on_delete=models.CASCADE,
        related_name="tables",
    )
    table_id = models.CharField(max_length=200)  # "Table-3.1.4.7."
    caption = models.CharField(max_length=500, blank=True, default="")
    images = models.JSONField(default=list)
        # Source document pages or pre-composited amended images
    notes = models.TextField(blank=True, default="")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "provision_version_tables"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "table_id"],
                name="table_version_table_id_unique",
            ),
        ]
```

### CodeEdition changes

```python
class CodeEdition(models.Model):
    system = models.ForeignKey(Code, on_delete=models.CASCADE, related_name="editions")
    edition_id = models.CharField(max_length=50)
    year = models.IntegerField()
    effective_date = models.DateField()
    ineffective_date = models.DateField(null=True, blank=True)
        # null = still in force. Consistent with provision version naming.
    amendment_chain_complete = models.BooleanField(default=False)

    # Dropped in task 5 (kept during transition):
    # map_codes, pdf_files, download_url, regulation (CharField),
    # superseded_date, amendments, amendments_applied
```

No `base_regulation` or `revoked_by` FK — the base regulation is
`edition.regulations.get(role="base")` and the revoking regulation is
the next edition's base regulation. Both are always available via the
prefetched regulation set.

### ProvinceCode rename

```python
class ProvinceCode(models.Model):
    province = models.CharField(max_length=2, unique=True)
    code = models.ForeignKey(
        Code, on_delete=models.CASCADE, related_name="provinces"
    )
```

Rename of `ProvinceCodeMap`. `Code` is the rename of `CodeSystem`.
Maps province codes ("ON") to code systems ("OBC"). Used in
`get_applicable_codes()` for the multi-province case.

### ProvisionEditionMapping

Cross-edition provision identity mapping.

```python
class ProvisionEditionMapping(models.Model):
    old_provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE,
        related_name="mapped_forward",
    )
    new_provision = models.ForeignKey(
        CodeEditionProvision, on_delete=models.CASCADE,
        related_name="mapped_back",
    )
    mapping_type = models.CharField(max_length=20)
        # "renamed", "split", "merged", "replaced", "removed"
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "provision_edition_mappings"
        constraints = [
            models.UniqueConstraint(
                fields=["old_provision", "new_provision"],
                name="provision_mapping_unique",
            ),
        ]
```

## Rename: CodeSystem → Code

`CodeSystem` becomes `Code`. `db_table` renamed from `code_systems` to
`codes` for clarity.

## Migration Steps

1. Rename `CodeSystem` → `Code` (model + table), `ProvinceCodeMap` →
   `ProvinceCode`
2. Create `Regulation`
3. Create `RegulationClause`
4. Create `CodeEditionProvision`
5. Create `CodeEditionProvisionVersion`
6. Create `ProvisionVersionTable`
7. Create `ProvisionEditionMapping`
8. Add `CodeEdition.ineffective_date`, `amendment_chain_complete`

No data migration from existing models. All data comes fresh from CCM
via the `load_edition` command (task 2).

## Verification

- All new models created and migrated
- Enum values match CCM output contract
- `reg_id` is unique (not per-edition)
- Old models still exist (dropped in task 5)
- `RegulationClause` table empty until CCM data loaded

## Notes

- Old models (`CodeMap`, `CodeMapNode`) are NOT dropped here — task 5
- No data migration from existing data — all populated by CCM
