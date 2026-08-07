# A repeat of the same search must not cost the allowance

**Status: DONE 2026-08-07**, in the same working tree as the address-bar work
that exposed it. `RateLimitMiddleware._other_questions_today` replaces the row
count. Tests in `core/tests/test_middleware.py`.

What the built version does, where it differs from the plan below:

- **The count leaves out the question being asked now.** Counting distinct
  prior searches was not enough: a reader with one prior search still counts
  1, and `1 < 1` is false, so the reload still met the teaser. The number
  means "how many *other* questions have you asked today".
- **The key is the query text with the date it ran at**, read from
  `SearchHistory.parsed_params["date"]` — no new column, as hoped.
- **A post with no date matches on the words alone.** The date such a search
  runs at comes from the parser, and the middleware runs before the search.
  This errs towards the reader, and only where they gave no date to tell two
  questions apart.
- **`_spend` in the tests had to change.** It wrote identical rows, so under
  distinct counting every test meaning "N searches used" would have been
  testing one.

**Prefix:** `a-` — high priority. This was a live defect, and the address-bar
work made it reachable by accident.

## The gap

`RateLimitMiddleware.check_rate_limit` counts rows:

```python
search_count = SearchHistory.objects.filter(
    ip_address=ip, user__isnull=True, timestamp__gte=today_start
).count()
```

Every row, not every distinct query. `RATE_LIMIT_ANONYMOUS` is 1.

So an anonymous reader searches once and reads the results. Then they press
Ctrl-R, or press Back, or follow their own link again. The page re-runs the
search, writes a second row, and the middleware puts them in the teaser band.
The address survived; the answer did not.

The reader did not ask a second question. They asked the same question twice,
and we charged them for it. The allowance is supposed to measure how much we
answer, and a second copy of one answer is not a second answer.

## Why it appeared now

`/search/?q=…&d=…` runs its own search, and the search view now writes that
address after every search. So a reload reproduces the search — which is the
point — and each reproduction spends a search. Before this, a reload lost the
query, so nobody ever re-ran one by accident.

## What to build

Count **distinct** searches, not rows. The unit is the question, not the
request.

The shape of the key needs a decision. The query text alone is not enough,
because the same words at two dates are two questions. `query` + the AS-OF
date is the likely key. `SearchHistory` already stores both, so this may be a
`.distinct()` over those two columns rather than a new column.

Watch two things:

- **The teaser band's ceiling exists to stop an open tap.** The teaser costs
  an LLM parse per request. A repeat is served from `QueryCache`, so it does
  not, which is why a repeat can be free — but check that this holds before
  relying on it.
- **`EngagementEvent.RATE_LIMIT_BLOCK` counts intent.** A reader who repeats
  a search did not form a new intent, so a repeat that is now allowed must not
  record a block either.

## Done when

- An anonymous reader can reload their search and still read it.
- A test asserts that the same query at the same date, run twice, leaves the
  reader in the same band.
- A test asserts that a *different* query still spends the allowance.

## Related

- `core/middleware.py` — the count.
- `core/views/search.py` — `_push_search_url`, which made repeats easy.
- `CLAUDE.md` — "The address bar holds the search that ran".
