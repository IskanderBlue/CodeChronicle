# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CodeChronicle is a Django 5.0 application for searching historical Canadian building codes. Users enter natural language queries (e.g., "fire safety for a house built in Toronto in 1995"), which are parsed by Claude's tool_use API into structured parameters (date, province, keywords, building_type), then searched against applicable code editions using the `building-code-mcp` library.

## Commands

All commands must run inside the virtual environment (`venv/` in project root). On Windows: `venv\Scripts\activate`. On Linux/Mac: `source venv/bin/activate`.

```bash
# Install (editable with dev dependencies)
pip install -e ".[dev]"

# Run development server
python manage.py runserver

# Run all tests
pytest

# Run a single test file
pytest api/tests/test_search.py

# Run a single test
pytest api/tests/test_search.py::TestClassName::test_method_name

# Lint
ruff check .
ruff check --fix .

# Database migrations
python manage.py migrate
python manage.py makemigrations

# Load code metadata (DB-backed)
python manage.py load_code_metadata --source config/metadata.json

# Export code metadata to JSON

# Load map JSONs into DB
python manage.py load_maps --source ../CodeChronicle-Mapping/maps

# Start PostgreSQL
docker-compose up -d
```

## Architecture

### Django Apps

- **core/** - Custom User model (email-only, no username via `AUTH_USER_MODEL = 'core.User'`), SearchHistory, QueryCache/QueryPrompt models, RateLimitMiddleware, and frontend views (HTMX-based)
- **api/** - Django Ninja REST API. Key endpoints: `/api/search` (POST), `/api/history` (GET), `/api/codes` (GET), `/api/health` (GET)
- **config/** - Configuration helpers: `code_metadata.py` reads DB-backed code metadata (`get_applicable_codes()`), `keywords.py` has the valid keyword list.

### Request Flow

```
User query → RateLimitMiddleware → llm_parser.parse_user_query() (Claude API with tool_use)
→ QueryCache check/store → api/search.execute_search() → config.get_applicable_codes()
→ BuildingCodeMCP.search_code() → api/formatters.format_search_results() → SearchHistory.create()
```

### Frontend

Django templates + HTMX + Alpine.js + Tailwind CSS (CDN). Templates live in `templates/` with HTMX partials in `templates/partials/`. The search page uses `hx-post` for partial page updates without full reloads.

### Settings

Split settings in `code_chronicle/settings/`: `base.py`, `development.py`, `production.py`. Tests use `development` settings (configured in `pyproject.toml`). Key env vars: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `DATABASE_URL`.

### Rate Limiting & Subscriptions

Anonymous: 1 search/day (per IP). Authenticated free: 3/day. Pro (via Stripe/dj-stripe or `pro_courtesy` flag): unlimited. Enforced by `core.middleware.RateLimitMiddleware`.

## Code Style

- **Linter**: ruff (rules: E, F, I, N, W; line-length: 100; target: py312)
- **Imports**: stdlib → Django → third-party → local
- **Type hints** on all function signatures
- **Naming**: snake_case files/functions, PascalCase classes, UPPER_SNAKE_CASE constants, singular model names
- **API responses**: `{"success": bool, "data": {...}, "error": str|null, "meta": {...}}`
- **Commits**: conventional style (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
- **Tests**: pytest with `pytest-django`; fixtures for common setup

## Key Dependencies

- `building-code-mcp` - Core search engine for building code PDFs
- `anthropic` - Claude API client for natural language query parsing
- `django-allauth` - Email-only authentication (no username field)
- `dj-stripe` - Stripe subscription management
- `boto3` - S3 access for code PDF map files
- `rapidfuzz` - Fuzzy string matching for keyword resolution
