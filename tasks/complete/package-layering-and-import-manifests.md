# Package layering and import manifests

**Done, 22 August 2026.** Tier 3 of the structural guard work.

The `core` / `api` cycle is gone. The repository holds eight packages, each
declaring the packages it may import, and the declared graph is a DAG.

Result: 1456 tests pass (1452 before, plus the four new manifest checks),
`ruff check .` clean, `mypy .` clean on 209 files.

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

## The measured graph

Every edge points downward. There is no cycle.

```
shared     -> ()
data       -> ()
core       -> data
accounts   -> shared, core
telemetry  -> shared, data, core
corpus     -> shared, data, core, accounts
search     -> shared, data, core, accounts, corpus
web        -> shared, data, core, accounts, telemetry, corpus, search
```

Two edges reach `accounts` from below the delivery layer, and both are
deliberate: `corpus/sitemaps.py` (the sitemap is free-tier scoped) and
`search` (the tier split runs before the display limit). The earlier
decoupling work removed the other three, by passing the gate in as a
`Callable[[str], bool]`.

## What changed beyond the plan

- **`core/apps.py` split.** `CoreConfig.ready()` registered the asset-signing
  check and imported three signal modules. Those moved to `CorpusConfig` and
  `AccountsConfig`. `core/apps.py` now has no `ready()`.
- **`INSTALLED_APPS` gained five entries, not six.** `search` holds no model,
  no command and no template tag library, so it is a plain package.
- **Two config files carried the package list by name**, and both went stale
  in the same way. The `Dockerfile` copied four directories; it now copies all
  eight, and a package missing there is an `ImportError` at container boot.
  The `mypy` pre-commit hook passed `["api", "core", "config",
  "code_chronicle"]`; it now passes `["."]`, which cannot go stale. Neither
  failure shows up in `pytest`: the hook answered "Duplicate module named
  `__main__`", which names nothing useful.
- **Rule 1 of `test_module_conventions.py` lost its allowlist.** It named
  `core/apps.py`. Three `apps.py` files now have a `ready()`, so the
  exemption is derived from the filename instead. The guard keeps its promise
  of zero allowlist entries.
- **Rules 4 and 5 gained the derived manifest exemption**, as planned — a
  package `__init__.py` may bind `ALLOWED_IMPORTS`, and two such packages may
  bind the same empty tuple.
- **The URL namespace moved too.** `web/urls.py` sets `app_name = "web"`, and
  every `core:<route>` reference became `web:<route>` — 81 files. The
  namespace is a separate name from the package, so it could have stayed
  `core`; it did not, because a reader who meets `web:pricing` in a template
  should find it in `web/`. Only the 46 route names `web/urls.py` declares
  were replaced, so prose that writes "core:" is untouched.
- **`pyrightconfig.json` listed the old packages** and now lists the new ones
  plus `tests`.

## What the tests actually prove

The suite resolves all seven settings strings, not five: two tests post the
real allauth signup form (`tests/accounts/test_clickwrap.py` and
`test_signup_notice.py`), so `ACCOUNT_ADAPTER` and `ACCOUNT_SIGNUP_FORM_CLASS`
are exercised. No manual server run is needed as a backstop.

Each manifest check was proved to bite before the work was called done: an
undeclared import, a declared cycle and a stale entry each failed the suite,
and each failure named the offending file and line.

## Verification

```bash
ruff check .    # All checks passed
mypy .          # Success: no issues found in 209 source files
pytest          # 1456 passed
```
