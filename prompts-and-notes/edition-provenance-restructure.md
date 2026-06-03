# Edition Provenance & Model Restructure

**Broken into tasks at `prompts-and-notes/transitions/`** — see:

- [00-overview.md](transitions/00-overview.md) — problems, core idea, model summary
- [1-schema-and-backfill.md](transitions/1-schema-and-backfill.md) — Transition model, CodeMap FK, ProvinceCodeSystem rename, migration
- [2-update-code-paths.md](transitions/2-update-code-paths.md) — rewrite queries, orchestration, formatters
- [3-remove-old-fields.md](transitions/3-remove-old-fields.md) — drop redundant fields and files
- [4-template-provenance.md](transitions/4-template-provenance.md) — UI for quotes, uncommenced warnings

Data population: `CodeChronicleMapping/tasks/transitions/`

---

## Problem

1. **No provenance** — `CodeEdition.effective_date` and `superseded_date` are bare
   dates with no link to the regulation or provision that established them. Users
   can't verify *why* a particular edition is in force on a given date.

2. **CodeMap vs CodeEdition confusion** — `CodeMap` is a loaded JSON file;
   `CodeEdition` is a legal edition. They're linked by a stringly-typed
   `map_codes` ArrayField instead of a foreign key. Physical-file fields
   (`pdf_files`, `download_url`) are on `CodeEdition` where they don't belong.

3. **Transition data lacks real citations** — `transitions.json` has hand-written
   `citation_text` and `applicability_text` summaries. No actual quoted provision
   text, no structured source document reference, no URL.

4. **`amendments` vs `amendments_applied`** — `CodeEdition.amendments` stores the
   legislative composition of an edition but is never consumed by any code.
   Confusingly named alongside `amendments_applied`.

5. **Scattered date/regulation fields** — `CodeEdition.effective_date`,
   `superseded_date`, `regulation`, `source_url` are all aspects of "what
   provision puts this edition in/out of force" but stored as disconnected
   fields with no link to the source provision or its text.

6. **Three names for one concept** — edition in-force dates, provision
   commencement dates, and grandfathered overlap periods are all the same
   thing: a provision of law says "X is in force from date A to date B."
   The current design treats them as separate concepts with separate schemas.

7. **`ProvinceCodeMap` misnomer** — `ProvinceCodeMap` maps province → `CodeSystem`
   (e.g., ON → OBC). That's a system-level relationship, not a map-level one.
   Should be `ProvinceCodeSystem`. A real `ProvinceCodeMap` would resolve which
   specific edition/map is in force in a province — but that's now derived from
   `Transition` records filtered by jurisdiction.

8. **National codes have no jurisdiction-aware in-force model** — NBC is
   published once by NRC but adopted on different dates by different provinces,
   each through a different legal instrument. The current model has no way to
   represent "NBC 2025 is in force in Saskatchewan since date X per ministerial
   order Y, and in Manitoba since date Z per order in council W."

---

## Core Idea: Transition Model

Every date-bounded legal state — "this edition is in force," "this provision
commences later," "the old edition is grandfathered" — is a **Transition**.

A `Transition` is the answer to "says who?" It carries:
- The source document and specific provision
- The actual quoted text of that provision
- The effective date and end date
- What it applies to (an edition or a specific provision)
- Which jurisdiction it applies in (for national codes adopted by provinces)

One model. One table. Different FK relationships express what each transition
applies to. Jurisdiction scoping handles national codes that come into force
on different dates in different provinces.

---

## Model Changes

### 1. Transition — the provenance record

```python
class Transition(models.Model):
    """A provision of law that establishes when something is in force."""

    # Source document
    regulation = models.CharField(max_length=200)
        # e.g., "O. Reg. 332/12", "O. Reg. 139/17"
    source_url = models.CharField(max_length=500, blank=True, default="")
        # e.g., "https://www.ontario.ca/laws/regulation/120332"

    # Provision within the document
    provision_id = models.CharField(max_length=200)
        # e.g., "Div C, s. 4.1.4", "s. 140(1)"
    provision_quote = models.TextField(blank=True, default="")
        # The actual statutory text

    # When this legal state applies
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
        # null = still in effect

    # What it applies to — one of these is set:

    # Edition-level: "this edition is in force from/until..."
    edition = models.ForeignKey(
        CodeEdition, null=True, blank=True,
        on_delete=models.CASCADE, related_name="transitions"
    )

    # Provision-level: "this specific provision has a different rule..."
    node = models.ForeignKey(
        CodeMapNode, null=True, blank=True,
        on_delete=models.CASCADE, related_name="transitions"
    )

    # For provision-scoped edition transitions: which provisions are affected
    # (only used when edition is set and scope is "provisions")
    scope = models.CharField(
        max_length=20, default="whole_code",
        choices=[("whole_code", "whole_code"), ("provisions", "provisions")]
    )
    affected_provisions = models.JSONField(null=True, blank=True)
        # When scope="provisions":
        # [{"section_id": "8.6.2.2.", "division": "B",
        #   "old_provision_ref": "Sentence 8.6.2.2.(5)"},
        #  {"section_id": "Table-1.3.1.2.", "division": "",
        #   "old_provision_ref": "Item 329 of Table 1.3.1.2."}]

    # Jurisdiction (for national codes adopted by multiple provinces)
    jurisdiction = models.CharField(max_length=10, blank=True, default="")
        # Province code: "ON", "SK", "MB", etc.
        # Empty = not jurisdiction-specific (e.g., NRC publication of a model
        # code, or a provincial code where the code system already implies
        # the jurisdiction)

    # Human-friendly summary (optional, for display)
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

**Note on `jurisdiction`:** For provincial codes (OBC, BCBC, ABC), the
jurisdiction is implied by the `CodeSystem` — OBC is Ontario's code, so its
Transitions don't need `jurisdiction` set. For national codes (NBC, NPC,
NFC), each province adopts separately, so the Transition carries the province
code. A Transition with empty `jurisdiction` on a national code represents the
NRC publication itself (not adoption by any province).

"Which edition is in force in province X?" is answered by:
1. `ProvinceCodeSystem`: find which code systems apply to province X
2. `Transition`: filter by `edition__system` + `jurisdiction IN ("", "X")`
   + date range

This replaces the need for a static `ProvinceCodeMap` table — the in-force
mapping is computed from Transition records.

**Note on `affected_provisions`:** `section_id` alone is not unique in the
code — sections like `1.1.1.1.` exist in multiple divisions. The `division`
field disambiguates, matching the `(code_map, node_id, division)` unique
constraint on `CodeMapNode`.

### 2. CodeMap → CodeEdition FK

Replace the `map_codes` ArrayField with a proper foreign key.

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

### 3. ProvinceCodeMap → ProvinceCodeSystem rename

```python
class ProvinceCodeSystem(models.Model):
    """Map a province to its primary code system(s)."""
    province = models.CharField(max_length=2, unique=True)
    code_system = models.ForeignKey(
        CodeSystem, on_delete=models.CASCADE, related_name="provinces"
    )
```

This is a rename only — the model is structurally identical. The old name
suggested it mapped provinces to specific maps or editions; it actually maps
provinces to code *systems* (e.g., ON → OBC). Which specific edition is in
force is now derived from Transition records.

### 4. CodeEdition cleanup

Fields that move to `Transition` or `CodeMap`:

```python
class CodeEdition(models.Model):
    system = models.ForeignKey(CodeSystem, on_delete=models.CASCADE,
                               related_name="editions")
    edition_id = models.CharField(max_length=50)
    year = models.IntegerField()
    version_number = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=50, blank=True, default="")
    amendments_applied = models.JSONField(null=True, blank=True)
    is_guide = models.BooleanField(default=False)

    # --- REMOVED ---
    # effective_date      → derived from edition.transitions (in-force Transition)
    # superseded_date     → derived from edition.transitions (end_date)
    # regulation          → on the Transition record
    # source_url          → on the Transition record
    # map_codes           → replaced by reverse FK (edition.maps.all())
    # pdf_files           → moved to CodeMap.pdf_file
    # download_url        → moved to CodeMap.download_url
    # amendments          → dropped (never consumed; if needed, rename to
    #                       legislative_history)
```

### 5. CodeMapNode — provision_transitions removal

The existing `provision_transitions` JSONField is replaced by `Transition`
records with `node` FK set.

```python
class CodeMapNode(models.Model):
    code_map = models.ForeignKey(CodeMap, on_delete=models.CASCADE,
                                 related_name="nodes")
    node_id = models.CharField(max_length=200)
    division = models.CharField(max_length=10, default="", blank=True)
    ...

    # --- REMOVED ---
    # provision_transitions  → replaced by node.transitions.all()
```

---

## What We Have vs What We're Missing

### Currently populated (will migrate to Transition records)

| Data | Source | Status |
|------|--------|--------|
| Edition effective/superseded dates | `metadata.json`, manually set | Dates exist but **no provenance** — no regulation, provision, or quote |
| Whole-code transition overlaps (OBC) | `transitions.json`, hand-written | Dates and summaries exist but **no real citations** — `citation_text` is editorial, no provision quote |
| Provision-scoped transitions (OBC 2012 v08→v09) | `transitions.json` + `load_maps` stamping | Affected provisions identified but **no provision quote** |
| Transition overlaps (BCBC, QCC, QSC, QPC, QECB) | `transitions.json`, hand-written | Same gap — summaries only, no quotes |

### Missing entirely

| Data | Source needed | Notes |
|------|---------------|-------|
| **In-force provenance** — which commencement provision establishes each edition's effective date | Source regulation filings on e-Laws (`/r{NNNNN}`) | Not yet scraped |
| **Transition provision quotes** — actual text of Div C §4.1.x | Consolidated regulation HTML (already cached) | HTML is cached but Div C Part 4 is not parsed |
| **Per-provision commencement** — grey-background sections that commence on a different date | Consolidated regulation HTML (already cached) | CSS class for uncommenced text not yet identified |
| **Pre-e-Laws commencement/transition provisions** — gazette regulation text | Gazette pipeline output (already parsed) | Currently classified and **discarded** during map assembly |
| **NBC in-force provenance** — what puts a national code edition in force | NRC publication + provincial adoption instruments | Model code has no commencement provision; provinces adopt separately |
| **Provincial adoption provenance** (BC, AB, QC, etc.) — orders in council, ministerial orders | Per-province government sources | Each province has its own instrument type and publication system |
| **OBC 2024 transitions** — new base regulation O. Reg. 163/24 | Consolidated HTML for O. Reg. 163/24 | Not yet cached or investigated |

---

## Query Logic Changes

### Current
```
1. ProvinceCodeMap: province → CodeSystem
2. CodeEdition: effective_date <= search_date AND
                (superseded_date IS NULL OR superseded_date > search_date)
3. transitions.json: filter by date range
```

### Updated
```python
# 1. Find which code systems apply to this province
systems = ProvinceCodeSystem.objects.filter(
    province=province
).values_list("code_system", flat=True)

# Also include national systems
national = CodeSystem.objects.filter(is_national=True)

# 2. Find editions in force — via Transition, jurisdiction-aware
active_transitions = Transition.objects.filter(
    edition__system__in=[*systems, *national],
    scope="whole_code",
    jurisdiction__in=["", province],  # publication + province-specific
    effective_date__lte=search_date,
).filter(
    Q(end_date__isnull=True) | Q(end_date__gt=search_date)
).select_related("edition")
```

Each result carries its Transition records with full provenance:

```python
{
    # All transitions that apply to this result
    "transitions": [
        {
            "regulation": "O. Reg. 139/17",
            "source_url": "https://...",
            "provision_id": "s. 3(1)",
            "provision_quote": "This Regulation comes into force on July 1, 2017.",
            "effective_date": "2017-07-01",
            "end_date": "2018-01-01",
            "scope": "whole_code",
            "jurisdiction": "ON",
            "applicability_text": "..."
        },
        ...
    ]
}
```

For national codes, the result may carry multiple Transitions — the NRC
publication (empty jurisdiction) and the provincial adoption (with
jurisdiction). Both are "show your work" provenance:

> "Published by NRC as NBC 2025. Adopted in Saskatchewan by Ministerial
> Order MSO-123-2025, effective 2025-07-01."

For provision-level results, include both the edition's transitions and any
node-specific transitions from `node.transitions.all()`.

### Transition overlap detection

Currently `get_active_transitions()` reads `transitions.json` and filters by
date. This becomes a database query:

```python
# Find editions where a transition makes the *previous* edition still valid
Transition.objects.filter(
    edition__in=applicable_editions,
    scope="whole_code",
    jurisdiction__in=["", province],
    effective_date__lte=search_date,
    end_date__gt=search_date,  # overlap still active
).select_related("edition")
```

---

## Template Changes

### Provenance display (all result types)

Every search result gets an expandable "Legal basis" section:

- **Header:** "{regulation}, {provision_id}"
- **Body:** blockquote with `provision_quote`
- **Link:** source_url (when available)
- **Dates:** "In force {effective_date}" / "until {end_date}"

### Transition compare view

Same side-by-side diff view as today, but the transition context panel shows
the actual provision quote instead of hand-written citation text.

### Not-yet-commenced provisions

When a node has a `Transition` with `effective_date > search_date`:
- Amber banner: "This provision does not commence until {date}"
- Expandable quote of the commencement provision

---

## Migration Plan

### Phase 1: Add new models, backfill

1. Create `Transition` model with `jurisdiction` field (migration)
2. Rename `ProvinceCodeMap` → `ProvinceCodeSystem` (migration)
3. Add `CodeMap.edition` FK (nullable), `CodeMap.pdf_file`,
   `CodeMap.download_url`
4. Backfill `CodeMap.edition` from `CodeEdition.map_codes`
5. Backfill `CodeMap.pdf_file` from `CodeEdition.pdf_files` dict
6. Backfill `CodeMap.download_url` from `CodeEdition.download_url`
7. Create `Transition` records from existing `CodeEdition` effective/superseded
   dates (provenance fields blank — to be populated later by CCM).
   For provincial codes (OBC, BCBC, etc.): `jurisdiction=""` (implied by
   system). For national codes (NBC, NPC, NFC): `jurisdiction=""` (publication
   only — provincial adoption Transitions added when data is available).
8. Create `Transition` records from existing `transitions.json` entries
   (provenance fields blank — to be populated later by CCM)
9. Create node-level `Transition` records from existing
   `CodeMapNode.provision_transitions` JSONField

### Phase 2: Update code paths

1. Update `load_maps.py` to use `CodeMap.edition` FK
2. Update `load_code_metadata.py` to create `Transition` records instead of
   setting `effective_date`/`superseded_date` on `CodeEdition`
3. Update `orchestration.py` to query `Transition` (with jurisdiction filter)
   instead of `CodeEdition.effective_date` + `transitions.json`
4. Update `code_metadata.py` (`get_applicable_codes`) to use `Transition`
   query with `jurisdiction__in=["", province]`
5. Update `formatters.py` to pass `Transition` fields through
6. Rename `ProvinceCodeMap` → `ProvinceCodeSystem` in all code references
7. Update templates to render provenance

### Phase 3: Remove old fields

1. Make `CodeMap.edition` non-nullable
2. Drop `CodeEdition`: `effective_date`, `superseded_date`, `regulation`,
   `source_url`, `map_codes`, `pdf_files`, `download_url`, `amendments`
3. Drop `CodeMapNode.provision_transitions`
4. Delete `transitions.json` and `transitions.py`

### Phase 4: Populate provenance (CCM work)

See companion document:
`CodeChronicleMapping/tasks/transitions/`
