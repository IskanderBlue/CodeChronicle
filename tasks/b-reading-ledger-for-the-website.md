# Know what an account has taken, on the website too

**Prefix:** `b-` moderate priority. Code, and actionable now.

The API side shipped on 18 August 2026. The website ledger and its watch,
the per-provision text fetch and the arrival record all shipped on 21 August
2026. **Nothing is committed.** Item 6 is dropped, with the reasoning kept;
item 7 is ops in the Terraform repository and is ready to apply.

### Where this stands, 21 August 2026

Every item except 7 is **built and green**: 1,435 tests, ruff clean, mypy
clean (the hook's own `scripts/run_mypy.py api core config code_chronicle`,
170 files), `makemigrations --check` reports no changes.

**It is not committed, and it cannot be committed alone.** Two workstreams
share this working tree, and the second one is not beside these files — it is
inside them:

- `core/views/regulation.py` holds 37 hunks mixing this card's work
  (`record_versions`, `provision_text`, `core.subtrees`, `arrival_context`,
  `delivered`/`recorded`) with a package-layering refactor (`edition_gate`,
  `core.attribution`, `core.code_names`).
- `core/access.py` is the same: `api_access_allowed` is this card's,
  `edition_gate` is the refactor's.
- `core/models.py` carries `ApiKey` and `ProvisionFetch` (migrations
  0054–0056) beside `Organization`, `Membership` and `Invite` (0057–0058).
- **The dependency runs the wrong way for a partial commit.**
  `core/views/regulation.py` calls `edition_gate`, which exists only in the
  refactor's uncommitted `core/access.py`. This card's files committed alone
  give a `main` that raises `ImportError` on start-up.

A hunk-level split also cannot pass the hooks. pre-commit reverts unstaged
changes to *tracked* files but leaves *untracked* files on disk, and the mypy
hook runs whole-tree (`pass_filenames: false`). So a partial `core/models.py`
meets an untracked `core/teams.py` that imports `Organization`, and fails —
against a tree state that is not what would be committed.

**So the layering refactor lands first, and this card goes on top of it**, or
everything goes in one snapshot that names both workstreams. A commit message
for this card's share is at `.tmp/grand-commit.txt` (gitignored).

⚠️ **The index already holds a partial snapshot, and it is stale.** Another
session staged eight files, `core/views/regulation.py` among them, before this
card's last edits to that file. `git status` shows it as `MM` — staged content
plus newer unstaged content. A `git commit` without a fresh `git add` would
commit the older half of that file and leave the rest behind, which is a
broken tree that no test run would have seen. Stage explicitly before
committing; do not reset the index, because the staged rows are another
session's work in progress.

## The problem

A subscriber who can read the corpus can copy the corpus. No control in this
repository changes that.

- **The corpus is small.** 8,865 provision versions carry text, of 11,365
  loaded. About 10 MB. Measured on production, 18 August 2026.
- **A heavy day of real use and the whole corpus are the same size.** So no
  daily number separates a good customer from somebody who records.

So the control is detection, not prevention. The threat is not a subscriber who
reads offline. The threat is somebody who republishes the corpus as a rival
citable source, and the ledger's job is to supply evidence in that one case.

## What is built

In the working tree. Passes **1429 tests**, ruff and mypy (177 files).
**Not committed.**

| Piece | Where |
|---|---|
| `ApiKey` — bearer credential, SHA-256, revocable | `core/models.py`, `api/auth.py` |
| Key management for a subscriber | `core/views/api_keys.py`, `templates/partials/_api_keys.html` |
| Search answers with the **map**: identity, dates, score, url — no text | `api/schemas.py` |
| `GET /api/provision` answers with the **text**, one provision to a request | `api/views.py`, `api/provisions.py` |
| `ProvisionFetch` — one row per (account, provision, version), with a count and a `source` | `core/models.py` |
| The website's write path, five delivery points | `core/reading_ledger.py` |
| The coverage readout, per surface | `core/insights.py`, `templates/insights.html` |
| The ledger watch — is it still recording, and recording *everything*? | `core.insights.ledger_health` |
| The subtree walk, its limit, and the contents block all three surfaces show | `core/subtrees.py` |
| `SearchHistory.source` (`web` / `api`) | `core/models.py` |
| Terms name the API, forbid a shared key, reserve the revoke | `templates/terms_of_service.html` |
| One text, one request, for a signed-in reader | `core.views.regulation.provision_text` |
| The shared section builder both paths render through | `core.views.regulation._section_row` |
| Arrival | `core.events.arrival_context` |
| The cold-arrival column on the coverage table | `core.insights._cold_arrivals_in_window` |
| Tests for all of it | `test_reading_ledger.py` (25), `test_deferred_provision_text.py` (17), `test_reading_shape.py` (9), `test_provision_contents.py` (27) |

Migrations `0054_apikey`, `0055_searchhistory_source_and_more`,
`0056_provisionfetch`. All additive.
(`0057` and `0058` are another branch's team work, not this card's.)

**`0056` is hand-edited and must not be edited again.** `ProvisionFetch.source`,
its index and its check constraint were folded into it rather than added by a
`0057`, because `source` carries no model default and a follow-up migration
would have needed a one-off fill value for rows that exist nowhere. That was
safe only while `0056` was unreleased.

## What to build

### 1. Strengthen the Terms — DONE, 21 August 2026

The rewritten Terms are in force in the working tree. `terms_of_service.html`
carries the audit right (*Records and Review*), the termination right, and the
compilation claim named in *Ownership and Your Licence* as the amendment
reconstruction rather than the provision text. `TERMS_VERSION` and
`TERMS_REACCEPT_FROM` are both `2026-08-21`, so the first deploy after this
walls every existing account with the re-acceptance prompt.

**No lawyer has read it, and that is a decision, not an oversight**: the review
waits on revenue. The header comment in the template records this.

### 2. Record what the page rendered — DONE, 21 August 2026

`core/reading_ledger.py` holds the website's write path. `record_versions`
takes the versions a page rendered; `record_reads` takes ledger keys. Five
delivery points call it, all **after** `edition_allowed`, so a refusal records
nothing:

| Surface | Note |
|---|---|
| `provision_permalink` | From the view's own `by_provision`, never from `matched` |
| the same view's `for_print` branch | Whole subtree, one pass, no `CONTENTS_THRESHOLD` |
| `compare_versions`, page and print | Both sides |
| `viewer_section_content` | Renders every descendant as a flat visible list |
| `search_results` | Up to `SEARCH_RESULT_CAP` bodies, unpicked by `api.schemas.flatten` |

What holds it together:

- **`keys_for` is the only place the key is spelled.** `edition.code_name`
  (`"OBC_2006"`, the permalink's own form) and the bare division letter. Any
  other spelling misses `unique_provision_fetch_per_user`, so the account's
  ledger splits in two and its coverage halves — a corruption that reads as a
  well-behaved reader.
- **Three queries whatever the page size.** One SELECT built as an OR of
  per-key `Q` objects, one `bulk_create(ignore_conflicts=True)`, one `UPDATE`
  with `F("fetch_count") + 1`. The `Q` form asks for exactly the rows wanted;
  an `__in` filter per column matches a cross product and needs a second pass
  in Python to undo it.
- **Text only.** A version with an empty body delivered nothing to copy. The
  `/insights/` denominator counts text-carrying versions to match, because
  counting headings on one side of the fraction only understates every account.
- **`ProvisionFetch.source`** names the surface that delivered the text
  **first**, and the repeat never rewrites it. The row's identity is the text
  and its date is `first_fetched_at`, so the surface belongs with the moment the
  account acquired it.
- **Never fatal**, same contract as `core.events.record_event`.

Three things the build corrected:

1. **`results_csv` needs no write.** Its columns are identity only. The card
   used to name it.
2. **"No default on the field" is not enough on its own.** Django gives a
   non-null `CharField` an implicit `""`, and `choices` is checked by
   `full_clean`, which `save` never calls. Such a row counts as neither
   surface. A `CheckConstraint` is the part that holds, and
   `test_a_row_without_a_surface_is_refused` keeps it honest. The existing
   helper in `test_api_keys.py` had been writing empty-source rows all along
   and every test passed.
3. **`viewer_section_content` writes unguarded by `HX-Request`**, unlike the
   engagement event beside it. That asymmetry is deliberate: the event measures
   a deliberate click, the ledger records what left the server, and text
   delivered to a refreshed URL left the server just the same. It looks like an
   oversight and somebody will try to "fix" it.

**The watch sees a partial failure too**, added 21 August 2026. The day-level
test answers "is the ledger recording"; it passes a page that delivers 40 texts
and records 3, because that day has writes. So each bulk surface stamps
`delivered` and `recorded` on the view event it writes anyway, and
`ledger_health` counts the requests where the second is lower.

- **The two numbers come from two functions**, which is the rule the whole
  watch rests on. `record_reads` swallows every failure, so a number it alone
  produced cannot report its own silence. `keys_for` touches no database.
- **A failure answers 0, not a part count.** The writes are not one
  transaction, so after an exception the number written is unknown. A watch
  that guesses low raises an alarm; one that guesses high hides it.
- **`delivered` counts distinct keys**, measured exactly as `recorded` is.
  Counting the versions instead would report a shortfall on every container
  page (a heading carries no text) and on every transition (two versions of
  one provision).
- **Signed-in readers only.** `record_reads` answers 0 for an anonymous
  reader by design, so counting those would report every anonymous read as a
  total ledger failure.
- The comparison casts through `->>` rather than comparing the JSON values,
  because a jsonb comparison orders 9 after 10 and this is a "fewer than"
  question.

### 3. Lazy-load the descendants for signed-in readers — DONE, 21 August 2026

**The ledger records what an account was given, so delivery has to be granular
or the record is coarse however carefully item 2 is written.** One request to a
permalink handed over up to 39 texts. That was the website doing what
`/api/search` used to do, and it took the same fix: one text, one request.

Measured on production, 21 August 2026, before the change:

| | |
|---|---|
| Requests needed to sweep the corpus | **1,292** |
| Provisions those requests deliver | 9,637 of 9,744 — **98.9%** |
| Texts one pass over all permalinks delivers | 21,278, against ~11,365 versions |
| Pages rendering more than one text | 2,173 of 9,744 (22%) — carrying **64%** of all text delivered |

1,292 requests is an afternoon, and against a ledger it looked like nothing.

What shipped. A signed-in reader's permalink renders the matched provision's
text and the **headings** of everything under it; each body arrives from
`core.views.regulation.provision_text` on `hx-trigger="revealed"`.

- **`/provision/<edition>/<division>/<id>/v<n>/text/`** — the website's
  `/api/provision`, and the permalink with `/text/` on the end exactly as the
  print route is the permalink with `/print/`. A row with **no** version in
  force is never deferred: it has no body to fetch, so it renders its one line
  on the page and costs no request. That is also why every fragment URL names
  a version that exists.
- **The fragment resolves cross-references at its own version's effective
  date**, which is what `provision_permalink` does for the version *its* URL
  names. On a permalink the descendants instead inherit the matched version's
  date, so the two differ wherever a descendant came into force earlier — 28
  of 9,822 descendant rows, measured 21 August 2026. It changes which version
  a citation links to, never the text.
- **`_section_row` is the one place a section is described**, and
  `_viewer_section_body.html` the one place a body is rendered. The fragment,
  the page and the exhibit go through both. Two copies would let a lazily
  loaded body differ from a printed one, which is the guarantee `for_print`
  exists to make — now with a second code path to hold it against, and a test
  that does (`TestTheExhibitNeverDefers`).
- **Anonymous rendering is unchanged.** That is what crawlers see, what the
  edge stores, and what `CONTENTS_THRESHOLD` was measured against. Deferring
  there would multiply the requests and record none of them.
- **The exhibit never defers.** A printed page has no later, and the print
  branch renders the whole subtree with no `CONTENTS_THRESHOLD`.
- **The fragment answers 403 to an anonymous reader**, not a login redirect:
  htmx swaps nothing on a non-2xx, so an expired session leaves the heading in
  place instead of pasting a sign-in form into the body slot.
- **The provision the URL names is never deferred.** A page that answers a
  request for one provision with a spinner is not a page.
- Known cost: find-in-page no longer reaches an unexpanded body. A `<noscript>`
  link to the provision's own permalink keeps a reader without htmx from being
  stranded.
- A secondary benefit, not the reason: it also separates **delivered** from
  **consumed**, so a reader who scrolls past two of forty stops looking like a
  script that took all forty. `revealed` rather than `load` is what buys that.

Do **not** argue this from the median permalink. The median permalink is a leaf
article: one text, nothing to defer. Nobody copying the corpus visits median
pages, so a median hides the whole problem — this card contained that mistake
once already.

`CONTENTS_THRESHOLD` did not close it. It capped the largest subtrees for
**cost**, and capping cost is not the same as making delivery countable; the
1,292 figure above is measured with that cap already in force.

**What this did not change: the search overlay defers nothing.**
`viewer_section_content` renders its bodies inline, and deliberately — it
highlights the query's terms in each, and a fragment URL carries no query, so a
deferred body there would arrive unhighlighted. It is recorded in full by
item 2.

**What it did change there, on 21 August 2026: the walk is bounded.** The
overlay walks the *parent's* subtree, so a reader sees the match in context,
and that walk had no limit at all. A search result is not always a leaf
article: the candidate query does not exclude a version with an empty body, and
BM25F scores the title as its own field, so a part or a section can be the
match. Its parent's subtree is then the 1,339-provision, 1.9 MB render
`CONTENTS_THRESHOLD` exists to prevent — inline, with every body highlighted,
on the one surface that had no cap.

- **The context narrows before the panel changes character.** The parent is
  there to give the match its siblings, but the reader searched for one
  provision and must still be shown it, so the siblings go first. Only when
  the match's *own* subtree is too big does the panel become a table of
  contents. `subtree_root` moves with the walk — the section list is built by
  descending from it, and a root left naming a provision no longer in the set
  renders an empty panel. That is a real bug, and the tests caught it.
- **It is the permalink's block, not one like it.** The overlay mounts
  `_provision_contents.html` over `core.subtrees.contents_view`, the same two
  the reading page and the exhibit mount. A reader who meets the contents of
  Part 9 beside the results and again on its own page meets one list.
  `test_the_two_surfaces_show_the_same_list` compares them row by row.
- **`core/subtrees.py` owns the whole rule**, not only the walk: the limit,
  `walk_subtree`, `descendant_count`, `related_links`, `plural` and
  `contents_view`. `contents_view` answers the block's three context keys
  together, because the count is *not* a by-product of the walk — the walk
  stops early on purpose — and a caller that builds the rows and then asks for
  the total separately is a caller that can get the two out of step.
- **`core/tests/test_module_conventions.py` forbids the alternatives.** Rule 3
  refuses a private name read across a module boundary, and rule 5 refuses a
  constant duplicated by value. A view-to-view import was impossible in this
  direction regardless — `regulation` already imports `in_force_versions` from
  `search`. So the shared code had to move *below* the view layer; it could
  not be passed sideways.
- **The block's copy names no surface.** It said "too many to show on one
  page", which is wrong in a panel beside the search results.

**How far it was reachable in practice is not measured.** The overlay is
bounded now whether or not a container has ever been returned by a real search.

### 4. Tell a run apart from a year — DONE, 21 August 2026, differently

The card asked for a session key stamped on every row. **Do not build that.**
A session key is the session cookie's value, and these rows are kept for two
years, so storing it extends the life of a credential well past the session.
Worse, it measures the wrong thing: `SESSION_COOKIE_AGE` is unset here, so
Django's default of **two weeks** applies, and a consultant who stays signed in
reads a fortnight under one id. They would score the single long run that is
supposed to be the recorder's signature.

`core.insights._sittings_in_window` derives it instead, from the gaps between
`first_fetched_at` values, with `SITTING_GAP` at 30 minutes. No column, no
migration, no credential, and the threshold can be re-tuned later against data
already collected. Only first sightings count, because a sitting answers "when
did this account acquire text" and re-reading acquires nothing.

**The general rule this came from: store the observations, derive the
interpretation.** `first_fetched_at` is an observation. "That was one sitting"
is an interpretation, and interpretations get revised.

### 5. Record how a reader arrived — DONE, 21 August 2026

Arrival measures **shape** rather than quantity, which has no ceiling problem:
no amount of ordinary reading produces 3,000 cold arrivals in id order.

- **From the `Referer` header** (`core.events.arrival_context`). Two keys on
  the view event's `context`: `arrival` is `cold` / `internal` / `external`,
  and `from` is the **route name** of the page that linked here, internal
  arrivals only. No query parameter — an internal marker in a URL ends up in
  somebody's citation.
- **The referrer URL is never stored**, and a test holds that. A route name
  says a reader came from a contents page; a URL says which one, and an
  outside referrer can carry somebody else's search terms. The ledger already
  holds the reading list, under a rule the Privacy Policy states.
- The readout is one more column on the existing coverage table on
  `/insights/`, so there is one list of accounts and not two.

**Container reads were built here and then removed.** A `CONTAINER_VIEW` event
type recorded the two surfaces that deliver no text — an edition's contents
page, and a permalink whose subtree was too large to render. Two measurements
killed it: OBC 2006 holds **37** container pages against 3,225 provisions, so
a full walk of the edition is 1.1% containers, and on the historical record
container pages are **259 of 13,172** permalink views. A consultant who opens
two large Parts in a week produces two. The distributions overlap, so the
number cannot separate a walk from a practice, and a concept that earns
nothing costs everybody who reads the code afterwards. `cold` carries the
arrival signal on its own.

### 6. Mint the scan token per account — DROPPED, 21 August 2026

Not deferred. Dropped, and the reasoning kept so nobody re-argues it.

`documents/` holds whole-page OBC 1997 scans on sequential keys, answered from
R2 by a Worker with Django out of the path. The token defeats enumeration but
is account-blind, so that log cannot say who fetched what. The change itself is
small: put an account marker in the HMAC input and in the URL, and have the
Worker read it back.

**What it would buy is already recorded.** A scan URL is only ever minted while
rendering a page the gate has already allowed, so every signed URL belongs to an
account `ProvisionFetch` can name — the page that carried the image is in the
ledger, keyed on (account, edition, division, provision id, version). Item 3
tightened this: a descendant's scans now load with its deferred body, so the
fragment mints the token and writes the ledger row in one request. All the
account marker adds is *which images of a page were actually fetched*, and
nothing acts on that number.

**What it would cost:**

1. **The second ledger may not exist to be read.** The Worker's record is
   Cloudflare's request log. Retained logs and Logpush are paid features. Having
   the Worker write to KV or D1 instead puts a write on the hot path of every
   image request.
2. **It fragments the edge cache.** `asset-proxy.js` answers with
   `public, max-age=31536000, immutable`, and Cloudflare keys the cache on the
   full URL. One marker per account means one cached copy per account of the
   largest objects we serve. Moving the scans off the origin is what fixed the
   Neon egress bill; this partly undoes it.
3. **It puts an account identifier in a URL that reaches a printed exhibit.**
   The print pages embed signed scan URLs, so a filed exhibit would name the
   subscriber who produced it.
4. **It is a cross-repository change with a hard order.** `SIGNED_PREFIXES`,
   the secret and the token's input must agree across `config/assets.py` and
   `CodeChronicleTerraform/modules/cloudflare/asset-proxy.js`. Shipping the
   Django half first 403s every scan in production.

Reopen this only if somebody needs per-image detail for a specific account, and
only after confirming there is a log to read.

### 7. Schedule the retention purge on the backup timer

The Privacy Policy says a reading record is kept for up to two years and then
deleted. `core/management/commands/purge_reading_records.py` does the deleting.
Nothing calls it, so today the sentence is a promise with no machinery.

**Reuse `cc-backup`, and add no new unit.** The scheduling style already in use
is a systemd timer in `CodeChronicleTerraform/modules/compute/startup.sh`, with
a healthchecks.io dead-man's switch watching it. `cc-backup.service` already
runs a command inside `codechroniclenet-web` daily at 07:00 UTC, so the purge
is one more line in that script.

- **Run it after the backup**, and keep its exit code out of the backup's
  healthchecks ping. A backup alarm must mean the backup failed. A purge
  failure that reddens the backup check teaches the operator to distrust the
  alarm, and an alarm nobody trusts is worse than none.
- **Give it its own check** if it needs watching. The free tier allows 20.
  Period 1 day, grace 6 hours.
- **Daily is more often than the promise needs**, and that is the point: the
  cheapest schedule is the one that already runs.
- **Pass `--apply`.** Without it the command only reports, which is correct for
  a person and useless for a timer.

**Confirmed ready on 21 August 2026.** `purge_reading_records` takes `--apply`
and `--days` (default 730, matching the Privacy Policy), and
`cc-backup.service` already runs `docker exec codechroniclenet-web python
manage.py backup_userdata` at 07:00 UTC. The change is one `ExecStart=` line
beside it in `CodeChronicleTerraform/modules/compute/startup.sh`. Not applied:
`startup.sh` rebuilds the VM's configuration, and a Terraform apply that
touches it is the operator's call, not a side effect of a code task.

## When this lands

- ~~Rename the `/insights/` section~~ — **done**. It reads "Provision text
  delivered", with `web_held`, `api_held` and `sittings` reported apart.
- ~~Three docstrings say "through the API"~~ — **done**. `ProvisionFetch`, the
  `User.provision_fetches` comment and the readout all say both surfaces now.
  `api_coverage` was renamed `reading_coverage` for the same reason. Each of
  those sentences read as a scope limit to whoever met it next — the same
  failure as the e-Laws scoping in `core/attribution.py`, where a true statement
  about the source stood in for the rule.
- ~~Read **coverage**, not new share, for website traffic~~ — **done**, and
  said on the page itself. A part page delivered texts the reader did not ask
  for one at a time, so novelty read false there. Item 3 has since made a
  signed-in reader's fetches one text at a time, so the two sides are
  converging; the page says that, and says that older rows still are not.
- **The purge un-ages novelty.** `purge_reading_records` deletes on
  `last_fetched_at`, so a consultant returning to a provision after two years
  is recorded as meeting it for the first time, and the coverage curve bends
  upward for the most ordinary reader there is. The Privacy Policy wins — but
  consider keeping a per-account aggregate that outlives the row, or the one
  curve this ledger exists to draw is wrong at exactly the two-year mark.

## The limit

None of this observes anonymous reading, and it cannot: an anonymous response
is stored at the edge for `EDGE_MAX_AGE` and never reaches Django. That is
acceptable. Anonymous means free tier, free tier means OBC 2006, and we publish
that to crawlers on purpose. The blind spot and the content that needs no
protection are the same set.

Every read of paid content already reaches Django: `corpus_last_modified`
returns `None` for a signed-in reader and `corpus_conditional` sends `private,
no-store`. The plumbing is complete. Only the record is thin.

## Also open

- **The re-acceptance wall is armed.** `TERMS_REACCEPT_FROM` is `2026-08-21`
  and `PRIVACY_REACCEPT_FROM` is `2026-08-19`, so the first deploy after this
  prompts every existing account. Intended, and worth shipping deliberately
  rather than as a side effect of an unrelated release.
- **Nothing is committed**, and this card cannot go in on its own — see
  "Where this stands" at the top for the entanglement and the order that
  resolves it. Three migrations, the API modules and endpoint, the new models,
  `core/reading_ledger.py`, `core/subtrees.py`, the insights work, the Terms
  and the Privacy Policy. The suite is green at 1,435 tests.
- ~~A partial ledger failure is invisible~~ — **done**, 21 August 2026. Each
  bulk surface stamps `delivered` and `recorded` on its view event, and
  `/insights/` counts the requests where the second is lower. What it still
  cannot see is a `record_reads` that fails *and* reports the wrong number,
  which is a much narrower bug than the one it closes.
- **`new_share` still reads false for older web rows.** Item 3 made a
  signed-in reader's fetches one text at a time, so web novelty is becoming
  a real measurement — but rows written before 21 August 2026 counted a whole
  page render as one decision, and the two are mixed in one column. Read
  `coverage` for the web side until that window has passed.
- **The search overlay still delivers in bulk**, deliberately: it highlights
  the query's terms in each body and a fragment URL carries no query. Item 2
  records it in full, so the ledger is right; only the granularity is coarse.
  The *size* of that bulk is now capped — see item 3.

---

## History

Kept so nobody re-derives a rejected idea or repeats a wrong one.

### Why the map and the text are separate calls

A search used to answer with up to 100 full texts. The only countable thing was
the request, and a request could be one text or a hundred. One provision to a
request makes the text countable, and countable text makes *distinct* text
countable. Item 3 above applies the same reasoning to the website.

### What other publishers rely on, in order

1. **The contract.** A named licensee, a seat count, no redistribution, an
   audit right, a termination right. Westlaw, Lexis, CSA and ANSI all depend on
   this. `Ryanair v PR Aviation` (CJEU, 2015): a contract can restrict use of a
   database carrying no copyright and no database right. This is why item 1 is
   first.
2. **Authentication**, so every read carries a name.
3. **The shape of the interface** — one record per call, no bulk export. Firms
   that sell bulk sell it separately, at a bulk price.
4. **Metering**, treated as a cost control and a coarse tripwire. Nobody claims
   a quota prevents copying.
5. **Behavioural detection** — novelty, coverage curve, order, timing, breadth,
   session shape.
6. **Edge bot defences.** These stop an unauthenticated scraper and do nothing
   against a subscriber who pays.
7. **Canaries and watermarks**, for attribution after a leak. Rejected below.

### The legal floor

- Canada has **no database right**. The EU and UK do, and `British Horseracing
  Board v William Hill` (2004) narrowed even that.
- Canadian protection is copyright in the **compilation**. `CCH Canadian v Law
  Society of Upper Canada` (SCC, 2004) sets the standard at skill and judgment.
- **The provision text is not ours.** The King's Printer permits any person to
  reproduce Government of Ontario legislation, and confirmed this in writing
  for OBC 1997, 2006 and 2012 by name (file C/N 0099/26/C, 2026). The
  permission is not tied to e-Laws — all three editions predate that
  consolidation.
- The US CFAA has shrunk (`Van Buren`, 2021; the `hiQ v LinkedIn` line).
  LinkedIn won on **breach of contract**, not on the computer-misuse statute.

### Rejected: watermark the citation

Each citation choice with two acceptable forms carries one bit — `O Reg` or
`O. Reg.`, `retrieved` or `accessed`, a trailing period or none. Twenty choices
separates a million accounts, and half the bits must go to error correction.

Rejected for four reasons:

1. It marks the wrong thing. A copier takes provision text, not citations.
2. A citation gets edited. One copy-editing pass removes the mark.
3. The citation is the one thing we want copied — it carries our URL into
   somebody else's document, so it should be identical everywhere.
4. A varying citation format is a wrong citation format. The McGill Guide has
   one correct form.

### Corrections to earlier versions of this card

- **"A copy is a snapshot that decays."** Wrong. An edition's reconstruction is
  finished work; OBC 2006 reads the same in 2030. What a copy never gets is
  **citability** — a source nameable in a report, with a resolving permalink
  and a publisher behind the amendment chain. It is why people pay for Westlaw
  when the same cases sit on CanLII.
- **"Lazy loading breaks the print guarantee."** Wrong. That guarantee is about
  two *assemblies* of the subtree. Lazy loading changes *delivery*. One
  assembly function serves both paths.
- **"Find-in-page already fails on that text."** Also wrong, in the other
  direction: `_viewer_section_content.html` renders descendants as a flat
  visible list, so Ctrl-F reaches them today. Item 3 gives that up knowingly.
- **"The median permalink renders one text, so item 3 buys little."** Wrong,
  and wrong in an instructive way. The median permalink is a leaf article, and
  a distribution dominated by leaves says nothing about the pages a copier
  uses. The figures now in item 3 are the ones that answer the question.
- **"Item 3 is about telling a reader from a script."** That is its secondary
  benefit. Its purpose is to make delivery granular, so that what an account
  was given is recorded per text rather than inferred from a page render.
- **"The search results page needs the map/text split."** Overstated. It
  renders text and item 2 must record it — that is one more view in item 2's
  list, not a rebuild. A reader scanning results with the text in front of
  them is the product.
- **"`ProvisionFetch.source` needs a default for existing rows."** There were
  none, anywhere: production had no such table, and test databases are built
  fresh. That is what made folding the field into `0056` right.
- **"Leaving the model default off makes every write site name the surface."**
  Wrong on its own. Django writes an implicit `""` for a non-null `CharField`,
  and `choices` is only checked by `full_clean`. The check constraint is what
  makes the rule true.
- **"Stamp a session key on every read row."** Wrong twice: it stores a
  credential in a two-year ledger, and it measures `SESSION_COOKIE_AGE` rather
  than a sitting. See item 4.
- **"Lazy loading saves the page's database work."** It does not, and it was
  never the goal. The view still loads every descendant version, because the
  headings carry titles that live on the version row; only the *rendering* of
  the body is withheld. Deferring the query instead would need `defer("html")`,
  and a deferred field that anything touches re-fetches silently — an N+1 no
  test would catch. Anonymous rendering is where the cost lives, and item 3
  leaves it alone on purpose.
- **"A provision can have two versions in force on one date."** Wrong.
  Measured on production, 21 August 2026: **zero** pairs of versions of one
  provision have overlapping in-force windows. The transition overlap is
  *across* editions — two corresponding provisions, one per edition — which
  never groups under a single provision, so `active_versions` on a permalink
  page never holds more than one. `provenance/_transition_view.html` is
  defensive there.
- **Two further justifications for a date-addressed fragment URL, both
  wrong.** First that a version number would split a derivation from its use
  (nothing drifts: the view holds each descendant's version at render time).
  Then that only a date can name a row with nothing in force (true, but such a
  row has no body to fetch and should never have been deferred at all). The
  URL now carries the version number, matching every other provision route.
  The lesson is the pattern, not either error: a working design was defended
  with the strongest-sounding reason available rather than the true one, twice.
- **"The permalink recorded a provision view, which was wrong."** It was not
  wrong. A container is a provision and a reader who opened it did open it.
- **"Many containers against few provisions is the shape of a walk."** The
  ratio is the other way round, and then the signal turns out to be too weak
  to use at all — see item 5. `CONTAINER_VIEW` was removed.
- **"`CONTENTS_THRESHOLD` capped the largest subtrees."** True of the
  permalink and false of the product. The search overlay walked its match's
  parent with no limit at all, and the reason it had never hurt is not that it
  is safe — it is that a search result is *usually* a leaf. Nothing in the
  candidate query makes that a rule. A cost control that one of two surfaces
  observes is a cost control with a hole in it, and the hole was on the surface
  that renders every body inline and highlighted.
- **"A partial ledger failure is not obviously worth closing."** It cost two
  integers in a JSON field already being written, and one comparison. The
  reason it looked expensive was the assumption that both numbers had to come
  from the ledger; the view already knows what it rendered.
- **"The overlay's contents block is a different, simpler thing."** Written
  by me, about my own first pass, and true only of what I had built. Two
  answers to "what do we show when a subtree is too big" is two things to keep
  in step, and the argument that a panel and a page deserve different copy was
  really an argument that moving `contents_rows` out of the view layer looked
  expensive. It was not: `related_links`, `plural` and the row builder moved
  with it, `regulation.py` came out two lines shorter, and the shared partial
  needed one word changed.
- **"A per-account scan token is a small change."** Small in code, not in
  consequence: it fragments the edge cache per account, puts an account
  identifier into URLs that reach printed exhibits, and only pays off if
  Cloudflare's request logs are readable on this plan. Item 6 is dropped;
  the ledger names the account from the page, not from the image.
