# Landing page

Status: **done**. Shipped in commit `d75c5fa`
(`feat(landing): add the public front page, and mount the real components on it`).
The suite is green (625 tests at the time of the move); `ruff check .` is clean.

`tasks/complete/component-reuse-fidelity.md` is also done: the search form is one
partial rendered by all three call sites, the specimen widths read the working
grid's own tokens instead of a transcribed number, and the verification-rail
guide shows the whole IN FORCE band rather than a bare rail on the page
background.

## What it is

A public front page at `/`, with the value proposition of the corpus. The page
is `templates/landing.html`; the view is `core/views/landing.py`; the tests are
`core/tests/test_landing.py` (18 tests).

## Routing change

The search page moved. `/` is now the landing page.

| URL | View | Behaviour |
|---|---|---|
| `/` | `core.views.landing` (`core:landing`) | The front page. A signed-in reader gets a redirect to `/search/`. |
| `/about/` | the same view (`core:about`) | The same page. No redirect, so the page stays reachable for a signed-in reader. The footer links here. |
| `/search/` | `core.views.search_page` (`core:search`) | The search page. The old name was `core:home`. |

The redirect comes from a URLconf extra kwarg (`redirect_signed_in`), not from
the route name, so you can see the behaviour where the routes are declared.

`?d=YYYY-MM-DD` on `/search/` sets the AS-OF picker. The picker is the date the
search runs at, so a link that carries only `?q=` runs at the corpus default
date. A malformed value falls back to the default.

## Rules the page obeys

1. **No number is typed by hand.** Every figure comes from the view, which
   reads the same tables the search reads. The `verified` flag is the filter,
   the same gate the Sources page uses.
2. **No claim about e-Laws that we cannot support.** e-Laws publishes
   period-in-time consolidations, so the page must not say it only shows the
   current text. The two differences the page does claim are reach (the online
   consolidation record starts 2003-09-01; coverage starts 1998-04-06) and
   provenance (a consolidation gives the words, not the regulation and clause,
   and its citations are not links).
3. **Layout is Tailwind; anything named or computed is an `lp-` rule.**

## Content decisions

- The two reconstruction routes are **regulation-parsing** (what we publish,
  shown first) and **historical-version comparison** (the independent check).
  Do not call them Path A and Path B.
- `DIFFERENCE_CLASSES` in the view holds all 11 `known_safe_kind` values, each
  with a gloss and a worked example `(edition, division, provision_id,
  version)` taken from a real parity-report item. The view builds a permalink
  for each. An example outside the free tier gets a `Pro` chip, because the
  link opens the locked-edition teaser.
- **OBC 2006 raised only 3 of the 11 classes**, so the other 8 examples must
  come from OBC 1997 or 2012. `occurs_in` records which editions raised each
  class, and the page prints it where OBC 2006 is not among them. Without it a
  reader takes the edition for a choice. `occurs_in` is transcribed from CCM's
  parity reports, never counted live; it names editions and carries no
  quantity, which is what keeps rule 1 true.
- `non-keyword-table-ocr` only occurs in the scanned pre-e-Laws era (OBC 1997),
  and only on tables shown as the page image. The reader sees the scan, so the
  OCR noise behind it only affects what the table matches on in search.
- **Section III imports the shipping components; it does not imitate them.**
  Each row shows a real specimen:

  | Row | What it renders | Source |
  |---|---|---|
  | 01 | `partials/_search_form.html` | the search page's own form, `mode="handoff"` |
  | 02 | `partials/_provenance_rail.html` | `_provenance_result` on `SPECIMEN` |
  | 03 | `partials/_provenance_band.html` | the same result mapping |
  | 04 | The provision html with live citations | `core.cross_refs.annotate_versions`, `fan_out=True` |
  | 05 | Two source chips | real `Regulation` rows, one per `source_kind` |

  Row 03 mounts the **whole IN FORCE band**, not the rail alone. The rail never
  appears by itself in the product: it is the band's body, and the band paints
  `bg-secondary-soft`. A rail on the page background is the wrong colour and the
  wrong object. The `.rail-legend` wrapper force-shows the graphic, which the
  live rail gates behind `@xl`; that is the same wrapper the verification guide
  uses, for the same reason.

  Row 01 and the hero render the real search form, in `handoff` mode: a plain
  GET to `/search/`, which reads `?q=` and `?d=`. They were two hand-drawn
  miniatures, and both had already lost the form's Jurisdiction cell — so the
  front page advertised a control the product does not have.

  **The specimen widths are computed, never typed.** `.lp-mount-centre` reads
  `--ws-centre` and `.lp-mount-rail` reads `--ws-rail`, the same tokens
  `.ws-cols` builds the working grid from (`base.html`). Width matters as much
  as colour here: the attestation rail collapses its staggered labels once its
  own container clears 46rem, so a specimen at the wrong width shows a layout no
  reader can reach. The two numbers that used to sit here were transcribed from
  another page's grid, and one of them was 31px wrong.

  `SPECIMEN` is Article 1.1.2.4. of Division A in OBC 2006, at version 2. It
  serves rows 02 and 04 together. Three properties earn it the job: it is
  inside the free tier, it has a three-regulation chain and a mapped OBC 1997
  predecessor, and one of its citations resolves to two versions on
  `SPECIMEN_DATE` — which is the fan-out case row 04 explains.
  `core/tests/test_landing.py::TestSectionThreeSpecimens` fails if a row goes
  back to hand-written markup.
- **The specimen box paints no fill.** `.lp-spec` sets a border and padding
  only. A fill puts an imported component on a backdrop it was not built
  against, and the component's knockout marks then fill with the wrong colour.
  If a fill is ever wanted, set `--backdrop` to the same token in the same rule.
  See `TestBackdropKnockouts` in `core/tests/test_templates.py`.
- The corpus table shows `last_day` (the inclusive final day), not
  `ineffective_date` (which is exclusive and shows the next edition's start).

## Open questions, and where each one stands

1. **Free-tier scope — answered.** The scope stays OBC 2006. Pro sells every
   covered edition, and the pricing page now names OBC 1997 first, because it
   is the one edition a reader cannot get anywhere else (commit `c2a2e09`).
   Eight of the 11 difference-class examples still open a locked teaser. That
   is the intended behaviour: the teaser is the argument for the paid tier.
2. **Still open.** `templates/data_sources.html` prints `ineffective_date`
   raw at line 108, so its "Until" column keeps the off-by-one-day reading
   that the landing table avoids. The fix is the same one: show `last_day`.
3. **Still open.** Only two "try this" examples are in free scope, and both
   carry the date 2010-06-01. `EXAMPLE_QUERIES` in `core/views/search.py`
   needs a third OBC 2006 example.

Item 2 and item 3 are small and have no card. Write one if either survives
the next pass over the search page.

## Local development note

`docker-compose.yml` publishes Postgres on 5432. Another project also uses
5432. `.tmp/docker-compose.port5433.yml` moves it to 55432 if the port is busy.
Build the CSS before you look at the page:
`.\tailwindcss.exe -i static/css/input.css -o static/css/tailwind.css --minify`.
Templates do not hot-reload; restart `runserver` after a template edit.
