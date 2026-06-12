# Find a new transition-period example query

## Problem

The empty-state example chips (`EXAMPLE_QUERIES`, `core/views/search.py`)
are meant to showcase the product's range, and one of them used to land on
a provision with a visible transition period (the staggered-commencement
band — old and new rules overlapping, from/until-commencement ⓘ). After
the cancelled-before-in-force amendments fix landed in CCM and the
editions were reingested (2026-06-12), that example no longer shows a
transition, so the feature is no longer discoverable from the empty state.

## Task

Hunt a replacement provision/date whose **rank-1** search result renders
the transition band, and swap it into `EXAMPLE_QUERIES`.

- Candidate hunting from the data, not by guessing queries: look for
  provision versions whose effective window starts at a clause-level
  `effective_date` that differs from its regulation's filing/in-force
  date, or regs with a real commencement schedule (the staggered-
  commencement surfaces) — then pick a date inside the overlap window.
- The chip must satisfy the existing bar (comment above `EXAMPLE_QUERIES`):
  carries a `date` (sets the AS-OF picker), Ontario/in-coverage, and
  **verified rank-1 through the full `run_search` pipeline including the
  LLM parse** — not just a direct provision lookup.
- Free-tier note: chips are shown to anonymous users; once
  `FREE_TIER_GATING_ENABLED` is on, an example outside OBC 2006 hits the
  locked-teaser path. Prefer an OBC 2006 transition so the chip works for
  everyone, or consciously accept the teaser as the upsell.
- Re-verify the other three chips still rank-1 against the reingested
  data while at it (last verified 2026-06-11, pre-reingest).

## Acceptance

- New chip's result visibly renders the transition/commencement band at
  the chip's date.
- All four chips verified rank-1 through `run_search` post-reingest; the
  verification date in the `EXAMPLE_QUERIES` comment is updated.
