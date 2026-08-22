# Package layering and import manifests

Tier 3 of the structural guard work. Tiers 1 and 2 are complete: five rules in
`core/tests/test_module_conventions.py`, no allowlist entries.

This card breaks the `core` / `api` cycle by moving modules into ranked
packages, then makes each package declare the packages it may import.

## Why the cycle is not real today

Every upward import starts in `core/views/`, `core/management/commands/` or
`api/views.py`. No domain module reaches upward. The cycle is an artifact of
two packages that each hold both a domain layer and a delivery layer.

## The target tree

Nine Python packages at the repository root. `manage.py` stays at the root.

```
CodeChronicle/
├── code_chronicle/     settings/  urls.py  wsgi.py
│
├── shared/       rank 0   ip.py  email.py  html.py
├── data/         rank 0   keywords.py  query_keywords.py  synonyms.py
│                          part_applicability.py  search_limits.py  assets.py
│                          code_metadata.py  exports.py  guard_height_article.py
│                          elaws_consolidations.json
│
├── core/         rank 1   models.py  migrations/  admin.py  apps.py
│                          provision_notes.py  code_names.py
│
├── accounts/     rank 2   access.py  teams.py  pricing.py  reacceptance.py
│                          forms.py  adapters.py  apps.py
│   └── signals/           auth_audit.py  signup_notice.py  stripe_handlers.py
│   └── management/commands/  backup_userdata.py  link_stripe_customers.py
│
├── telemetry/    rank 2   events.py  insights.py  reading_ledger.py
│                          attribution.py  apps.py
│   └── management/commands/  purge_reading_records.py
│
├── corpus/       rank 3   permalinks.py  seo.py  cross_refs.py  citations.py
│                          provision_levels.py  asset_signing.py  sitemaps.py
│                          apps.py
│   ├── lineage/           provision_lineage.py  compare.py
│   ├── verification/      verification.py  rail_examples.py
│   ├── printing/          page_crops.py  print_options.py
│   └── management/commands/  load_edition.py  load_consolidations.py
│                          refresh_corpus_currency.py  sync_images.py
│                          make_social_card.py  notify_edition_requests.py
│
├── search/       rank 4   service.py  prefs.py  apps.py
│   ├── engine/            engine.py  orchestration.py
│   ├── llm/               llm_parser.py
│   └── formatters/        formatters.py  band.py
│
└── web/          rank 5   urls.py  middleware.py  http_cache.py
    │                      context_processors.py  apps.py
    ├── views/             the 17 files now in core/views/
    ├── api/               views.py  auth.py  provisions.py  schemas.py
    ├── templatetags/      unchanged filenames
    └── management/commands/  set_site_domain.py  verify_guard_height_article.py
```

`api/` and `services/` and `config/` disappear.

## Placements that are not obvious

- **`core/code_names.py` stays in `core`.** `accounts/access.py` imports it, so
  it must sit below rank 2. It reads `data.code_metadata` and `core.models`
  only.
- **`core/search_prefs.py` becomes `search/prefs.py`.** Only web views import
  it, and it is the relevance floor.
- **`verify_guard_height_article` goes to `web`.** It checks a web page's
  claims, and `web` already imports `search`, so `formatters.diff_similarity`
  is a downward import there. It stays a command and does not become a test:
  it reads the shipped database, and a test reads a fixture.
- **`notify_edition_requests` goes to `corpus`.** It is about editions.
  `telemetry` is defensible; pick one and do not move it again.
- **`core/` gets no commands.** It holds the models and nothing else.

## What does not move

`core/` is not renamed, so `core/migrations/` needs no surgery, every
`ForeignKey("core.X")` string still resolves, and `AUTH_USER_MODEL` and
`DJSTRIPE_SUBSCRIBER_MODEL` stay as they are. This is the reason `core` keeps
its name.

## Settings strings to rewrite

Django reads these as text, so no import rewriter finds them. All are in
`code_chronicle/settings/base.py`.

| Line | Now | After |
|---|---|---|
| 55 | `core.http_cache.PublicCacheVary` | `web.http_cache.PublicCacheVary` |
| 64 | `core.middleware.RateLimitMiddleware` | `web.middleware.…` |
| 69 | `core.middleware.TermsReacceptanceMiddleware` | `web.middleware.…` |
| 85 | `core.context_processors.masthead_currency` | `web.context_processors.…` |
| 86 | `core.context_processors.page_metadata` | `web.context_processors.…` |
| 203 | `core.adapters.AccountAdapter` | `accounts.adapters.AccountAdapter` |
| 217 | `core.forms.CustomSignupForm` | `accounts.forms.CustomSignupForm` |

`INSTALLED_APPS` lines 47-48 become six entries: `core`, `accounts`,
`telemetry`, `corpus`, `search`, `web`. Django finds a command only inside an
`INSTALLED_APPS` entry, so every package that holds one must be an app.

Also rewrite: `ROOT_URLCONF` includes in `code_chronicle/urls.py`, and
`pyproject.toml` `[tool.setuptools.packages.find] include`.

`load_consolidations` reads `BASE_DIR / "data" / "elaws_consolidations.json"`.
`data/` stays at the root, so that path does not change.

## The manifests

Each package `__init__.py` declares its neighbours:

```python
# corpus/__init__.py
ALLOWED_IMPORTS = ("shared", "data", "core")
```

`tests/structure/test_import_manifests.py` reads every module with `ast` and
checks three things:

1. Every cross-package import is declared.
2. Every declaration is used. A stale entry is a lie about the shape.
3. The declared graph has no cycle.

The graph is checked for a cycle rather than against rank numbers, because
`accounts` and `telemetry` are genuinely independent of each other and a rank
number would claim an order that does not exist.

Rule 4 of `test_module_conventions.py` forbids a duplicate module-level name.
Nine copies of `ALLOWED_IMPORTS` breach it. Add a **derived shape exemption** —
a package `__init__.py` may declare the manifest name — not an allowlist entry.
Same technique as the `BaseCommand` exemption.

## Order of work

Do not start phase 1 until the parallel session's work lands. About 35 modified
and 25 untracked files sit in the tree, many in `core/views/`, which this move
rewrites.

**Phase 1 — the move.** Use `git mv`, so the history follows the file. Rewrite
imports, the settings strings and `pyproject.toml`. The suite must return the
same 1417 passed.

**Phase 2 — the tests.** Move the tests to a root `tests/`, one directory per
package. `pyproject.toml` has no `testpaths`, so add one.

**Phase 3 — the manifests.** Write the nine `ALLOWED_IMPORTS` and the guard
test. Add the derived shape exemption to rule 4.

Commit each phase separately. Phase 1 is a pure move and must stay reviewable
as one.

## Verification

```bash
ruff check .
mypy .          # expect: Success, 171 source files
pytest          # expect: 1417 passed
```

The suite resolves the middleware and the context processors, because a test
client request loads them. It resolves the allauth strings only if a test signs
somebody up. Run the development server once after phase 1 and open one page,
as the cheap backstop.
