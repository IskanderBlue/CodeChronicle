# Boost the part the reader is actually in

## Goal

Use the kind of building in the query to rank one part of the code above
another. A reader who asks about a house usually wants Part 9. A reader who
asks about an office tower wants Part 3. Today the search treats every part
alike.

## Why this card exists

`tasks/complete/keywords-from-the-query-first.md` deleted the `building_type`
field from the LLM parser on 14 August 2026. That field was inert — no code
read it — and the model mirrored its value into the scored keyword list, where
it did harm.

The idea behind the field was right. The delivery was wrong. A building type
is a property of the reader's project. It is not a word the provision text
contains, so it must never be a scored term. It belongs on the *ranking*, as
a statement about which part of the code applies.

The guard-height article measures what is left to win. Asking
`guard height for a stair in a house` at 1 June 2008 now answers
`9.8.8.3. Height of Guards` first, but `3.4.6.5. Guards` — Part 3, exit stairs
in a large building — is **second**, above `9.8.8.1. Required Guards`, which is
the Part 9 provision that says when the reader needs a guard at all. Six of the
top 20 are Part 3.

The Part 3 title wins on shortness: `Guards` is one word, and the BM25F title
field rewards a match that fills the field. Nothing in the score knows which
part applies to the reader's building.

## The code already answers this, and we hold the text

Each edition states which part applies to which building. The text is in the
corpus. We do not invent the rule; we read it.

**OBC 2006 and 2012 — Division A, Subsection `1.1.2.`:**

| Article | Governs | Test |
|---|---|---|
| `1.1.2.1.` | Parts 1, 7, 12 | None. "apply to all buildings" |
| `1.1.2.2.` | Parts 3, 4, 5, 6 | Occupancy, and size (over 600 m² **or** over three storeys) |
| `1.1.2.3.` | Part 8 | The building has a sewage system |
| `1.1.2.4.` | Part 9 | Occupancy, and size (three storeys or fewer **and** 600 m² or less) |
| `1.1.2.5.` | Part 10 | A change of use |
| `1.1.2.6.` | Part 11 | The building is five years old or more |

**OBC 1997 — Section `2.1.`**, which is the same six statements in a different
shape. There is no Division A in 1997, and `division` is the empty string.

| Article | Governs |
|---|---|
| `2.1.1.1.` | Parts 1, 2, 7, 12 — all buildings |
| `2.1.1.2.` | Parts 3, 4, 5, 6 |
| `2.1.1.3.` | Part 9 |
| `2.1.1.6.` | Part 11 |
| `2.1.1.12.` | Part 10 |
| `2.1.1.14.` | Part 8 |

The occupancy vocabulary is Table `3.1.2.1.`, "Classification of Buildings":
Group A assembly (4 divisions), B detention / care and treatment / care,
C residential, D business and personal services, E mercantile, F1 high hazard
industrial, F2 medium, F3 low.

## Four findings that decide the design

**1. The code splits on building type in exactly one place.** Only two of the
six articles read the building: `1.1.2.2.` and `1.1.2.4.`. The rest apply to
every building, or apply to an activity, or apply to a system. So the map is
not eleven parts with eleven rules. It is one test with two outcomes: Part 9,
or Parts 3/4/5/6.

**2. A part number does not mean one thing.** It changes across editions:

| Part | 1997 | 2006 and 2012 |
|---|---|---|
| 2 | General Requirement | Reserved |
| 5 | Wind, Water and Vapour Protection | Environmental Separation |
| 8 | Reserved | Sewage Systems |

It also changes across divisions of one edition. In OBC 2012, Division A
Part 3 is Functional Statements, Division B Part 3 is Fire Protection, and
Division C Part 3 is Qualifications. **The key is `(edition, division, part)`.**
A bare part number is not a key.

**3. The rule is time-varying, and the version windows prove it.** Article
`1.1.2.4.` v0 ran to 2017-07-01. On that date v1 removed retirement homes from
Part 9, and `1.1.2.2.` v2 added them to Parts 3, 5 and 6. So the same building
gets a different part before and after that day. The table must therefore key
on the applicability **version**, not on the edition.

**4. The text is a test, not a label.** `1.1.2.4.` does not say "houses". It
says three or fewer storeys, **and** 600 m² or less, **and** a major occupancy
in Group C, D, E, F2 or F3. A four-storey townhouse of 140 m² fails the first
condition, so Part 9 does not apply to it, and `1.1.2.2.`(1)(b) sends it to
Parts 3, 5 and 6. A map from the word "house" to Part 9 answers that reader
wrongly, and answers silently.

## The design

### A. An applicability table, written by a person, keyed by version

One row per applicability provision version:

```
edition, division, part        the part the row governs
occupancy_groups               ["C", "D", "E", "F2", "F3"]
max_storeys, max_area_m2       3, 600   (null when the article states none)
source_provision, source_version
effective_date, ineffective_date
```

Two rules:

- **A person writes the table, or CCM ships it. A regular expression does
  not.** The text carries exceptions ("Subject to Articles 1.1.2.6. and
  1.3.1.2."), and a wrong extraction moves a real answer down the page. There
  are six articles in each of three editions. The table is small enough to
  write and to review.
- **Each row cites its own provision version and carries that version's
  window.** This makes the boost explainable, and it makes the boost correct
  as of the search date. See finding 3.

### B. A profile with one derived field and one supplied field

The parser gains **one** field, and it is not a free string:

```json
"occupancy": "residential"
```

Classifying the reader's words into a Group is a language task, and the LLM
is good at it. A storey count is a fact about a building. Nothing in the word
"townhouse" contains it, so the model must never supply it.

Read what the occupancy alone decides:

- **Group A, B or F1** — Parts 3, 4, 5, 6 apply, and no size is necessary.
  `1.1.2.2.`(1)(a) states no size test for these groups. A query about a
  school, a hospital or an arena is decided by the word.
- **Group C, D, E, F2, F3** — undecided. The code says the size decides, and
  we do not have the size. Do not boost.

For the second group, one control asks the reader for the facts:

- **`storeys`** is decisive on its own when it exceeds three. This is the case
  the naive guess gets wrong, and it is the easiest fact a reader has.
- **`area`** is asked only when `storeys` is three or fewer. State the
  threshold in both units: 600 m², about 6,500 ft².

The control shows the derived occupancy and lets the reader change it. Both
fields start absent. An absent field means "unknown", and unknown never
boosts.

### C. A multiplier at rank time, never a filter

Apply the boost in `api/search/orchestration.py`, after `score_versions`
returns. Do not put it inside the BM25F loop. The scorer answers "how well do
these words match". The boost answers "does this part apply to this building".
Two questions belong in two places, or `BM25F_TITLE_WEIGHT` becomes untunable.

```
applies       score * (1 + PART_BOOST)      start at 0.25
excluded      score * (1 - PART_DEMOTE)     start at 0.15
unknown       score * 1.0
```

"Excluded" means the code's own test excludes the building. Everything else is
"unknown", which includes Division A, Division C, and every part the
applicability articles do not gate.

## Where the profile lives

The profile is a property of **this search**, not of the reader. A reader
searches one building today and a different building tomorrow. So it does not
belong in `core/search_prefs.py` beside `match_threshold`, which is sticky.

The precedent is the AS-OF date. `core.views.search._push_search_url` states
the rule: the address must name the search that ran. Three places, all of them
the effective value — what the search used, whether the model derived it or
the reader corrected it:

1. **The address:** `?q=…&d=…&occupancy=residential&storeys=4`. Reader-facing
   words and the reader's own numbers. Not the group letter `C`, which is an
   internal token in an address.
2. **`parsed_params`**, which `SearchHistory` already stores as JSON. No
   migration.
3. **The history link**, which `templates/history.html` already builds from
   `parsed_params`.

**Append. Never edit a stored row.** `services/search_service.py` creates a
row for each search that runs, and the history page shows the latest row for
each question. So a re-ranked search updates what the history card offers,
with no new write path. Editing the row instead would corrupt the record:
`EngagementEvent.search` is a foreign key to `SearchHistory`, so every click
already recorded against that row would start describing a search that did not
run.

**A re-rank is not a second question.** `core.middleware` counts
`(query text, parsed_params.date)`, and this work does not change that tuple.
A boost re-orders; it never adds a row and never removes one. So the same
words at the same date ask one question, however often the reader adjusts the
building. A filter would add and remove, which is a second reason not to
filter.

## In scope: the history page loses a question

`core/views/history.py` groups on `query` alone
(`.values("query").annotate(latest_id=Max("id"))`). Dates do not separate
cards. So two searches of the same words at two dates give **one** card, which
shows the later date and links to it. The earlier search stays in the database
and stays counted by the rate limiter, but the reader cannot reach it.

That contradicts the definition the middleware states: a question is the words
and the date. It also blocks this card's own design, because a profile set on
one date's search would re-rank the other date's card.

**Fix:** group the history page on `(query, parsed_params.date)`. A card then
means a question, and the profile is what changes inside a card.

Accept two consequences, and state both:

- The `N×` count on a card counts runs, so a re-rank increments it. This is
  already true of the relevance-floor control, which re-posts through the same
  view and writes a row.
- The `/insights/` search totals count re-ranks. Also already true today.

## Rules

- **A building type is never a scored keyword.** That is the mistake this card
  exists to avoid repeating.
- **The model classifies words. The model never supplies a measurement.**
  Finding 4 is why.
- **Nothing becomes unreachable.** A boost changes an order. A filter removes
  an answer, and a house can be governed by a Part 3 provision through a
  cross-reference.
- **Do not tell the reader the results are unchanged.** The boost removes
  nothing, but the relevance floor runs after it on the adjusted scores, so a
  demoted result can fall under the reader's line and leave the page. Keeping
  that order is correct — the floor and the ranking must be measured the same
  way — so the copy says "it changes the ranking" and never "it never changes
  the results". A reader who has not met the close-match control cannot tell
  the two apart, and would read the promise as broken.
- **The boost is not a determination.** A row of townhouses divided by
  firewalls counts as separate buildings for some purposes (`3.1.3.1.` in
  2012, `2.1.3.1.` in 1997), and storeys have their own counting rules. Say
  what the code's test returns. Do not tell the reader what governs their
  building.
- **Measure it on real queries.** Collect more from `SearchHistory` before and
  after.

## Measurement

Query: `guard height for a stair in a house` at 1 June 2008. Keywords are the
deterministic set (`config.query_keywords`), not an LLM parse, so the
measurement repeats exactly: `guard, guards, height, heights, house, houses,
stair, stairs`. 405 accessible matches in OBC 2006, floor at 0.0.

**Before.** `3.4.6.5. Guards` (Part 3, exit stairs in a large building) ranks
**1st**, above every Part 9 guard provision. `9.8.8.3. Height of Guards` is
2nd and `9.8.8.1. Required Guards` is 5th. **7 of the top 20 are Part 3.**

**After**, stating a two-storey house of 140 m², at the chosen 0.35/0.20:

| Provision | Before | After |
|---|---|---|
| `9.8.8.3. Height of Guards` (Part 9) | 2 | **1** |
| `9.8.8.1. Required Guards` (Part 9) | 5 | **4** |
| `3.4.6.5. Guards` (Part 3) | 1 | **6** |
| Part 3 in the top 20 | 7 | **1** |

**The four-storey townhouse**, same words and same date, states 4 storeys:
`3.4.6.5. Guards` ranks **1st** and `9.8.8.3.` falls to 6th, marked
`excluded`. 13 of the top 20 are Part 3. That is the code's answer, and it is
the opposite of what "house" alone would have produced.

Both provisions stay on the page in every case. Nothing was filtered.

The constants were chosen from this measurement rather than picked round —
see the sweep recorded in `config/part_applicability.py`. Collect more queries
from `SearchHistory` before tuning further; one query is not a corpus.

## Done when

- [x] A query about a house ranks Part 9 provisions above their Part 3
  counterparts, for the same words and the same date.
- [x] A four-storey Group C building ranks Part 3 above Part 9, which is what
  `1.1.2.4.` states.
- [x] No provision becomes unreachable.
- [x] The history page shows one card for each `(query, date)`.
- [x] The measurement above is recorded, before and after.

## What is not done

- **Only one query is measured.** The card's own rule says to collect more
  from `SearchHistory`. Do that before tuning `PART_BOOST` again.
- **A new search drops the measurements.** The occupancy is read from the new
  query text, but the storeys and the area are not, because they are facts
  about a building and no question contains them. A reader who asks three
  questions about one building states it three times. Decide from use whether
  that is worth fixing; making it sticky would turn a property of the search
  into a property of the reader, which is what this design refused.
- **OBC 2024 has no rule.** `rule_for` returns `None`, and the whole edition
  is `unknown`, which boosts nothing. Add a row when that edition loads.

## Related

- `tasks/complete/keywords-from-the-query-first.md` — removed `building_type`.
  It has landed, so this card is unblocked.
- `api/search/engine.py` — BM25F, and `BM25F_TITLE_WEIGHT`, which is what
  currently lets a short Part 3 title win.
- `api/search/orchestration.py` — where the multiplier goes.
- `api/llm_parser.py` — `PARSE_QUERY_TOOL`, which gains the occupancy field.
- `core/views/search.py` — `_push_search_url`, and the address rule.
- `core/views/history.py`, `templates/history.html` — the grouping fix.
- `core/middleware.py` — the definition of a question.
