# CCM Output Contract

What CodeChronicle expects from CodeChronicleMapping's pipeline output.
This is the interface between the two repos.

## Output: One JSON per Edition

CCM produces one consolidated JSON file per code edition. Example:
`OBC_1997.json`. This file contains everything CodeChronicle needs to
populate its provenance models for that edition.

## Top-Level Schema

```json
{
  "code": "OBC",
  "edition": "1997",
  "effective_date": "1998-04-06",
  "ineffective_date": "2006-12-31",
  "amendment_chain_complete": true,

  "regulations": [ ... ],
  "provisions": [ ... ],
  "provision_mappings": [ ... ]
}
```

No `base_regulation` or `revoked_by` at the top level — these are
identified from the regulations array by `role: "base"` and by the next
edition's base regulation respectively.

## `regulations[]`

All regulations for this edition (base + amendments), ordered by
effective date then filing date.

```json
{
  "reg_id": "403/97",
  "role": "base",
  "amends": null,
  "filed_date": "1997-11-03",
  "effective_date": "1998-04-06",
  "source_pdf": "ont_reg_1997_v3.pdf",
  "source_pages": [1, 400],
  "clauses": []
}
```

```json
{
  "reg_id": "22/98",
  "role": "amendment",
  "amends": "403/97",
  "filed_date": "1998-01-27",
  "effective_date": "1998-04-06",
  "source_pdf": "ont_reg_1998_v1.pdf",
  "source_pages": [29, 51],
  "clauses": [
    {
      "clause_id": "1.(1)",
      "parent_clause": "1",
      "action": "revoke_and_substitute",
      "target_level": "article",
      "target_id": "1.1.3.2.",
      "clause_text": "The definitions of 'Alternative measure'...",
      "strike_text": null,
      "sub_text": null,
      "page": 29,
      "bbox": {"l": 194, "t": 625, "r": 366, "b": 30},
      "overlay": null
    }
  ]
}
```

### `clauses[].action` values

| Value | Meaning |
|-------|---------|
| `revoke_and_substitute` | Replace target entirely with payload |
| `amend_add` | Add content to/after target |
| `amend_strike_sub` | Find and replace text in target |
| `revoke` | Remove target |
| `renumber` | Re-id target (pairs with a `provision_mappings[]` entry) |

### `clauses[].target_level` values

| Value | Meaning |
|-------|---------|
| `article` | Article (e.g., 1.1.3.2.) |
| `sentence` | Sentence within an article (e.g., 9.10.18.6.(1)) |
| `clause` | Clause within a sentence (e.g., 3.2.2.9.(1)(a)) |
| `subclause` | Subclause (e.g., 2.1.1.2.(1)(a)(ii)) |
| `subsection` | Subsection (e.g., 9.33.2.) |
| `section` | Section (e.g., 2.11.) |
| `part` | Part (e.g., 2) |
| `table` | Table (e.g., Table-2.5.1.1.) |

`table` is a valid target level for clauses because gazette directives
target tables directly. The clause resolves to the parent provision for
versioning — CodeChronicle handles this during ingestion.

### `clauses[].clause_text`

The directive text from the gazette, verbatim. E.g.:

> "The definitions of 'Alternative measure', 'Private sewage disposal
> system' and 'Sewage system' in Article 1.1.3.2. of the Regulation are
> revoked and the following substituted"

### `clauses[].overlay`

For table amendments with structural changes (column/row replacement),
an overlay descriptor. Null for non-table amendments.

```json
{
  "base_coverage": {
    "pages": [28, 29, 30],
    "column_x_ranges": [
      {"label": "Peterborough", "x0": 339, "x1": 347}
    ]
  },
  "replacement_source": {
    "pdf": "ont_reg_1998_v1.pdf",
    "page": 32,
    "grid_bbox": {"l": 194.5, "t": 625.5, "r": 366.0, "b": 30.5}
  }
}
```

CodeChronicle does not use this at runtime — it's consumed by the image
pre-compositor during ingest. Stored on `RegulationClause.overlay` for
reference.

## `provisions[]`

All provisions in the edition with their complete version chain.

Provision bboxes encompass the provision text plus any associated tables.

```json
{
  "provision_id": "1.1.3.2.",
  "level": "article",
  "division": "Division A",
  "parent_id": "1.1.3.",
  "appendix_of_id": null,

  "versions": [
    {
      "version": 0,
      "clauses": [],
      "effective_date": "1998-04-06",
      "ineffective_date": "1998-04-06",
      "transition_provision_id": null,

      "title": "Definitions",
      "html": "<p>In this Code,</p><p>...</p>",
      "page_images": [
        {"image": "documents/obc_1997_v2.pdf/42.webp", "bboxes": [{"l": 50, "t": 200, "r": 380, "b": 80}]}
      ],
      "keyword_counts": {"fire": 3, "safety": 1},

      "tables": []
    },
    {
      "version": 1,
      "clauses": [
        {"regulation": "22/98", "clause_id": "1.(1)"}
      ],
      "effective_date": "1998-04-06",
      "ineffective_date": null,
      "transition_provision_id": null,

      "title": "Definitions",
      "html": "<p>In this Code,</p><p>...amended...</p>",
      "page_images": [],
      "keyword_counts": {"fire": 3, "safety": 1, "sewage": 2},

      "tables": []
    }
  ]
}
```

Note v0's `ineffective_date` equalling its `effective_date` — a
zero-width window. Emitted whenever the first amendment on a
provision falls on the same date as the base edition's effective
date (common: day-zero amendments filed simultaneously with the
base regulation). Preserves the "as-filed" snapshot without
claiming it was ever in force. Consumers that only want in-force
windows can filter `v.ineffective_date == v.effective_date`.

### Appendix provision example

```json
{
  "provision_id": "A-1.1.3.2.(1)",
  "level": "sentence",
  "division": "Division A",
  "parent_id": "A-1.1.3.2.",
  "appendix_of_id": "1.1.3.2.",

  "versions": [
    {
      "version": 0,
      "clauses": [],
      "effective_date": "1998-04-06",
      "ineffective_date": null,
      "transition_provision_id": null,

      "title": "",
      "html": "<p>The OBC applies to both site-built and...</p>",
      "page_images": [
        {"image": "documents/obc_1997_appendix.pdf/12.webp", "bboxes": [{"l": 50, "t": 300, "r": 380, "b": 200}]}
      ],
      "keyword_counts": {},

      "tables": []
    }
  ]
}
```

**`appendix_of_id`**: The `provision_id` of the body provision this note
annotates. CodeChronicle resolves this to a `CodeEditionProvision` FK
during ingestion. Body provision and appendix provision must be in the
same edition.

Appendix provisions have their own version chains — they can be
independently amended. `parent_id` is the structural parent in the
appendix tree (e.g., `A-1.1.3.2.` for sentence `A-1.1.3.2.(1)`),
while `appendix_of_id` links across to the body tree.

### `provisions[].level` values

| Value | Meaning |
|-------|---------|
| `division` | Division |
| `part` | Part |
| `section` | Section |
| `subsection` | Subsection |
| `article` | Article |
| `sentence` | Sentence (appendix provisions, e.g. `A-1.1.1.1.(2)`) |
| `clause` | Clause (appendix provisions, e.g. `A-3.2.2.9.(1)(a)`) |

No `table` level — tables are content within provisions. `sentence` and
`clause` levels are used by appendix provisions only — body provisions
collapse sub-article IDs into the parent article.

### Version-level `action` is not stored

Versions do not carry a version-level `action` field. Where a kind-
of-change label is needed, it is **derived** from the version's
contributing clauses:

| Semantic | Derivation |
|----------|------------|
| "original" | `version == 0 AND clauses == []` |
| "added"    | `version == 0 AND any clause has `action == "amend_add"` whose `directives[]` creates this provision id` |
| "revoked"  | Any contributing clause has `action == "revoke"` |
| "renumbered" (new id) | A `provision_mappings[]` entry points its `introduced_by.version` at this version |
| Other kinds (revoke_and_substitute, amend_strike_sub, amend_add content-only) | Inspect contributing clauses' actions directly |

Fine-grained amendment intent lives on `RegulationClause.action`,
which is where it belongs — per clause, not per version (a single
version can aggregate clauses of different kinds; see below).

### `versions[].clauses[]`

The list of gazette clauses that contributed to this version, in
application order. Each entry references a clause on a regulation
elsewhere in `regulations[]`.

```json
"clauses": [
  {"regulation": "22/98", "clause_id": "18"},
  {"regulation": "122/98", "clause_id": "2.(1)"},
  {"regulation": "122/98", "clause_id": "2.(2)"}
]
```

- `version == 0` base originals emit `clauses: []`.
- `version == 0` amend-add-created provisions emit the single
  creating clause.
- Every other version emits one entry per clause that applied
  during this version's window.
- Application order is `(regulation.filed_date, clause_id)` — the
  order in which the applicator actually processed them.

CodeChronicle resolves each `(regulation, clause_id)` tuple to a
`RegulationClause` FK during ingestion and stores the list as an
M2M relation on `CodeEditionProvisionVersion`.

### `versions[].effective_date` / `ineffective_date`

**One `ProvisionVersion` per `(provision_id, effective_date)` pair.**
If ten clauses — from any number of regulations — act on one
provision on one date, they collapse into a single version carrying
all ten clause refs in `clauses[]`. Version numbers are a strict
ascending sequence per provision: v0, v1, v2, …  No version-number
collisions, no same-date duplicates.

- `effective_date`: when this version comes into force.
- `ineffective_date`: when this version ceases to be in force. Null
  if this is the current version and the edition is still in force.
- `ineffective_date == effective_date` — a zero-width window — is
  legal and carries the "as-filed but superseded same day" case.
  Typical for v0 of a provision whose first amendment shares the
  base regulation's effective date.
- During a transition period, the old version's `ineffective_date`
  is extended to the overlap end. Both versions have overlapping
  date ranges.

### `versions[].transition_provision_id`

When this version creates a transition period (the previous version
continues to apply for some permits), this is the `provision_id` of the
Division C / Part 12 provision that defines the transition terms.

CodeChronicle resolves this to a `CodeEditionProvisionVersion` FK during
ingestion (the current version of the referenced transition provision).

Null when no transition applies.

### `versions[].page_images`

List of objects, each referencing a full page image plus a bbox defining
the provision's region on that page. Provisions that span columns or
pages have multiple entries in reading order.

```json
"page_images": [
  {
    "image": "documents/obc_1997_v3.pdf/143.webp",
    "bboxes": [
      {"l": 50, "t": 400, "r": 380, "b": 120},
      {"l": 400, "t": 30, "r": 750, "b": 350}
    ]
  }
]
```

- `image`: S3 path to the full page image (shared across provisions on
  the same page).
- `bboxes`: list of `{l, t, r, b}` regions on that page, in reading
  order. Multiple bboxes handle provisions that flow across columns
  (e.g., starts bottom of left column, continues top of right column).
  The frontend shows each bbox as a separate cropped region by default.
  "View full page" shows the uncropped image with all bboxes highlighted.

Multiple entries in `page_images` handle provisions spanning pages.
Each entry is one page; bboxes within that entry are column regions.

Empty list when no page images exist (HTML-only amended provisions).

### `versions[].tables[]`

Tables belonging to this provision at this version.

```json
{
  "table_id": "Table-3.1.4.7.",
  "caption": "Fire Resistance Ratings",
  "images": [
    {"image": "documents/obc_1997_v2.pdf/143.webp", "bboxes": [{"l": 50, "t": 100, "r": 750, "b": 30}]},
    {"image": "documents/obc_1997_v2.pdf/144.webp", "bboxes": [{"l": 50, "t": 30, "r": 750, "b": 600}]}
  ],
  "html": "",
  "notes": "Note (1): For buildings of...",
  "order": 0
}
```

- `images`: list of `{image, bboxes}` objects. Same format as
  `page_images` — full page image path + bboxes for the table region.
  For base tables, these are source document pages. For amended tables
  with pre-composited overlays, the `image` path points to the
  composited image (bbox covers the full composited image).
  May be an empty list when `html` is populated and no authoritative
  image form is available for this version.
- `html`: Structured table markup (e.g. `<table>...</table>`) sourced
  from e-Laws when a point-in-time HTML form exists for this version.
  Empty string when unavailable — the renderer falls back to `images`.
  Typically populated for base v0 of e-Laws-sourced editions and the
  latest consolidated version; historical amended versions usually
  stay image-only because e-Laws only publishes current consolidations.
- `notes`: Table notes as text. Notes that were amended have the
  amended text here. When `html` is populated, notes may already be
  embedded in the markup — in that case emit `notes: ""` to avoid
  double-rendering.
- `order`: Display order when a provision has multiple tables.

When a table is amended but its parent provision's text is unchanged,
the parent still gets a new version (with the same `html`) because the
table content changed.

## `provision_mappings[]`

Provision identity mappings — both intra-edition renumbers driven by
gazette directives and cross-edition identity carries. A single unified
array; the two cases are distinguished by whether the old/new editions
match, not by a separate payload shape.

Optional — only present when mapping data exists.

### Intra-edition renumber (introduced by a gazette clause)

```json
{
  "old_provision_id": "9.10.18.6.",
  "old_division": "",
  "old_edition": "1997",
  "new_provision_id": "9.10.18.7.",
  "new_division": "",
  "new_edition": "1997",
  "mapping_type": "renumbered",
  "introduced_by": {
    "provision_id": "9.10.18.7.",
    "division": "",
    "version": 1
  },
  "notes": ""
}
```

`introduced_by` is the **new-id version** that first materialises the
renumber (the version whose `action` is `"renumbered"`). Triple-resolved
by CodeChronicle through the version lookup built from `provisions[]`,
then attached as `ProvisionMapping.introduced_by_version`. This lets the
UI render the gazette clause text (`introduced_by_version.clause.clause_text`)
as the transition narrative for intra-edition pairs.

OBC 1997 has no Division A/B/C structure, so `division` is an empty
string in the example above. For Division-bearing editions (OBC 2006+,
NBC), populate `division` with the top-level Division name.

### Cross-edition identity carry

```json
{
  "old_provision_id": "9.10.18.6.",
  "old_division": "Part 9",
  "old_edition": "1997",
  "new_provision_id": "9.10.18.6.",
  "new_division": "Division B",
  "new_edition": "2006",
  "mapping_type": "renumbered",
  "introduced_by": null,
  "notes": "Renumbered when Division B introduced"
}
```

Cross-edition pairs have no introducing gazette clause (the new edition
is a wholesale re-enactment), so `introduced_by` is null. The UI falls
back to the new version's `transition_provision_id` (a Division C /
Part 12 entry on the receiving edition) for the transition narrative.

### `mapping_type` values

| Value | Meaning |
|-------|---------|
| `renumbered` | Same content, different id (most common) |
| `split` | One provision becomes several |
| `merged` | Several provisions become one |
| `replaced` | Substantively replaced across the identity boundary |

### Resolution

CodeChronicle resolves `old_edition` + `old_provision_id` +
`old_division` and `new_edition` + `new_provision_id` + `new_division` to
`CodeEditionProvision` FKs during ingestion. `introduced_by` is resolved
via the `(provision_id, division, version)` triple to a
`CodeEditionProvisionVersion` FK on the new-id side.

## Image Pre-Rendering

CCM is responsible for producing all images referenced in `page_images`
and `tables[].images`. Image management (upload to S3) is handled by
CodeChronicle's deploy/ingest pipeline.

### Image specs

- Format: WebP
- Quality: 85
- Resolution: varies by content. Full gazette pages ~1600px wide.
  Tables and figures sized to their content.

### What CCM renders

| Content | Source | Output path |
|---------|--------|-------------|
| Full page images | Any PDF | `documents/{pdf_name}/{page}.webp` |
| Amended table composites | Base + amendment PDF | `amended/{code}/{edition}/{table_id}/{version}/{num}.webp` |

Full page images are shared — the same image is referenced by every
provision/table/clause on that page, each with its own bbox. No
duplication of page images.

Bboxes are provided per provision and per table in the JSON. The
frontend uses bbox to crop/focus the view by default, with a "View
full page" toggle for the uncropped image.

### Gazette page images

Regulation browsing in CodeChronicle shows gazette pages for each clause.
These are source document pages referenced by `RegulationClause.page` +
the regulation's `source_pdf`:

```
documents/{source_pdf}/{page}.webp
```

CodeChronicle constructs the path from the regulation's `source_pdf` and
the clause's `page` number.

## What CodeChronicle Does NOT Expect

- Raw PDF files (CodeChronicle serves images, not PDFs)
- Map JSON files (the map abstraction is gone)
- `transitions.json`-style transition data (transitions are version overlaps)
- Separate amendment JSON files (everything consolidated per edition)
- OCR text for tables (tables are images)
- Editions with incomplete amendment chains
