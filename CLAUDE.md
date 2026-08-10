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

# Load a CCM consolidated edition (provenance models) into the DB.  This loads
# ONE edition, the default OBC_2012.json.  Add --file to pick another.
python manage.py load_edition --source ../CodeChronicleMapping/data/outputs

# Load every edition in that directory, oldest first.  Use this to rebuild the
# corpus from empty (a restore, a fresh dev DB).  The order matters: loading an
# edition deletes the cross-edition rows touching it, and the newer edition's
# payload is what puts them back.
#
# Either form finishes by calling load_consolidations, because loading an
# edition deletes that edition's consolidation rows (FK, CASCADE) and nothing
# else restores them.  Pass --skip-consolidations to stop that.
python manage.py load_edition --source ../CodeChronicleMapping/data/outputs --all

# Tell the people who asked for an edition that it has landed. Run by hand,
# when an edition ships. Prints a report and sends nothing without --send;
# read the message yourself before you add that flag. A human picks the
# recipients (--match / --ids) because code_text is free text.
python manage.py notify_edition_requests \
    --about "OBC 1997" \
    --news "The 1997 Ontario Building Code is now on CodeChronicle." \
    --search "guards and handrails for a stairway" --date 1999-06-01 \
    --match 1997

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

**The address bar holds the search that ran.** `hx-post` does not change the
address, so a reload used to throw the search away. `core.views.search._push_search_url`
answers with `HX-Replace-Url` and rewrites it to `/search/?q=…&d=…`, which
`search_page` already reads and auto-runs (the `data-autorun-search` block in
`templates/search.html`). So a reload, a bookmark and a link a reader sends
somebody all reproduce the search. Three rules:

- **The view writes it, not a script.** The AS-OF picker overrides the date
  the parser reads out of the query text, so only the view knows the date the
  search used.
- **A new search pushes; re-measuring one replaces.** The relevance-floor
  control re-posts through the same view without changing the query, so
  pushing there would stack identical entries and Back would look broken. The
  view tells them apart by `match_threshold` in the post — that field lives in
  the results partial, not in the search form, so only the floor control sends
  it.
- **A failed search writes nothing.** Nothing ran, so there is nothing to
  reproduce.

**Back reloads.** One `popstate` handler in `templates/search.html` does two
jobs in order: it closes the viewer overlay if the overlay is open and stops
there, because the overlay pushes an entry carrying the same address; then it
reloads. The reload runs whatever the address says, so the page cannot show
one search while the address names another. It reuses the seeded auto-run
rather than restoring the results in JavaScript, which would be a second copy
of that logic.

**A reload costs an anonymous reader nothing.** `RateLimitMiddleware` counts
*questions*, not requests — see `_other_questions_today`. A question is the
query text with the date it ran at, and the question being asked now is left
out of the count, so a reload, a Back, or the reader's own link leaves the
number unchanged. Two rules hold it together: the same words at two dates are
two questions (that is the product), and distinct questions still reach the
hard band, so the LLM-parse tap stays capped.

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

### The new-account notice

`core/signup_notice.py` writes to `settings.SIGNUP_NOTICE_EMAILS`
(`rob@codechronicle.ca` by default, env-backed, comma-separated) when somebody
creates an account. Three rules:

- **It hooks allauth's `user_signed_up`, not `post_save` on the user.** The
  model signal fires on every profile edit and on accounts made by a script;
  neither is somebody arriving at the product.
- **It never breaks a signup.** The account already exists when the receiver
  runs, so an unguarded failure would lose the notice *and* show a 500 to a
  reader whose signup actually worked. Same reasoning as `core.auth_audit`.
- **An empty list switches it off**, which is what a local run wants.

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
  demand capture. The need is required; the email is optional. The band
  promises we will write when the edition lands, and
  `notify_edition_requests` keeps that promise. `notified_about` is a **list**
  of edition labels, not one stamp: a row may name two editions, and one
  timestamp would spend it on the first. That list is also what makes a
  re-run safe after a part-way failure.
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
  `core.seo.effective_window` supplies the window. That window is **the
  version's own**: CCM computes these dates and lets a window run past its
  edition on purpose, because a transition overlap is two editions' versions
  in force at once. The edition's end is a fallback for a **null** end only,
  where a version would otherwise read as open-ended and open-ended reads as
  current. Eight loaded versions run past their edition; CCM's
  `tasks/future/a-verify-windows-past-edition-end.md` asks it to confirm each
  one is a real overlap rather than an unclipped window.
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

## Crawlers: what they cost, and what they can reach

Almost all traffic is machines. In 13 days to 10 August 2026 the site served
**21,467 provision page views against 27 searches**, and the nginx user agents
name the callers: GoogleOther, MJ12bot, meta-externalagent and Amazonbot each
outrank Googlebot, which is under 10% of the load. Every one of them declares
itself and obeys `robots.txt`.

**A permalink is a subtree, not a provision.** `provision_permalink` renders
the matched provision and all its descendants, so `OBC_2006/B/Part 9` is 1,339
provisions and about 1.9 MB of database reads in one request. That is why the
crawl cost 545 MB of reads while the whole database is 142 MB, and it is the
first thing to weigh before adding a query to that view.

**Over `CONTENTS_THRESHOLD` (40) the page shows what is inside instead**
(`core.views.regulation`, `templates/partials/_provision_contents.html`). Not
pagination: page 3 of Part 9 is not a thing a code consultant can ask for, and
`?page=` would multiply the URL count when the point is to cut the work.
Measured over the free-tier corpus, this takes provision renders from
**15,170 to 7,472** across the same 3,225 URLs, and the worst single page from
**2,934 provisions to 84 rows**. Four rules:

- **The switch is by measured size, not by level name.** A "section" runs from
  0 to 201 descendants here, so the name does not predict the cost. Measuring
  also means a differently-shaped edition needs no new rule.
- **Nothing becomes unreachable.** Every child is still linked, one hop
  further on, so a crawler still walks the whole corpus. **Nothing above
  article level carries text** — every division, part, section and subsection
  has an empty body — so a container page *is* its links. The rendered
  sub-provisions link to their own permalinks (`section.url`), because the
  rail's "Subprovisions" names only the direct children and left everything
  deeper reachable only by going back up.
- **The page states the number it is withholding.** "Too much to show" is a
  judgement a reader cannot check. `_descendant_count` asks for the total with
  one recursive query, because the walk stops early on purpose and so never
  learns it. An empty body is also never reported as missing text on a
  container (`is_container`); that message claimed a fault on every part and
  division page in the product.
- **It removes a duplicate-text problem, not only a cost one.** An article's
  text used to appear on five URLs — its own, and each of its four ancestors'
  — with nothing to say which is the subject, because the canonical rule picks
  the highest *version* and says nothing about containment.
- **The exhibit follows the page**, through the same partial. The alternative
  is a 1,339-provision PDF.

The walk already ran a generation at a time, so the limit is a stopping
condition rather than a second query. It stops on the generation that would
breach the limit, so at worst it loads one generation too many — bare
provision rows, where the cost avoided is their versions, tables and scans.

**The read surfaces answer 304.** `core/http_cache.py` gives
`provision_permalink`, `regulation_detail`, `compare_versions`,
`edition_contents` and `edition_chain` a `Last-Modified` taken from
`CorpusCurrency.refreshed_at`. Four rules:

- **Anonymous readers only.** The tier gate makes the same URL render
  differently for a Pro reader, so a reader-blind validator would let somebody
  who has just subscribed keep a cached locked page. Anonymous readers are
  uniformly free-tier, so one stamp describes them all.
- **A deploy bumps the stamp**, because `scripts/entrypoint.sh` runs
  `refresh_corpus_currency`. Without that a template change would keep
  answering 304 and serve the previous image's markup.
- **The print routes carry no validator.** They send an anonymous reader to
  the login page, so they have no anonymous body to validate.
- **Only a 200 or a 304 carries the validator.** Django's `condition`
  decorator stamps every safe-method response whatever its status, so the
  decorator strips it again. A 404 that handed out a `Last-Modified` can later
  be answered 304, which tells a crawler its cached miss is still current.
- **A 304 records no `EngagementEvent`**, which is correct — a 304 is not a
  reading — but it does lower the `/insights/` view totals against their own
  history. The drop is bots leaving the count, not readers.

The stamp must move whenever anything a decorated view could return changes,
including a provision ceasing to exist; `CorpusCurrency` moving on every load
is what guarantees that. Where there is no `CorpusCurrency` row — the window
after a restore, before `load_edition --all` — there is no such guarantee, so
the validator is withheld rather than invented.

**The edge stores the anonymous copy.** A 304 still costs a render; an edge
hit costs nothing at Django. `modules/cloudflare/main.tf` marks the five read
surfaces cacheable, and `core/http_cache.py` decides for how long
(`EDGE_MAX_AGE`, one hour). Four rules:

- **The app owns the TTL**, not the rule. The rule says `respect_origin`,
  because the app is what knows when the corpus changed. A TTL in Cloudflare
  would put that decision in two places that cannot see each other.
- **The tier gate is stated twice, on purpose.** The rule bypasses the cache
  when a `sessionid` cookie is present, *and* the app sends
  `private, no-store` to a signed-in reader. Either alone is sufficient, so a
  wrong rule cannot serve a free-tier page to a subscriber.
- **`Vary: Cookie` is gone.** Cloudflare honours `Vary` only on
  `Accept-Encoding`, so any other value made the page uncacheable — the whole
  cost problem. `SessionMiddleware` adds the header after the view runs, so
  `core.http_cache.PublicCacheVary` removes it from the outside and must stay
  **first** in `MIDDLEWARE`.
- **No form renders on a read page.** A response carrying `Set-Cookie` is one
  no shared cache stores, and one `{% csrf_token %}` in a hidden dialog is
  enough to attach one. Both dialogs fetch their panel instead
  (`core:citation_panel`, `core:report_form`); `test_no_cookie_is_set_on_a_read_page`
  fails if a form comes back.

Nothing purges the edge on deploy, so a template change can stay invisible for
up to `EDGE_MAX_AGE`. Going stale is cheap — Cloudflare revalidates with
`If-Modified-Since` and the origin answers 304 — so this is a staleness
window, not a cost.

**`templates/robots.txt` refuses what costs and returns nothing**: the print
routes (every provision links its own, and an anonymous request is a login
redirect), and the backlink crawlers. Search and AI crawlers are deliberately
left welcome — refusing those is a product decision, not a cost one. Rules for
everybody must sit **above** the first named `User-agent:` line, or they bind
to nobody.

**`/compare/` stays indexable, and that is measured rather than assumed.** It
looks like the expensive, unbounded surface and is neither. `annotate_chain_comparisons`
**order-normalises** the pair (the earlier version is always `a`), and links
only join versions of one provision plus one lineage hop, so the free-tier
corpus offers **408** comparisons from the 308 provisions with more than one
version. A comparison renders two versions, not a subtree: **~16 kB** against a
permalink's 26 kB average and a root permalink's 1.9 MB. It is also the only
page that answers what changed between two versions, which is the product.

**The scans are gated at the edge** (`core/asset_signing.py`,
`config/assets.py` `SIGNED_PREFIXES`). In production a Cloudflare Worker
answers the mirrored asset trees from R2, so Django is not in the path and
`edition_allowed` never runs on an image. `documents/` holds the whole-page
scans — the primary evidence, for an edition we gate — and its keys are
sequential, so the edition could be walked page by page without ever loading a
gated page. Django now signs those URLs and the Worker refuses an unsigned one.

- **The asset gate is the page gate.** A token is only minted while rendering
  a page `core.access` already allowed, so the two cannot drift.
- **The token does not expire.** An expiring token cannot survive the 304s
  above, or a printed exhibit outliving its footnotes. What it defeats is
  enumeration, not somebody re-posting a URL they were given.
- **`laws/`, `elaws/` and `amended/` stay open**: figure fragments shared by
  free and paid editions, and `laws/` paths are baked into stored e-Laws HTML
  that this product renders verbatim.
- **Three lists must agree** — `SIGNED_PREFIXES` here, `SIGNED_PREFIXES` in
  the Worker's `asset-proxy.js`, and the secret on both sides
  (`ASSET_SIGNING_KEY`, re-resolved in `production.py` through the
  `app_runtime_secrets` bundle). A mismatched secret 403s every scan; the
  Worker also refuses outright when its binding is missing, so a half-applied
  change fails closed rather than open.

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
