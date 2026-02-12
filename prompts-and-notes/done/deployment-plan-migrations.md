# Deployment Plan - Migrations and Map Storage

## Summary
- Map storage now lives in Postgres via `CodeMap` + `CodeMapNode` (disaggregated).
- Search flow is DB-backed; MCP map loading is removed.
- Code metadata is DB-backed via `CodeSystem` + `CodeEdition` + `ProvinceCodeMap`.

## Scope and Goals
- Eliminate large in-memory map loading on the app VM by using DB-backed map components.
- Keep PDF workflow unchanged (client-side rendering, stored externally by user).

## Data Model Changes

### New Models

1) `CodeMap`
- Fields:
  - `code_name` (string; not unique; e.g., `OBC_2024`, `NBC_2025`)
  - `map_code` (string; unique; current MCP identifier like `OBC_Vol1`, `NBC`)
  - `created_at` (auto_add_now=True)
  - `updated_at` (auto_now=True)
- Purpose: top-level map record; isolates each map and gives a stable identity.

2) `CodeMapNode`
- Fields:
  - `code_map` (FK to `CodeMap`)
  - `node_id` (string; original `section["id"]`)
  - `title` (string)
  - `html` (text; nullable) — rendered from markdown on import
  - `notes_html` (text; nullable)
  - `keywords` (ArrayField[str]; nullable)
  - `bbox` (JSONField or array; nullable)
  - `parent_id` (string; nullable; optional if we want hierarchy)
- Indexes:
  - `(code_map, node_id)` unique index
  - optional `node_id` index for fast lookup
  - GIN index on `keywords` for contains queries
- Purpose: disaggregated map content used at query time without loading full JSON.

### Rationale
- Disaggregation avoids loading the entire JSON payload into memory per request.
- Keeps queries bounded to only the relevant sections returned by DB search.
- Keyword filtering uses `ArrayField` + GIN for fast contains queries.

## Data Loading / Migration

### Management Commands
- `python manage.py load_maps --source ../CodeChronicle-Mapping/maps` (default path)
- Behavior:
  1. Scan `<dir>/*.json`.
  2. For each map file, create/update `CodeMap` (`code_name`, `map_code`, `updated_at`).
  3. Merge `sections` + `tables` into `CodeMapNode` rows (dedupe by `node_id`).
  4. Render markdown to `html` at import time.
  5. Clear nodes for a map before re-insert (bulk insert).
- `python manage.py load_code_metadata --source config/metadata.json`

### Migration
- Single migration for map + metadata models.
- Load commands are required before search usage.

## Search Flow Changes

### Current
- N/A (implemented).

### New
- DB-backed search against `CodeMapNode` with MCP synonyms/fuzzy scoring.
- Enrich results with `bbox` + `html` from DB via a single lookup per map.
- Metadata loaded from `config/metadata.json` (exported/managed separately).

### Impact
- Per-request memory stays low.
- DB load shifts to selective queries instead of full map decode.

## Public API/Interface Changes
- No endpoint changes.
- Internal: `execute_search()` now uses DB search + DB enrichment.

## Tests and Scenarios

1) Map Load Command
- Load maps from known directory.
- Assert `CodeMap` created and `CodeMapNode` count matches JSON sections + tables.

2) Search Result Enrichment
- Given `CodeMapNode` rows, `execute_search()` should return `bbox` and `html_content` as before.

3) No-map Edge
- If a map has no nodes, search still returns results but with missing `bbox`/`html_content` (graceful fallback).

## Assumptions and Defaults
- `CodeMapNode` is the chosen term for disaggregated entities.
- DB search is the source of truth.

