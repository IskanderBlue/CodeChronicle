# AGENTS.md

## Summary (for AI assistants)

### Project
- CodeChronicle: Django 5 app for historical Canadian building code search (OBC/NBC).
- Natural-language queries are parsed via Anthropic tool calling into structured params (date, province, keywords, building_type), then searched with `building-code-mcp`.

### Key Commands (run inside `venv/`)
- Install: `pip install -e ".[dev]"`
- Run server: `python manage.py runserver`
- Tests: `pytest` (or `pytest api/tests/test_search.py`)
- Lint: `ruff check .` (optionally `--fix`)
- Migrations: `python manage.py migrate`, `python manage.py makemigrations`
- Load metadata: `python manage.py load_code_metadata --source config/metadata.json`
- Load maps: `python manage.py load_maps --source ../CodeChronicleMapping/maps`
- Optional Postgres: `docker-compose up -d`

### Architecture
- Apps:
  - `core/`: custom `User`, search history, cache/prompt models, rate limiting, HTMX views.
  - `api/`: Django Ninja API (`/api/search`, `/api/history`, `/api/codes`, `/api/health`).
- `config/`: `code_metadata.py` (DB-backed `get_applicable_codes()`), `keywords.py`.
- Flow: Rate limit -> LLM parse -> cache -> `execute_search()` -> `get_applicable_codes()` -> `building-code-mcp` -> format -> history save.
- Frontend: Django templates + HTMX + Alpine.js + Tailwind (CDN). Partials in `templates/partials/`.

### Settings & Env
- Settings: `code_chronicle/settings/{base,development,production}.py`.
- Env vars: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `DATABASE_URL`.

### Rate Limits & Subscriptions
- Anonymous: 1 search/day. Authenticated free: 3/day. Pro: unlimited (Stripe/dj-stripe or `pro_courtesy`).

### Code Style
- Ruff: `E,F,I,N,W`, line length 100, py312.
- Typed function signatures.
- API response: `{"success": bool, "data": {...}, "error": str|null, "meta": {...}}`.
- Conventional commits (`feat:`, `fix:`, etc.).

### Historical Planning Notes (obsolete but context)
- MVP: OBC full text + NBC coordinate index (BYOD). Maps stored in S3, loaded into memory at startup.
- Phased roadmap, Stripe integration, optional AI synthesis post-MVP, expansion to pre-2004.
- NBC copyright constraints: coordinate index only, no full text storage.
