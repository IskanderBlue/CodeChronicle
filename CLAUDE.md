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

# Load a CCM consolidated edition (provenance models) into the DB
python manage.py load_edition --source ../CodeChronicleMapping/data/outputs

# Start PostgreSQL
docker-compose up -d
```

### Frontend CSS

Tailwind is built by the **v4.3.0 standalone CLI** (one self-contained binary, no Node) for both dev and prod — the same binary CI uses, so the two can't skew. The built file `static/css/tailwind.css` is gitignored; dev must build it (without it, pages render with the always-present inline CSS in `base.html` but no Tailwind utilities).

```bash
# One-time: download the standalone CLI for your OS from
# https://github.com/tailwindlabs/tailwindcss/releases/tag/v4.3.0
#   Windows -> tailwindcss-windows-x64.exe  (rename to tailwindcss.exe)

# Run in watch mode alongside `runserver` during dev:
.\tailwindcss.exe -i static/css/input.css -o static/css/tailwind.css --watch

# One-off build (no watch):
.\tailwindcss.exe -i static/css/input.css -o static/css/tailwind.css --minify
```

> ⚠️ **Windows Defender false-positive.** The standalone CLI is a Bun-compiled
> single-file (unsigned) executable, which AV routinely misflags — Defender has
> reported it as `Trojan:Win32/PowhidSubExec.B`. It's a known false positive (the
> file is the official `tailwindlabs` v4.3.0 release; see Tailwind's GitHub issues),
> **but** the detection is behavioral and is made much worse by running the binary
> through `pwsh -ExecutionPolicy Bypass -Command …` (that wrapper is itself the
> "PowhidSubExec" — *Pow*ershell *hid*den *Sub*-*Exec* — pattern). So: run it from a
> plain terminal as `.\tailwindcss.exe …` (NOT via a `pwsh -Command` one-liner, and
> NOT through tooling that wraps it that way). If Defender still quarantines it,
> re-verify from the official release and add a file/folder exclusion, or use the
> npm route instead — `npm i -D @tailwindcss/cli` then `npx @tailwindcss/cli …`
> (needs Node, but ships as plain `.js` that AV doesn't behavior-flag).

Hand-written, non-utility CSS (component classes, `x-cloak`, htmx/diff helpers) lives inline + always-present in `base.html`; the colour role tokens live in `tailwind.config.js`. `input.css` is only the Tailwind entrypoint (`@import "tailwindcss"; @config`).

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

## Temporary Files

Write throwaway scripts, debug helpers, and scratch files to `.tmp/` (gitignored). Never create them in the project root.

## Code Style

- **Linter**: ruff (rules: E, F, I, N, W; line-length: 100; target: py312)
- **Imports**: stdlib → Django → third-party → local
- **Type hints** on all function signatures
- **Naming**: snake_case files/functions, PascalCase classes, UPPER_SNAKE_CASE constants, singular model names
- **Terminology**: Use "provision" (not "section") as the generic term for any structural unit in the code (part, section, subsection, article). "Section" is only correct when referring to the specific `section` level (e.g., `2.11.`). Variables, function names, comments, and docs should all say `provision` when the meaning is generic.
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
