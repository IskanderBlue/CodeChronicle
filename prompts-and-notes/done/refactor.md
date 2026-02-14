# Repo Structure Review (2026-02-14)

## Rating
**7.5/10**

## What is working well
- Clear high-level separation between `api/`, `core/`, `config/`, and `code_chronicle/settings/`.
- Django settings split by environment (`base`, `development`, `production`) is clean and scalable.
- Tests are colocated by app (`api/tests`, `core/tests`) and cover key paths.
- Operational files (`Dockerfile`, `docker-compose*.yml`, `nginx/`, workflow) are straightforward.
- `README.md` and `AGENTS.md` provide enough context to start quickly.

## Structural Issues + Improvements (priority order)

### 1. Break up growing “god files” into focused modules
Current files are getting broad in responsibility (`core/views.py`, `core/models.py`, `api/search.py`).

Suggested split:
- `api/search.py` -> `api/search/` package:
  - `endpoint.py`
  - `orchestration.py`
  - `rate_limit.py`
  - `history.py`
- `core/views.py` -> `core/views/` package by page concern (`search.py`, `history.py`, `billing.py`).
- `core/models.py` -> separate model files (`user.py`, `search.py`, `maps.py`, etc.) with `core/models/__init__.py` exports.

Why: easier ownership, simpler tests, lower merge conflicts.

### 2. Add an explicit service layer for domain logic
Business logic currently appears distributed between API layer, `config/code_metadata.py`, and model helpers.

Suggested structure:
- `services/search_service.py`
- `services/llm_parse_service.py`
- `services/code_applicability_service.py`
- `services/subscription_service.py`

Why: keeps views/endpoints thin and prevents logic duplication between web and API paths.

### 3. Separate deploy/runtime artifacts from product docs
`prompts-and-notes/`, `CLAUDE.md`, and agent-specific files are useful, but mixed with runtime root files.

Suggested cleanup:
- Move internal planning to `docs/internal/` or `notes/`.
- Keep root focused on app/runtime essentials.
- Add `docs/architecture.md` with one canonical flow diagram.

Why: improves repo signal-to-noise and onboarding clarity.

### 4. Add CI quality gates beyond image publish
Current workflow only builds/pushes Docker.

Add workflow(s) for:
- `ruff check .`
- `pytest`
- optional `pyright`

Why: structural quality stays enforceable as contributors and file count grow.

### 5. Normalize config boundaries
`config/` currently mixes static data (`metadata.json`) and executable logic (`code_metadata.py`).

Suggested split:
- `config/data/` for JSON/static assets
- `core/domain/` or `services/` for executable rules

Why: clearer distinction between data inputs and domain behavior.

### 6. Introduce API versioning folder early
Before the API surface grows further, establish:
- `api/v1/...`

Why: avoids disruptive reorganizations later and enables compatibility planning.

### 7. Consider a dedicated frontend namespace if templates grow
If HTMX/Alpine UI expands, move toward:
- `frontend/views/`
- `frontend/templates/`
- `frontend/components/`

Why: prevents `core/` from becoming a mixed bucket for unrelated concerns.

## Suggested near-term sequence
1. Introduce service layer and migrate search orchestration first.
2. Split `api/search.py` and `core/views.py` into packages.
3. Add CI lint/test checks.
4. Move planning notes/docs into a dedicated docs namespace.
5. Split models only after service boundaries are stable.
