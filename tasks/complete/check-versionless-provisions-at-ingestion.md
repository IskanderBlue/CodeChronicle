# Check a versionless provision once, at ingestion

**Prefix:** `b-` medium priority. Code, and actionable now.

A provision without a version does not exist. The reading code does not know
that, so it asks — in about thirty places, on every render.

## The rule

`load_edition` decides whether a provision has a version. Everything
downstream may assume one.

A provision with no version is a **load failure**, not a rendering case. It
means CCM shipped a provision row with no version payload, and the answer is to
refuse the load and say which provision, not to draw a page with a blank where
the text goes.

## Where it stands now

`api/formatters._format_single_result` guards `version` at eight call sites
(lines 371, 666, 685, 694, 700, 707, 724, 760 as of 19 August 2026), and a
ninth was added and then removed during the Crown-attribution work. A wider
count over `api/`, `core/` and `services/`, excluding tests and the
differently-named locals (`next_version`, `base_version`, `target_version` and
friends), finds **56** guards on a null provision or version:

| File | Guards |
|---|---|
| `api/formatters.py` | 9 |
| `core/management/commands/load_edition.py` | 7 |
| `core/views/exports.py` | 3 |
| `core/seo.py` | 3 |
| `core/compare.py` | 2 |
| `api/views.py` | 2 |
| `api/schemas.py` | 2 |
| eight more files | 1 each |

Not all of these are the same question, which is the first job below.

## The distinction that matters

**A provision without a version cannot happen.** Guarding it is habit. It also
costs more than the branch: it makes a real bug render a blank card instead of
failing, and it makes every reader of the code wonder which case they are
looking at.

**A result without a provision can happen**, and that guard is real. A search
result may carry an id and a title and nothing more —
`api/tests/test_formatters.py` exercises it directly. Do not remove those.

> **Superseded.** This paragraph is wrong, and the work below removes those
> guards too. The test was the only thing that built such a result; no producer
> does. See "The contract that made it safe".

The loader's own seven guards are also real: `load_edition` is the code that
decides, so it is allowed — required — to ask.

## What was done (21 August 2026)

`load_edition` now refuses a payload that ships a provision with no version
(`Command._check_every_provision_has_a_version`). The check reads the payload,
not the rows, so the message names each provision. It runs before the loader
writes the versions, inside the per-edition transaction.

**Production carries no versionless provision**: 9,744 provisions, 0 without a
version. So the downstream guards were not load-bearing, and step 5 did not
delay step 3.

### The classification

The count of 56 mixed four questions, not three. Only the first is the
invariant, and only the first was removed:

| Question | Verdict | Where |
|---|---|---|
| The provision has no version, or the result has no provision | removed | `api/formatters.py` (17), `api/schemas.py` (2), `core/seo.py` (2), `core/views/regulation.py` (3) |
| No version is **in force** on the date, or no such version number | keep | `api/views.py`, `core/views/exports.py`, `core/views/landing.py`, `core/views/guard_height.py` |
| The argument is an empty **sequence** (nothing to annotate, or a tier-gated empty) | keep | `core/cross_refs.py`, `core/compare.py` |
| The card is a **group shape** that carries no version key | keep | `core/views/exports.py` (the CSV rows), the two `{% if result.version %}` templates |

The fourth question is the one that looks like the first. A
`transition_compare` card is built from a dict literal that never sets
`version`, so a function that walks the top-level results meets a card with no
version — and that is the grouping shape, not a versionless provision.

### The contract that made it safe

`api/search/engine.py` builds each result **while it walks the versions**, and
sets `version` and `provision` in one dict literal. So every result dict
carried both. The formatter now states that: `result["version"]` and
`result["provision"]`, not `.get`. The required key is what lets mypy check the
change; with `.get`, the type stays `Any | None` and every use needs a branch
again.

The card first proposed to keep the provision guards, on the reading that a
result with an id and a title and nothing else can happen. It cannot. The
argument that removes the version guards removes these too, and it is stronger
here: a version's `provision` is a **non-null FK**, so the value is one
attribute away even from a producer that forgot the key —
`core/views/compare.py` reads it exactly that way. With the loader check in
place, both directions of the one-to-many are total.

Four signatures became honest as a result:
`core.seo.canonical_version_number` returns `int`,
`core.views.regulation._sibling_link` and `_dated_provision_url` no longer
return `None`, and `api.schemas.ResultOut.version` is required. So `/api/docs`
now states the invariant to a caller.

### The tests

- `core/tests/test_load_edition.py` — the loader refuses and names the
  provision; a refused load writes nothing.
- `api/tests/test_formatters.py` — seven tests built a result with no version
  or no provision. They now build real ones (`a_match`), because a test of a
  shape the formatter cannot meet tests nothing.
  `test_format_search_results_attaches_lineage` lost its second half, which
  asserted what a provision-less result returns.
- `api/tests/test_integration.py` — the shared fixtures gave a container
  provision no version. A real container carries an empty version, which is
  what the fixtures build now.

1,308 tests pass. `ruff` and `mypy` are clean.

## Related

The Crown-attribution helpers (`core/attribution.py`) are the counter-example
worth keeping in view. They ask a provision for its `origin_regulation` and
read the answer, with no null-version branch anywhere, because the question is
asked of the model that owns it.
