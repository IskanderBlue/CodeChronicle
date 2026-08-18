# Precompute the size-relevance windows onto CorpusCurrency

## The idea

`core.views.search._size_relevance` queries `CodeEdition` on every render of
the search page. It reads each edition's window, clips the applicability rules
to it (`config.part_applicability.size_relevance_intervals`), and hands the
result to the BUILDING control as JSON. The control uses it to decide whether
to ask the reader for a storey count on the date they are searching.

The windows change only when `load_edition` runs. So the query repeats work
that a data load could do once.

`CorpusCurrency` is the singleton that already holds a value computed once per
data load — the masthead's "Consolidation current to" stamp. A column there
would hold this payload, and `core.context_processors` already reads that row
on every render, so the read would cost nothing.

## Why it is not done

**The saving is small.** The query is one scan of a table with a few dozen
rows. Nobody has measured a problem.

**The cost is a migration**, plus a change to the refresh path, plus a new
coupling: the rules live in code (`config/part_applicability.py`) and
`CorpusCurrency` is refreshed by a data load. A code-only change to `RULES`
would leave a stale payload.

That last risk is smaller than it looks. `scripts/entrypoint.sh` runs
`refresh_corpus_currency` on each deploy, so a deploy that changes a rule does
move the stamp. But the coupling is still real, and it is the kind that is
invisible until it fails.

## What would have to become true

Any one of these makes it worth doing:

- The search page appears in a slow-query report, or in Neon's row-read
  totals. Almost all traffic is crawlers, `/search/` is in the sitemap, and
  the page carries no edge cache and no 304 — so the cost scales with the
  crawl, not with the readers.
- A second control needs the same derived data, which would make the
  computation shared rather than single-use.
- `RULES` grows enough that the clipping is no longer trivial. Today it is
  four rows.

## Where the code is

- `core/views/search.py` — `_size_relevance`, and `_building_control_context`
  which calls it.
- `config/part_applicability.py` — `size_relevance_intervals`, which returns
  `SizeWindow` objects and does no serialisation.
- `core/models.py` — `CorpusCurrency`, and the pattern to copy.
- `tasks/complete/boost-parts-by-building-type.md` — the feature this serves.
