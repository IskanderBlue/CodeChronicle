# Provenance Model & Display — Overview

## Goal

Make CodeChronicle the definitive source for forensic building code lookup.
For any provision, answer: "What version was in force on date X, and how do
I know?" — with a complete, verifiable chain of authority.

## Audience

Forensic engineers who need certainty about exactly what was in force on
what date. The answer must be provably correct and defensible in court.

## Scope

Ontario Building Code (OBC) first. We host the documents ourselves (gazette
PDFs, base code PDFs) and serve them directly — no BYOD.

## Core Design

### Provisions as the unit of display

A provision is anything with a legal identity in the code: parts, sections,
subsections, articles. Tables are content within their parent provision's
version — not separate entities. When a table is amended, its parent
provision gets a new version.

Provision bboxes encompass the provision text plus any associated tables.

### Version chain as the proof

Each provision has an ordered chain of versions, each linked to the
regulation clause that produced it. The chain proves the displayed version
is correct by showing:

1. Which regulation introduced this version (and which clause)
2. When it came into force
3. That the next amendment in the chain (if any) isn't in force yet
4. If a transition period is active, both versions with the applicability
   text from Division C / Part 12

### Display strategy

- **Text** (articles, sentences): HTML rendered from applied amendments
- **Tables**: HTML when e-Laws (or another structured source) publishes
  a point-in-time form for that version; otherwise pre-composited
  images (base page + amendment patches baked in at ingest time). No
  in-browser compositing. Per-version, per-table switch — see
  `4-display.md` for render rules.
- **Base edition content**: PDF page images (the actual documents)
- **Amended text content**: Rendered HTML (amendments produce new text)

### Pre-rendered images

Full page images at `documents/{document_name}/{page}.webp`, shared
across all provisions on the same page. Each provision and table carries
bbox data (`{l, t, r, b}`) pointing to its region on the page.

The frontend defaults to a cropped/focused view using the bbox, with a
"View full page" toggle showing the uncropped image with the region
highlighted. Provisions spanning columns or pages have multiple bbox
entries in reading order.

Amended tables with structural changes (column/row replacement) get
pre-composited images at `amended/{code}/{edition}/{table_id}/{version}/{num}.webp`.

Image management sits under CodeChronicle, not CCM.

### No separate Transition model

Transitions are date range overlaps on `CodeEditionProvisionVersion`. When
a query date falls within an overlap, two versions are active. The newer
version's `transition_provision` FK points to the Division C / Part 12
provision whose text defines the transition terms.

## Model Summary

```
Code                     OBC
 └── CodeEdition         OBC 1997
      ├── ineffective_date: 2006-12-31
      │
      ├── Regulation (base "403/97", role="base")
      ├── Regulation (amendment "22/98", role="amendment")
      │    ├── RegulationClause 1.(1) → target 1.1.3.2.
      │    ├── RegulationClause 9     → target Part 2
      │    └── RegulationClause 15.(1)→ target 9.10.18.6.(1)
      │
      └── CodeEditionProvision 1.1.3.2.
           ├── CodeEditionProvisionVersion v0
           │    ├── clause: null (original, from base regulation)
           │    ├── effective_date: 1998-04-06
           │    ├── html: "...original text..."
           │    └── tables → ProvisionVersionTable(s)
           │
           └── CodeEditionProvisionVersion v1
                ├── clause: → RegulationClause 1.(1)
                ├── effective_date: 1998-04-06
                ├── html: "...amended text..."
                └── tables → ProvisionVersionTable(s)

Appendix note (separate provision, displayed inline with parent):
  CodeEditionProvision A-1.1.3.2.(1)
    ├── level: "sentence"
    ├── appendix_of: → CodeEditionProvision 1.1.3.2.
    └── CodeEditionProvisionVersion v0
         └── html: "...appendix note text..."

Cross-edition:
  ProvisionEditionMapping
    OBC 1997 § 9.10.18.6. → OBC 2006 Div B § 9.10.18.6.
    mapping_type: "renamed"
```

## Task Sequence

1. [Schema: new models](1-schema.md)
2. [Ingestion: load rewrite + image pipeline](2-ingestion.md)
3. [Code paths: search, API, applicable codes](3-code-paths.md)
4. [Display: provision view, provenance, regulation browsing](4-display.md)
5. [Cleanup: drop old models and fields](5-cleanup.md) — ✅ done 2026-06-02

CCM output contract: [ccm-output-contract.md](ccm-output-contract.md)

## What Replaces What

| Old | New |
|-----|-----|
| `CodeMapNode` | `CodeEditionProvision` + `CodeEditionProvisionVersion` |
| `CodeMap` (node container) | gone — provisions FK to edition |
| `CodeMap` (physical file) | S3 image paths on version |
| `CodeEdition.effective_date` | `CodeEdition.effective_date` (kept) |
| `CodeEdition.superseded_date` | `CodeEdition.ineffective_date` |
| `CodeEdition.regulation` (CharField) | `edition.regulations.get(role="base")` |
| `CodeEdition.map_codes` | gone — no maps |
| `CodeEdition.pdf_files` | S3 image paths on version |
| `CodeEdition.amendments` (JSONField) | `Regulation` records with `role="amendment"` |
| `CodeMapNode.provision_transitions` | `CodeEditionProvisionVersion` date range overlaps |
| `Transition` model (from old tasks) | `CodeEditionProvisionVersion` effective/ineffective dates + `transition_provision` FK |
| `Amendment` model (from old tasks) | `CodeEditionProvisionVersion` with `clause` FK |
| `config/transitions.json` | `CodeEditionProvisionVersion` date ranges |
| `config/transitions.py` | DB queries on version model |
| `ProvinceCodeMap` | `ProvinceCode` (renamed; Code not CodeSystem) |
