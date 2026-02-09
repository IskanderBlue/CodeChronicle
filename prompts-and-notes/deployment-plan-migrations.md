# Deployment Plan - Migrations and Map Storage

## Summary
- Move map storage from in-memory/S3 filesystem to database-backed models `CodeMap` + `CodeMapNode` (disaggregated).
- Update search flow to load map metadata/sections from DB instead of JSON files.

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
  - `html` (text; nullable)
  - `notes_html` (text; nullable)
  - `bbox` (JSONField or array; nullable)
  - `parent_id` (string; nullable; optional if we want hierarchy)
- Indexes:
  - `(code_map, node_id)` unique index
  - optional `node_id` index for fast lookup
- Purpose: disaggregated map content used at query time without loading full JSON.

### Rationale
- Disaggregation avoids loading the entire JSON payload into memory per request.
- Keeps queries bounded to only the relevant sections returned by MCP.

## Data Loading / Migration

### Management Command
- New: `python manage.py load_maps --source <dir>`
- Behavior:
  1. Scan `<dir>/*.json`.
  2. For each map file, create/update `CodeMap` (`code_name`, `map_code`, `updated_at`).
  3. Parse `sections` array into `CodeMapNode` rows (upsert).
  4. Clear nodes for a map before re-insert (or use bulk upsert).

### Migration
- Create migrations for `CodeMap` and `CodeMapNode`.
- The load command is required before search usage.

## Search Flow Changes

### Current
- `api/search.py` loads JSON files into `BuildingCodeMCP` in-memory.
- Lookup for `bbox` and `html_content` is from in-memory JSON.

### New
- Remove S3/local map loading from `_get_maps_dir()` and `_rekey_maps_by_stem()` usage.
- Modify search to:
  - `BuildingCodeMCP` must be initialized with our new map (eg. `regulations.json`), that file will have to stay in memory unless we intend to rebuild the `BuildingCodeMCP` functions actually in use (which looks doable).
  - For each MCP search result, fetch matching `CodeMapNode` rows:
    - Preload `node_id` -> `bbox`, `text`, `title` for the `map_code`.
  - This can be done with a single query per `map_code`:
    - `CodeMapNode.objects.filter(code_map__map_code=map_code, node_id__in=<result ids>)`
- If MCP still requires maps on disk, preserve minimal JSON load or introduce a DB-backed adapter (decision complete: keep MCP invocation as-is but replace lookup data with DB query).

### Impact
- Per-request memory stays low.
- DB load shifts to selective queries instead of full map decode.

## Public API/Interface Changes
- No API surface change to endpoints.
- Internal: `execute_search()` now enriches results using `CodeMapNode` instead of JSON map payload.

## Tests and Scenarios

1) Map Load Command
- Load maps from known directory.
- Assert `CodeMap` created and `CodeMapNode` count matches JSON sections.

2) Search Result Enrichment
- Given `CodeMapNode` rows, `execute_search()` should return `bbox` and `html_content` as before.

3) No-map Edge
- If a map has no nodes, search still returns results but with missing `bbox`/`html_content` (graceful fallback).

## Assumptions and Defaults
- `CodeMapNode` is the chosen term for disaggregated entities.
- MCP search remains in place; only enrichment is moved to DB.
