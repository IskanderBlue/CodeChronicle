# Find a new transition-period example query

**Resolved 2026-06-12 — no replacement query was needed.** The chip had not
stopped matching; the transition pair had started rendering *backwards*
(OBC 2012 shown as the "old" side, 2006 as "new") with no transition text.
Root cause was a pairing bug, fixed in `api/search/orchestration.py`.

## What actually happened

`_group_transitions` grouped results by `(id, division)` **without the
edition**, so the cross-edition same-id pair (OBC 2006 C 1.10.2.4. ↔
OBC 2012 C 1.10.2.4.) was captured by the intra-edition overlap branch,
which picks the "new" side by **version number**. Version numbers only
order within an edition: at 2014-07-01 both in-force versions are v0, so
old/new fell to arbitrary input order. Before the cancelled-before-in-force
amendments fix, a spurious amendment inflated one side's version number and
happened to break the tie the right way; the CCM fix renumbered, and the
card flipped.

## Fix

- `_group_transitions` now keys on `(id, division, code_edition)`, so the
  overlap branch only ever pairs one provision's own overlapping versions.
  Cross-edition same-id pairs fall through to the `ProvisionMapping`
  branch, where the mapping row (2006→2012 `continued`, pk 33639) is the
  authority on which side is old — deterministic, and it also carries
  `mapping_type`/`same_edition` into the transition context.
- The overlap `pair_key` includes the edition too (two editions each with
  an intra-edition overlap on the same id would otherwise collide).
- `api/tests/test_integration.py::TestTransitionContextInOverlapWindow`
  updated: both fixture versions are now v0 (mirroring real cross-edition
  data, regression for the tie) and the pair is fixed by a
  `ProvisionMapping` row instead of handpicked version numbers.

## Original problem statement (for the record)

The empty-state example chips (`EXAMPLE_QUERIES`, `core/views/search.py`)
are meant to showcase the product's range, and one of them used to land on
a provision with a visible transition period. After the
cancelled-before-in-force amendments fix landed in CCM and the editions
were reingested (2026-06-12), that example appeared to no longer show a
transition.

## Acceptance — met

- The maintenance-inspection chip's rank-1 result is the
  `transition_compare` card at 2014-07-01, versions ordered old (OBC 2006)
  → new (OBC 2012), both sides carrying the from/until-commencement band
  fields.
- All four chips re-verified rank-1 through the full `run_search` pipeline
  (LLM parse included) against the reingested data 2026-06-12; the
  verification date in the `EXAMPLE_QUERIES` comment is updated.
