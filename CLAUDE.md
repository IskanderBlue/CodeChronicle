# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CodeChronicle is a Django 5.0 application for searching historical Canadian building codes. Users enter natural language queries (e.g., "fire safety for a house built in Toronto in 1995"), which are parsed by Claude's tool_use API into structured parameters (date, province, keywords, building_type), then searched against the in-force versions of the applicable code editions in the database.

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

# Point django.contrib.sites at this deployment's domain. The sitemap's <loc>
# URLs and allauth's email links both read that row, and Django ships it as
# "example.com". Production is already set to www.codechronicle.ca; dev is not.
python manage.py set_site_domain --domain localhost

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
- **config/** - Configuration helpers: `code_metadata.py` (`get_code_display_name()`), `keywords.py` has the valid keyword list.

### Request Flow

```
User query → RateLimitMiddleware → llm_parser.parse_user_query() (Claude API with tool_use)
→ QueryCache check/store → api/search.execute_search()
   → in-force version query (per-version window, all editions of the province's code)
   → engine.score_versions() (scores every match, no truncation)
   → _split_by_access() → relevance floor → _group_transitions()
   → _limit_with_pairs(results_per_search)
→ api/formatters.format_search_results() → SearchHistory.create()
```

That order is load-bearing. The tier split runs **before** the display limit,
so a gated searcher's cards are filled from editions they can open rather than
from whatever survived an ungated top-N; and because scoring truncates nothing,
the free-tier teaser quotes exact per-edition match totals instead of the
candidate-pool size.

Two knobs shape the tail of that pipeline, both in `config/search_limits.py`:

- **`SEARCH_RESULT_CAP`** (100) — a constant, deliberately *not* a preference.
  A page-size control and a relevance floor both answer "how much do I see",
  and two such controls disagree in public. The cap is a backstop only, and is
  named in the UI **only when it binds** (`cap_binds`, computed where the
  trimming happens — never by comparing rendered rows to the match count,
  since grouping shortens the list for unrelated reasons and the header would
  claim results were withheld that weren't).
- **`match_threshold`** — the reader's stored floor (`User.match_threshold`,
  session for anonymous, via `core/search_prefs.py`). The relevance floor a
  result must clear to count as
  a *close match*, default 0.8. **Continuous, not named tiers**: measured
  against the real corpus a fixed 0.8 keeps 20 matches on one query, 90 on
  another and 1 on a third, so no tier name can mean anything stable. The
  control (`window.ccDatum`, `templates/search.html`) instead draws the
  query's own score distribution — `score_buckets`, emitted by the
  orchestrator over the accessible matches — and the reader drags a line
  across it. Alpine redraws locally on drag; htmx re-runs the search once on
  release (`change`, not `input`). It lives in a dialog opened by clicking the
  "close matches" noun in the results header, and closes because the re-run
  re-renders the whole partial — no close-on-success wiring to keep in sync.
  Nobody arrives wanting to tune a relevance floor, so it stays out of the way
  until asked for.
  The floor applies to both sides of the tier split, so the shown count and
  the locked teaser count are measured the same way — two differently-measured
  counts of one corpus on one screen is the bug this prevents. If nothing
  clears the floor, `weak_matches_only` is set and the nearest matches are
  shown and labelled as such, rather than rendering an empty page. Note
  `close_match_count` (above the line) is distinct from
  `accessible_match_count` (what's shown, which under the fallback is the
  whole weak list) — the control reports the former or it claims a full list
  was kept while drawing every bar as dropped.

Copy rule: the noun follows the measurement. Results are only called "close
matches" where that's true — not at Everything, and not under the
`weak_matches_only` fallback (`shown_noun` / `locked_noun`, resolved in the
view).

**Scoring is BM25F over two fields, title and body** (`api/search/engine.py`).
CCM ships `keyword_counts` (the title + body + table-text union) alongside
`title_keyword_counts` (the title alone, same tokenizer); the body's counts are
the difference, floored at zero. Two rules the maths depends on:

- **Saturate once, across both fields.** Field contributions are summed as
  length-normalized frequencies *before* the `k1` saturation, not scored
  per-field and added — otherwise a long body and a matching title each
  collect a near-full `k1 + 1` and a document doubles the intended ceiling.
- **With no title counts it reduces exactly to the old single-field BM25**
  (`raw*(k1+1)/(raw + k1*norm)` is algebraically `saturate(raw/norm)`), so an
  edition loaded before CCM emitted the field ranks as it always did rather
  than ranking wrongly. Reload to enable the weighting.

`BM25F_TITLE_WEIGHT` (3.0) is the one knob worth tuning. The title field exists
because a merged bag can't tell a provision that *is* "Maintenance Inspection
Program" from one mentioning the phrase once — after tokenization both are the
integer 1 — and because it relieves a real tension in `BM25_B`: b was set to
0.75 to suppress the Part 11 "Compliance Alternatives" mega-tables, but b only
knows "long is suspicious" and punishes long *relevant* provisions identically.
The title tells them apart. `avg_title_len` averages over titled versions only
— a missing field is not a short field. Note CCM's tokenizer does no stemming,
so the title boost must apply to indirect (LLM-variant) terms too, or it fires
on the user's choice of plural.

Search is DB-backed end to end. There is no edition-resolution step — the
in-force filter runs at the **version** level (`effective_date <= d <
ineffective_date`) across every edition of the province's code, which is what
lets two editions' versions co-exist during a transition. The old
`building-code-mcp` dependency is gone; its `SYNONYMS` table — the last thing
CodeChronicle used from it — is vendored at `config/synonyms.py`.

### Frontend

Django templates + HTMX + Alpine.js + Tailwind CSS (CDN). Templates live in `templates/` with HTMX partials in `templates/partials/`. The search page uses `hx-post` for partial page updates without full reloads.

### Settings

Split settings in `code_chronicle/settings/`: `base.py`, `development.py`, `production.py`. Tests use `development` settings (configured in `pyproject.toml`). Key env vars: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `DATABASE_URL`.

### Rate Limiting & Subscriptions

The anonymous allowance runs in **three bands**, decided by
`core.middleware.RateLimitMiddleware`:

| Searches today | Band | Behaviour |
|---|---|---|
| `< RATE_LIMIT_ANONYMOUS` (1) | full | Results as normal |
| `< RATE_LIMIT_ANONYMOUS_TEASER` (10) | teaser | The search **runs**; the text is withheld |
| above that | hard | 429, and the search does not run |

The middleware never runs a search itself. In the teaser band it sets
`request.search_teaser_only` and returns `None`; `core.views.search` then calls
`_teaser_context()`, which returns provision ids, titles, editions and counts —
identity only, via the same `api.search.orchestration.identity_preview()` the
free-tier locked list uses, so the two teasers cannot drift apart on screen.

Both the teaser band and the hard band record an
`EngagementEvent.EventType.RATE_LIMIT_BLOCK` with `context.band`, because the
conversion denominator counts *intent* — the reader asked and we withheld —
not which wall the intent met. The hard band exists because the teaser costs
an LLM parse per request; without a ceiling it is an open tap.

Authenticated users (free and Pro): unlimited searches. Content gating lives in
`core/access.py` (unconditional): anonymous and non-Pro users are scoped to the
editions in `FREE_TIER_CODE_NAMES` (OBC 2006); Pro (Stripe/dj-stripe or
`pro_courtesy` flag) is unrestricted. History:
`tasks/complete/free-tier-obc2006-scope.md`.

The Pro **price** is never a literal: `core/pricing.py` reads the mirrored
dj-stripe `Price` row keyed by the same `STRIPE_PRO_PRICE_ID` that checkout
uses, so the page and the charge cannot disagree, and a change in the Stripe
dashboard needs no deploy. It always returns a number — three logged fallback
paths — because a pricing page that 500s is worse than a stale figure.

### Clickwrap versions

The signup checkbox covers both documents, but they are stamped **separately**:
`TERMS_VERSION` and `PRIVACY_VERSION`, recorded on `TermsAcceptance`. One shared
stamp forced a false choice whenever only one document changed. Bump only the
document that changed. Full reasoning:
`tasks/complete/privacy-copy-for-collected-email.md`.

## Marketing & discovery surfaces

- `core/sitemaps.py` — `/sitemap.xml` (index) plus `pages` and `provisions`
  sections. Free-tier scope only, and **one URL per provision** at its highest
  version, not one per version.
- `core/seo.py` — per-page title, meta description and canonical URL. It owns
  the **canonical-version rule** (highest version wins); `core/sitemaps.py`
  implements the same rule set-based. Change one and you must change the other.
- `templates/robots.txt` — served by `RobotsView`, with a request-derived
  absolute sitemap link.
- `/insights/` (`core/insights.py`, staff only) — traction totals, per-day and
  cumulative charts, most-repeated queries, the edition-request queue, and the
  reader-report triage queue.
- `EditionRequest` (`core/views/demand.py`) — "which edition do you need?"
  demand capture. The need is required; the email is optional.
- `ProvisionFeedback` (`core/views/feedback.py`) — the "This looks wrong"
  reader report, free for everybody including anonymous readers. The trigger
  lives in the attestation rail's trailing affordances, beside "How to read
  this", and is opt-in per surface (`allow_report`) so the landing page's
  specimen band and the verification guide's example rails do not offer it.
  **The target is stored as text, never a FK**: `load_edition` replaces every
  provision and version pk on reload, and a report must outlive that. Two
  target shapes — provision (edition/division/id/version) or regulation
  (edition + `reg_id`) — and the queue resolves either back to a live URL at
  read time.

## Exports

Four ways to take something out of the product, all shipped at once and all
instrumented, because we could not guess which one a code consultant reaches
for. Each records an `EngagementEvent.EventType.EXPORT` with `context.kind`;
`/insights/` shows the counts (`core.insights.export_counts`), and
`tasks/b-exports-60-day-review.md` is the promise to read them on 3 October
2026 and remove what nobody used.

| Kind | Where |
|---|---|
| `citation` | The "Cite" menu in the attestation rail (`core/citations.py`) |
| `provision_pdf` | `/provision/…/print/` — the `for_print` branch of `provision_permalink` |
| `results_csv` | `core.views.exports.results_csv` |
| `comparison_pdf` | `/compare/print/` — the `for_print` branch of `compare_versions` |

Rules that hold across all four:

- **The gate is the gate** (`core/access.py`), on the read path and the write
  path both. A refusal must never also be counted as value delivered.
- **The citation is open to everybody**; the other three need a free account.
  A citation carries our URL into somebody else's document, which is the point
  of it; the rest are work product.
- **Every export states its retrieval date.**
- **The window is stated in days actually governed.** The stored window is
  half-open, so a citation that says "to" names the day *before* the end date.
  `core.seo.last_governed_day` owns that conversion for the whole product —
  the page title, the JSON-LD interval, the nav tooltips, the cross-reference
  chips and the citations all call it, because three private copies gave three
  answers. `core.citations.in_force_phrase` puts it in prose, and
  `core.seo.effective_window` closes an open version at its edition's end.
- **A citation links its own version, not the canonical one.** The canonical
  rule concentrates crawler ranking on the highest version; a citation pins a
  text to a date, and a link to a different text is the one failure an exhibit
  cannot survive.

Two citation formats, plus the incumbent: **Legal** (McGill Guide, for a
factum), **Report** (practice form, and the one that carries the URL and the
retrieval line), and **Reference** (the structured provenance block the band's
copy icon produced before this work — folded into the same menu so one control
answers "how do I quote this", and measured like the other two so it can lose).

**Printing is the browser's job.** There is no PDF library and no headless
browser on the server: the print pages render from the same partials the
reading pages use — that is what stops an exhibit showing something the
product does not — and a second layout engine would break exactly that. The
two print pages share `templates/partials/_print_shell.html` and
`_print_script.html`.

**Scans are cropped to the provision** (`core/page_crops.py`). A page image is
a whole scanned page and the bboxes mark the provision on it; on paper the rest
of the page is somebody else's text. Two rules: a crop is its own bbox plus a
small margin, **never** the union of a page's bboxes (these pages are set in
two columns, and a union of two column regions is the whole page again); and
**one scale for the whole provision** — the widest crop fills the printable
width and the rest are drawn in proportion, so a narrow fragment does not print
in giant type beside a wide table in tiny type. The crop is CSS; the only value
CSS cannot supply is the wrapper's height, because CCM ships no image
dimensions, so the print script reads each image's own proportions once it
loads.

**A scan already shows its tables**, so the printable surfaces do not repeat
them as separate figures (`core/print_options.py`). CCM ships a table twice for
a scanned edition — inside the page image, and again as a
`ProvisionVersionTable` row — and on the reading page the second copy sits
behind a disclosure, so nobody meets both. On paper both print, and an exhibit
showing one table twice invites the question of which copy is the evidence. The
decision is **per version**, not per page: an image-rendered version suppresses
its table rows, an HTML-rendered one keeps them (there the tables are not in
`version.html` and appear nowhere else). `?tables=on` / `?tables=off` override
it, and the print page carries the link.

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

- `anthropic` - Claude API client for natural language query parsing
- `django-allauth` - Email-only authentication (no username field)
- `dj-stripe` - Stripe subscription management
- `boto3` - S3 access for code PDF map files
- `rapidfuzz` - Fuzzy string matching for keyword resolution
