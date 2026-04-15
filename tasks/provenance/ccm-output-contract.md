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
  "edition_mappings": [ ... ]
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
      "action": "original",
      "regulation": "403/97",
      "clause_id": null,
      "effective_date": "1998-04-06",
      "ineffective_date": "1998-04-06",
      "transition_provision_id": null,

      "title": "Definitions",
      "html": "<p>In this Code,</p><p>...</p>",
      "page_images": [
        "documents/obc_1997_v2.pdf/42.webp"
      ],
      "keyword_counts": {"fire": 3, "safety": 1},

      "tables": []
    },
    {
      "version": 1,
      "action": "revoke_and_substitute",
      "regulation": "22/98",
      "clause_id": "1.(1)",
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
      "action": "original",
      "regulation": "403/97",
      "clause_id": null,
      "effective_date": "1998-04-06",
      "ineffective_date": null,
      "transition_provision_id": null,

      "title": "",
      "html": "<p>The OBC applies to both site-built and...</p>",
      "page_images": [
        "documents/obc_1997_appendix.pdf/12.webp"
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

### `versions[].action` values

| Value | Meaning |
|-------|---------|
| `original` | From base regulation (version 0 of base provisions) |
| `added` | New provision created by an amendment (version 0 of added provisions) |
| `revoke_and_substitute` | Entire provision replaced |
| `amend_add` | Content added to provision |
| `amend_strike_sub` | Text replaced within provision |
| `revoked` | Provision removed — `html` is empty |

### `versions[].regulation` + `versions[].clause_id`

Together these identify the source. CodeChronicle resolves these to
`Regulation` and `RegulationClause` FKs during ingestion.

- For `action: "original"`: `regulation` = base reg_id, `clause_id` = null
- For `action: "added"`: `regulation` = amending reg_id, `clause_id` = the clause
- For all others: `regulation` = amending reg_id, `clause_id` = the clause

### `versions[].effective_date` / `ineffective_date`

- `effective_date`: when this version comes into force
- `ineffective_date`: when this version ceases to be in force. Null if
  this is the current version and the edition is still in force.
- During a transition period, the old version's `ineffective_date` is
  extended to the overlap end. Both versions have overlapping date ranges.

### `versions[].transition_provision_id`

When this version creates a transition period (the previous version
continues to apply for some permits), this is the `provision_id` of the
Division C / Part 12 provision that defines the transition terms.

CodeChronicle resolves this to a `CodeEditionProvisionVersion` FK during
ingestion (the current version of the referenced transition provision).

Null when no transition applies.

### `versions[].page_images`

S3 paths to page images. Two schemes:

**Source document pages** (shared, reused across provisions):
```
"documents/obc_1997_v2.pdf/42.webp"
```

**Amended composites** (per provision version):
```
"amended/obc/1997/1.1.3.2./1/1.webp"
```

Base provisions (v0) reference source document pages — no duplication.
Amended provisions with HTML-only changes may have empty `page_images`
(HTML is the display).

### `versions[].tables[]`

Tables belonging to this provision at this version.

```json
{
  "table_id": "Table-3.1.4.7.",
  "caption": "Fire Resistance Ratings",
  "images": [
    "documents/obc_1997_v2.pdf/143.webp",
    "documents/obc_1997_v2.pdf/144.webp"
  ],
  "notes": "Note (1): For buildings of...",
  "order": 0
}
```

- `images`: S3 paths. For base tables, source document pages. For
  amended tables, pre-composited images under `amended/`.
- `notes`: Table notes as text. Notes that were amended have the
  amended text here.
- `order`: Display order when a provision has multiple tables.

When a table is amended but its parent provision's text is unchanged,
the parent still gets a new version (with the same `html`) because the
table content changed.

Table bboxes are included in the parent provision's overall bbox, not
tracked separately.

## `edition_mappings[]`

Cross-edition provision identity mappings. Optional — only present when
mapping data exists.

```json
{
  "old_edition": "1997",
  "old_provision_id": "9.10.18.6.",
  "old_division": "Part 9",
  "new_edition": "2006",
  "new_provision_id": "9.10.18.6.",
  "new_division": "Division B",
  "mapping_type": "renamed",
  "notes": "Renumbered when Division B introduced"
}
```

CodeChronicle resolves `old_edition` + `old_provision_id` and
`new_edition` + `new_provision_id` to `CodeEditionProvision` FKs during
ingestion.

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
| Base provision pages | Code PDF | `documents/{pdf_name}/{page}.webp` |
| Base table pages | Code PDF | `documents/{pdf_name}/{page}.webp` |
| Amended table pages | Base + amendment PDF | `amended/{code}/{edition}/{table_id}/{version}/{num}.webp` |
| Gazette regulation pages | Gazette PDF | `documents/{pdf_name}/{page}.webp` |

Source document pages are shared — the same page image is referenced by
every provision on that page. No duplication.

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
