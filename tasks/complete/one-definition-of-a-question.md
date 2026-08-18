# One definition of a question, for the allowance and the history page

**Done on 16 August 2026.**

## The result

`core/models.py` states the key once, as `QUESTION_FIELDS` plus two functions
beside `SearchHistory`:

| Function | Caller | Form it returns |
|---|---|---|
| `question_keys(searches)` | `core.middleware` | Distinct `(words, date)` pairs |
| `grouped_by_question(searches)` | `core.views.history` | One row per question, to aggregate |

Both go through one private `_with_question_key`, so there is now one spelling
of the key rather than two. The middleware used the `parsed_params__date`
lookup and the history page used `KeyTextTransform`; both now use the
expression, which the lookup cannot replace because only an expression can
join a `GROUP BY`. On a stored string the two return the same value, and a
missing key gives `None` either way, so no behaviour changes.

The annotation keeps the name `query_date`, which the rest of the product
already uses for this value — `core.views.search` reads `parsed_params["date"]`
into a context key of that name. It appears as a `date` object in
`core.verification` and as a string in the templates, but that is one value in
two forms, and the type hint states the form. A name that repeats the type goes
stale in silence.

They are plain functions and not a queryset manager. `as_manager()` is the
idiomatic form, but Pyright cannot see the methods through it, and this
repository keeps Pyright and mypy at zero without an ignore comment.

`TestOneDefinitionOfAQuestion` in `core/tests/test_history.py` is the guard the
card was missing: it asserts the two functions report the same questions for
one set of rows, and that the building does not enter the key.

## Goal

State once what makes two searches the same question. Two modules answer that
today, in two hand-written spellings, and each asserts in a comment that it
agrees with the other.

## The two places

**`core/middleware.py`**, `RateLimitMiddleware._other_questions_today`, decides
what costs an anonymous reader a search:

```python
.values_list("query", "parsed_params__date").distinct()
```

**`core/views/history.py`**, `history`, decides what makes one card:

```python
.annotate(query_date=KeyTextTransform("date", "parsed_params"))
.values("query", "query_date")
```

Both mean "the query text and the date it ran at". Both say so in their
docstrings. Neither reads the other.

## Why this matters

The rule is load-bearing in two different ways, and the two must not drift:

- The allowance charges for a question. A reader who reloads, presses Back, or
  follows their own link must not pay twice.
- The history page shows one card per question. A card that merged two
  questions would hide a search the reader ran; a card that split one would
  make the list repeat itself.

If the middleware's key widens and the history page's does not, a reader is
charged for a search they cannot find in their own history.

## The address is deliberately wider, and must stay so

`core.views.search._push_search_url` writes `q`, `d`, `occupancy`, `storeys`,
`area` and `area_unit`. That is a **third** key, and it is correct that it
differs: the address must reproduce the page, and the building changes the
order of the results.

So this card unifies **two** of the three, not all three. Do not fold the
address into the shared definition. Record in the comment why it is wider.

## What to build

One definition on `SearchHistory` — a constant such as `QUESTION_FIELDS`, or a
queryset method such as `SearchHistory.objects.questions()` — that both callers
use.

Watch two details:

- The two spellings are not interchangeable. `parsed_params__date` is a
  lookup; `KeyTextTransform` is an expression that can join a `GROUP BY`. A
  shared helper must give each caller the form it needs.
- `core/views/history.py` calls `.order_by("-latest_id")` to clear
  `Meta.ordering`. Without that, `-timestamp` joins the `GROUP BY` and splits
  every question into one card per run.

## Done when

- [x] One place states the fields, and both callers read it.
- [x] The comment beside it says why the address key is wider. It is the
  docstring of `question_keys`.
- [x] `core/tests/test_middleware.py` and `core/tests/test_history.py` both
  pass unchanged. Neither behaviour changes; only the definition moves.

## Related

- `core/middleware.py`, `core/views/history.py`, `core/views/search.py`.
- `tasks/complete/boost-parts-by-building-type.md` — the work that widened the
  address and grouped the history page on `(query, date)`.
