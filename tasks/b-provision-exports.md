# Exports: build all of them, then watch which get used

**Prefix:** `b-` — medium priority, actionable now.

## Goal

Give a reader four ways to take something out of CodeChronicle and put it in
their own work. Build all four. Instrument each one. Remove or rework whatever
nobody uses after 60 days.

Building all four is deliberate. We do not know which one a code consultant
reaches for, and asking produces an opinion rather than a measurement. Four
small exports cost less than one wrong guess.

## The four

### 1. Citation string

The cheapest, and the one that puts our URL in other people's documents.

> Ontario Building Code 2006, 3.2.5.7. Fire Department Access Routes, as it
> read 31 December 2006 to 1 January 2009. CodeChronicle, retrieved
> 1 August 2026. https://www.codechronicle.ca/provision/OBC_2006/B/3.2.5.7./v2/

A copy button beside the provision heading. The URL must be the **canonical**
one from `core/seo.py`, so a citation stays valid.

### 2. PDF of one provision at one date

The one a litigation buyer needs. It is filed as an exhibit, so it must carry
its own proof:

- The provision text as it read, with the tables and page images.
- The in-force window, stated in full.
- The amending regulation that produced this version.
- A retrieval stamp: date, and the canonical URL.
- The same "not legal advice" line the site carries.

Render from the same partials the page uses, so a PDF cannot show something
the product does not. Use a headless-browser print rather than a second
layout engine.

### 3. CSV of a search result set

For somebody auditing a building against a date. One row per result:
provision id, division, title, edition, effective date, ineffective date,
score, canonical URL. Nothing else — a CSV with body text in it is a
spreadsheet nobody can read.

The export must reflect the **same** filtering the reader saw: the relevance
floor, the tier gate, and the cap. An export that quietly contains more than
the screen showed is worse than no export.

### 4. Comparison export

The diff from `tasks/a-general-comparison-ui.md`, as PDF, with both in-force
windows, both amending regulations, and the statement of how the two
provisions were paired. This is likely the most valuable of the four; it is
listed last only because it depends on the comparison work.

## Rules for all four

- **Gate through `core/access.py`.** A free reader exports what a free reader
  can read. No second definition of a tier.
- **Every export records an `EngagementEvent`** with the export kind in
  `context`. That is the whole point of building all four — see below.
- **Never export a locked edition's text**, not even into a PDF the reader
  requested. The gate is the gate.
- **State the retrieval date on everything.** A historical text with no
  retrieval stamp becomes an undated claim the moment it leaves the site.

## How we decide what stays

Add a new `EngagementEvent.EventType.EXPORT` with `context.kind` in
`{citation, provision_pdf, results_csv, comparison_pdf}`. Surface the four
counts on `/insights/` as one small table.

After 60 days:

- An export nobody used is removed, not defended.
- An export used often gets the next round of work.
- An export used once per reader and never again was probably confusing.
  Ask that reader before removing it.

## Done when

- All four exports ship, gated, instrumented, and tested.
- `/insights/` shows the four counts.
- A calendar note exists to review the counts 60 days after release.

## Related

- `core/seo.py` — the canonical URL every export must use.
- `tasks/a-general-comparison-ui.md`.
