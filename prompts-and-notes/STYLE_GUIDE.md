# CodeChronicle Style Guide

This document captures architectural and coding decisions for the project.

## Technology Stack

| Layer | Choice | Version | Rationale |
|-------|--------|---------|-----------|
| **Backend** | Django | 5.x | Batteries-included, excellent ORM |
| **API** | Django Ninja | 1.x | Type-safe, fast, OpenAPI auto-docs |
| **Database** | PostgreSQL | 15+ | Production-ready, JSON support |
| **Frontend** | HTMX + Alpine.js | 1.9.x / 3.x | Server-driven, minimal JS |
| **CSS** | Tailwind CSS | 3.x (CDN) | Utility-first, responsive |
| **Auth** | django-allauth | 0.60+ | Social login, email verification |
| **Payments** | dj-stripe | 2.8+ | Stripe integration, webhooks |
| **LLM** | Anthropic Claude | `CLAUDE_MODEL` env var | Tool calling for query parsing |

---

## Project Structure

```
CodeChronicle/
├── code_chronicle/           # Django project (settings, urls, wsgi)
├── api/                      # API app (endpoints, search logic)
├── core/                     # Core app (models, middleware)
├── config/                   # Code metadata, map loading
├── templates/                # Jinja2 templates
├── static/                   # Static assets (if any)
└── tests/                    # Top-level test utilities
```

---

## Python Conventions

### Import Order
1. Standard library
2. Django imports
3. Third-party packages
4. Local app imports

```python
# Standard library
import json
from datetime import datetime
from typing import Optional

# Django
from django.conf import settings
from django.http import JsonResponse

# Third-party
from coloured_logger import Logger
from ninja import NinjaAPI
from anthropic import Anthropic

# Local
from api.llm_parser import parse_user_query
from config.code_metadata import get_applicable_codes
```

### Naming Conventions
- **Files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions/Variables**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Django models**: Singular nouns (`User`, `Subscription`, not `Users`)

### Type Hints
Use type hints for all function signatures:
```python
def get_applicable_code(code_name: str, year: int) -> dict | None:
    ...
```

### Logging
Use `coloured-logger` instead of `print()` for all application output. Reserve `print()` for temporary debugging only — it should never be committed.

```python
from coloured_logger import Logger

logger = Logger(__name__)

# Use the appropriate level for the message
logger.info("Search completed successfully")
logger.warning("Rate limit approaching for user %s", user_id)
logger.error("Failed to connect to MCP service: %s", err)
logger.debug("Parsed query params: %s", params)
```

**Level guidelines:**
- `logger.debug()` — Verbose details useful during development (parsed params, intermediate state)
- `logger.info()` — Normal operational events (search executed, cache hit, user login)
- `logger.warning()` — Recoverable issues that deserve attention (rate limit near, fallback used)
- `logger.error()` — Failures that need investigation (API errors, missing config)

---

## Django Ninja API Conventions

### Endpoint Naming
- Use noun-based paths: `/api/search`, `/api/codes`, `/api/history`
- Use HTTP verbs appropriately: `GET` for reads, `POST` for actions

### Response Format
All API responses follow this structure:
```python
{
    "success": True,
    "data": {...},      # or "results": [...]
    "error": None,      # or error message string
    "meta": {...}       # optional metadata (pagination, parsed params, etc)
}
```

### Error Handling
```python
from ninja.errors import HttpError

def search(request, query: str):
    try:
        # ... logic
    except ValueError as e:
        raise HttpError(400, str(e))
    except Exception as e:
        raise HttpError(500, "Internal server error")
```

---

## Anthropic Tool Calling Pattern

When using Claude for query parsing:

```python
import anthropic
from django.conf import settings

# Model is configurable via environment variable
CLAUDE_MODEL = settings.CLAUDE_MODEL  # Default: "claude-sonnet-4-20250514"

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# Define tool with JSON Schema
TOOL = {
    "name": "parse_building_code_query",
    "description": "Extract structured parameters from natural language query",
    "input_schema": {
        "type": "object",
        "properties": {
            "year": {"type": "integer"},
            "keywords": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["year", "keywords"]
    }
}

# Make request
response = client.messages.create(
    model=CLAUDE_MODEL,
    max_tokens=1000,
    tools=[TOOL],
    messages=[{"role": "user", "content": query}]
)

# Extract tool use from response
for block in response.content:
    if block.type == "tool_use":
        parsed_params = block.input
```

---

## HTMX Patterns

### Partial Updates
Use `hx-target` and `hx-swap` for partial page updates:
```html
<form hx-post="/api/search" 
      hx-target="#results" 
      hx-swap="innerHTML"
      hx-indicator="#loading">
```

### Loading States
```html
<div id="loading" class="htmx-indicator">
    <svg class="animate-spin">...</svg>
    Searching...
</div>
```

### Error Handling
Return error HTML fragments that can replace content areas.

---

## Environment Variables

Required variables (see `.env.example`):
- `SECRET_KEY` - Django secret key
- `DATABASE_URL` - PostgreSQL connection string
- `ANTHROPIC_API_KEY` - Claude API key
- `STRIPE_SECRET_KEY` - Stripe API key

---

## Testing Conventions

### Test File Naming
- `test_*.py` for test modules
- `Test*` for test classes
- `test_*` for test methods

### Test Organization
```python
class TestQueryParser:
    """Tests for LLM query parsing"""
    
    def test_simple_query_extracts_year(self):
        ...
    
    def test_missing_keywords_raises_error(self):
        ...
```

### Fixtures
Use pytest fixtures for common setup:
```python
@pytest.fixture
def sample_query():
    return "Fire safety for house built in 1993"
```

---

## Git Conventions

### Commit Messages
```
feat: Add search API endpoint
fix: Handle missing year in query
docs: Update README with setup instructions
refactor: Extract code resolution to separate module
test: Add tests for subscription middleware
```

### Branch Naming
- `feature/search-api`
- `fix/query-parser-error`
- `docs/setup-guide`
