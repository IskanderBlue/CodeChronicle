# 2 — Ingestion: Load Rewrite + Image Pipeline

## What

Replace `load_maps.py` with a new ingestion command that reads CCM's
consolidated output and populates the provenance models. Set up image
storage in S3.

## Depends On

- Task 1 (schema exists)
- CCM producing consolidated edition JSON (see `ccm-output-contract.md`)

## New Management Command: `load_edition`

Replaces `load_maps` + `load_code_metadata` for provenance-aware editions.

```
python manage.py load_edition --source path/to/OBC_1997.json
```

### What it does

1. **Edition + regulations**: Create/update `CodeEdition`, `Regulation`
   records (base + all amendments) from top-level metadata
2. **Regulation clauses**: Create `RegulationClause` records from each
   regulation's clause data
3. **Provisions**: Create `CodeEditionProvision` records from provision
   tree, setting `parent` FKs based on hierarchy and `appendix_of` FKs
   for A-prefixed provisions (linking `A-1.1.3.2.` → `1.1.3.2.`)
4. **Versions**: Create `CodeEditionProvisionVersion` records:
   - v0 from base provision data (title, html, keyword_counts)
   - v1+ from amendment-applied versions
   - Set `effective_date`, `ineffective_date`, `clause` FK
   - Set `transition_provision` FK where transitions apply
5. **Tables**: Create `ProvisionVersionTable` records from table data on
   each version (table_id, caption, notes, image paths)
6. **Cross-edition mappings**: Create `ProvisionEditionMapping` records
   if mapping data is present

### Idempotent

Re-running `load_edition` for the same edition replaces all data. Deletes
existing provisions + versions for the edition and recreates from JSON.

## Image Pipeline

### Source images

CCM pre-renders page images from gazette/code PDFs during its pipeline.
These are the authoritative visual representation.

For amended tables, CCM produces pre-composited images (base table with
amendment patches applied).

### Storage layout

Two image schemes — source pages are shared, amended images are per
provision version:

```
s3://codechronicle-assets/
  documents/
    obc_1997_v2.pdf/
      42.webp                    # source PDF page (shared across provisions)
      43.webp
    ont_reg_1998_v1.pdf/
      29.webp                    # gazette page for clause browsing
      30.webp
  amended/
    obc/1997/
      1.1.3.2./
        1/1.webp                 # amended provision version 1
      Table-2.5.1.1./
        1/1.webp                 # pre-composited amended table
        1/2.webp                 # (multi-page)
```

Base provision versions reference source document pages directly —
no duplication. Amended versions that are HTML-only (text amendments)
may have no page images at all.

### Image specs

- Format: WebP
- Quality: 85
- Resolution: varies by content. Full gazette pages ~1600px wide.
  Tables and figures sized to their content.

### Image management

Image upload and management sits under CodeChronicle, not CCM. CCM
produces the images; CodeChronicle's deploy/ingest pipeline uploads them
to S3. The `load_edition` command reads image paths from the JSON and
stores them on `CodeEditionProvisionVersion.page_images` and
`ProvisionVersionTable.images`.

## Verification

- `load_edition` ingests a CCM-produced JSON without errors
- All provisions, versions, regulations, clauses populated
- `ProvisionVersionTable` records created for table data
- Image paths resolve to real S3 objects
- `version_count` matches actual version records
- `effective_date` / `ineffective_date` form non-overlapping ranges per
  provision (except during transition periods, where exactly two overlap)
- Re-running `load_edition` produces identical state (idempotent)
