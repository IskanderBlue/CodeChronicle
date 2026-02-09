# CCM Integration Plan

Integrate CodeChronicle-Mapping (CCM) regulation data and maps into CodeChronicle.

## Context

CCM's `data/regulations.json` contains granular OBC edition data:
- **OBC 1997**: 12 versioned entries (v01–v12), effective dates 2003-09-01 to 2006-08-29
- **OBC 2006**: 22 versioned entries (v01–v22+), effective dates 2006-06-28 to ~2014
- **OBC 2012**: 38 versioned entries (v01–v38), effective dates ~2013 to 2024-04-10
- **NBC 2025**: 1 entry (placeholder, not yet fully ingested by CCM)

Each entry has one `output_file` pointing to a single map JSON (e.g. `OBC_1997_v01.json`).
CCM maps use the same schema as existing MCP maps (`sections`, `id`, `title`, etc.) and are
fully compatible with `BuildingCodeMCP`.

## Changes

### 1. Rename `MCP_MAPS_DIR` → `MAPS_DIR`

All maps (existing MCP + CCM) go in one directory locally and one S3 bucket.
No dual-directory setup.

**Files:**
- `code_chronicle/settings/base.py`: `MAPS_DIR = os.environ.get('MAPS_DIR', '')`
- `config/map_loader.py`: `settings.MCP_MAPS_DIR` → `settings.MAPS_DIR`
- `api/search.py`: all `MCP_MAPS_DIR` references → `MAPS_DIR`
- `.env.example`: rename variable, update comment
- `AGENTS.md`, `CLAUDE.md`: update references

### 2. Update `CodeEdition` TypedDict

Current:
```python
class CodeEdition(TypedDict):
    year: int
    map_codes: List[str]
    pdf_files: dict[str, str]
    effective_date: str
    superseded_date: Optional[str]
    amendments: List[Amendment]
```

New:
```python
class CodeEdition(TypedDict):
    edition_id: str              # unique within system: "2024", "1997_v01", "2012_v38"
    year: int                    # for display/grouping
    map_codes: List[str]         # map identifiers
    effective_date: str          # ISO date
    superseded_date: NotRequired[Optional[str]]  # ISO date or None
    pdf_files: NotRequired[dict[str, str]]        # MCP editions have these
    amendments: NotRequired[List[Amendment]]       # MCP editions have these
    regulation: NotRequired[str]                   # e.g. "O. Reg. 332/12"
    version_number: NotRequired[int]               # CCM version number
    source: NotRequired[str]                       # "elaws", "pdf", "mcp"
    source_url: NotRequired[str]                   # elaws URL or download link
    amendments_applied: NotRequired[List[dict]]    # CCM amendment list
```

### 3. Update `CODE_EDITIONS` OBC entries

- **Keep** OBC 2024 entry as-is, adding `edition_id: "2024"`, `source: "mcp"`
- **Remove** hardcoded OBC 2006 and OBC 2012 entries
- **Add** `load_ccm_editions()` function that:
  1. Reads `regulations.json` from `MAPS_DIR` (locally) or S3 (production)
  2. Converts each entry to `CodeEdition` format
  3. Computes `superseded_date` by sorting entries within each system by `effective_date`
     and chaining: each entry's `superseded_date` = next entry's `effective_date`
  4. The last CCM OBC entry (2012_v38, effective 2024-04-10) gets
     `superseded_date = "2025-01-01"` (when OBC 2024 takes over)
  5. Appends to `CODE_EDITIONS['OBC']`
- **All other code systems untouched** (NBC, NFC, NPC, NECB, BCBC, ABC, QCC, etc.)

### 4. Update `_find_edition()`

Current: splits `code_name` on `_`, parses year as int, matches `edition['year']`.

New: splits `code_name` as `system, edition_id = code_name.split('_', 1)`, matches
`edition['edition_id'] == edition_id`. No numeric fallback.

Code names become: `OBC_2024`, `OBC_1997_v01`, `OBC_2012_v38`, `NBC_2025`, etc.

### 5. Update `get_applicable_codes()`

Logic stays the same (find edition where `effective <= search_date < superseded`),
but now works across 70+ OBC entries instead of 3. Still returns exactly **one** edition
per system for a given date.

Return value format changes: e.g. `['OBC_2012_v17', 'NBC_2025']` instead of
`['OBC_2012', 'NBC_2025']`.

### 6. Update `get_map_codes()` / `get_pdf_filename()`

These delegate to `_find_edition()` which now uses `edition_id`, so they work
automatically. CCM editions will have `map_codes = ['OBC_1997_v01']` (stem of
`output_file`) and no `pdf_files`.

### 7. Update downstream callers

- **`api/views.py` `list_available_codes()`**: uses `ed['year']` for display name.
  Update to also show `edition_id` or `version_number` for CCM entries so they're
  distinguishable. Consider whether we want to expose all 70 OBC versions in the
  API or group them.
- **`api/formatters.py` `_build_code_display_name()`**: splits on `_` and takes
  parts[1] as "year". Now parts[1] could be `"2012_v38"`. This still works for
  display: `"Ontario Building Code 2012_v38"`. Could refine later.
- **`api/search.py`**: `mcp_server` variable name is fine; it's just a
  `BuildingCodeMCP` instance. The search loop already iterates `map_codes` —
  CCM editions have one map code each, so this works.
- **`api/tests/test_search.py`**: update `test_get_applicable_codes_ontario_2026`
  assertion — still expects `OBC_2024` (which has `edition_id="2024"`). Works.
- **`core/views.py`**: `get_pdf_filename()` returns `None` for CCM editions (no
  `pdf_files`). Existing 404 handling covers this.

### 8. `regulations.json` loading strategy

- **Local dev**: read from `MAPS_DIR/regulations.json` (CCM puts it alongside maps)
- **Production**: download from S3 alongside maps
- **Reload function**: `reload_ccm_editions()` that re-reads `regulations.json`
  from S3 and refreshes `CODE_EDITIONS['OBC']` in-place. Callable from management
  command or admin endpoint.
- **Startup**: `load_ccm_editions()` called at module import time. If
  `regulations.json` is missing, log a warning and leave CODE_EDITIONS with just
  OBC 2024 (graceful degradation).

### 9. Files modified (summary)

| File | Change |
|------|--------|
| `code_chronicle/settings/base.py` | `MCP_MAPS_DIR` → `MAPS_DIR` |
| `config/code_metadata.py` | TypedDict update, remove OBC 2006/2012, add loader |
| `config/map_loader.py` | `settings.MCP_MAPS_DIR` → `settings.MAPS_DIR` |
| `api/search.py` | `MCP_MAPS_DIR` → `MAPS_DIR` references |
| `api/views.py` | Display name for CCM editions |
| `api/tests/test_search.py` | Update for new edition_id format |
| `.env.example` | Rename env var |
| `AGENTS.md` | Update env var reference |
| `CLAUDE.md` | Update env var reference |

### 10. Not in scope

- NBC / NFC / NPC / NECB / BCBC / ABC / QCC changes (stay as-is)
- Transition period logic (future work)
- CCM search adapter (maps are MCP-compatible, not needed)
- `GUIDE_EDITIONS` changes
- Use of `html`, `notes_html` fields in maps as fallback when `bbox` is not available.
