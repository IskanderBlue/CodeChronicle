# AGENTS.md

## Summary (for AI assistants)

### Project
- CodeChronicle: Django 5 app for historical Canadian building code search (OBC/NBC).
- Natural-language queries are parsed via Anthropic tool calling into structured params (date, province, keywords, building_type), then searched against the in-force provision versions in the database.

### Key Commands (run inside `venv/`)
- Install: `pip install -e ".[dev]"`
- Run server: `python manage.py runserver`
- Tests: `pytest` (or `pytest api/tests/test_search.py`)
- Lint: `ruff check .` (optionally `--fix`)
- Migrations: `python manage.py migrate`, `python manage.py makemigrations`
- Load an edition: `python manage.py load_edition --source ../CodeChronicleMapping/data/outputs`
- Optional Postgres: `docker-compose up -d`

### Architecture
- Apps:
  - `core/`: custom `User`, search history, cache/prompt models, rate limiting, HTMX views.
  - `api/`: Django Ninja API (`/api/search`, `/api/history`, `/api/codes`, `/api/health`).
- `config/`: `code_metadata.py` (`get_code_display_name()`), `keywords.py`.
- Flow: Rate limit -> LLM parse -> cache -> `execute_search()` (per-version in-force query across all editions of the province's code -> `score_versions()`, untruncated -> `_split_by_access()` -> `_group_transitions()` -> `_limit_with_pairs()`) -> format -> history save. The tier split precedes the display limit so a gated searcher's cards come from editions they can open, and the locked counts are exact totals, not pool size. A relevance floor (`match_threshold`, default 0.8, continuous) is applied to both sides of the split so the shown count and the Pro-teaser count are measured identically; `weak_matches_only` marks the fallback where nothing cleared it, and `close_match_count` (above the line) is not `accessible_match_count` (what's shown). The control is a line dragged across the query's own score distribution (`score_buckets` + `window.ccDatum`), not named tiers — a fixed 0.8 keeps 20/90/1 matches on three real queries, so tier names can't stay honest; it lives in a dialog opened from the "close matches" noun in the header and closes when the re-run re-renders the partial. There is no page-size preference: `SEARCH_RESULT_CAP` (100) is a constant backstop, surfaced only when `cap_binds` (computed at the trim, not by comparing rows to counts). Searcher prefs (`results_per_search`, `match_threshold`) live in `config/search_limits.py` + `core/search_prefs.py`. No edition-resolution step; query-term synonyms come from `config/synonyms.py` (vendored from the retired `building-code-mcp` dependency).
- Scoring is BM25F over two fields: CCM ships `keyword_counts` (title + body + table-text union) and `title_keyword_counts` (title alone, same tokenizer), and the body's counts are the difference floored at zero. Fields are summed as length-normalized frequencies and saturated **once** — per-field saturation would let a long body plus a matching title double the ceiling. With no title counts it reduces exactly to the previous single-field BM25, so un-reloaded editions rank unchanged. `BM25F_TITLE_WEIGHT` (3.0) is the tuning knob; the title field carries the topicality that `BM25_B` (0.75, set to suppress Part 11 mega-tables) cannot, since b only knows "long is suspicious". Title weighting applies to indirect terms too — CCM's tokenizer does no stemming.
- Frontend: Django templates + HTMX + Alpine.js + Tailwind (CDN). Partials in `templates/partials/`.

### Settings & Env
- Settings: `code_chronicle/settings/{base,development,production}.py`.
- Env vars: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `DATABASE_URL`.

### Rate Limits & Subscriptions
- Anonymous: 1 search/day. Authenticated (free and Pro): unlimited.
- Content gating (`core/access.py`, unconditional): anonymous + non-Pro users are scoped
  to `FREE_TIER_CODE_NAMES` (OBC 2006); Pro (Stripe/dj-stripe or `pro_courtesy`)
  unrestricted. History: `tasks/complete/free-tier-obc2006-scope.md`.

### Code Style
- Ruff: `E,F,I,N,W`, line length 100, py312.
- Typed function signatures.
- API response: `{"success": bool, "data": {...}, "error": str|null, "meta": {...}}`.
- Conventional commits (`feat:`, `fix:`, etc.).

### Agent Notes
- **Workspace root is `c:/Users/victu/Documents/repos/CodeChronicle`.** When using `cwd` in Bash calls, use this path exactly — do NOT concatenate it with itself.
- **Temporary files**: Write throwaway scripts, debug helpers, and scratch files to `.tmp/` (gitignored). Never create them in the project root.

### Historical Planning Notes (obsolete but context)
- MVP: OBC full text + NBC coordinate index (BYOD). Maps stored in S3, loaded into memory at startup.
- Phased roadmap, Stripe integration, optional AI synthesis post-MVP, expansion to pre-2004.
- NBC copyright constraints: coordinate index only, no full text storage.
