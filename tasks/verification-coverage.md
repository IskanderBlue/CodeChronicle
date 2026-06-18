# Verification coverage — per-(provision, date) confidence statuses

When a user reads a provision "as it read on date D," how confident are we that
our reconstruction of the in-force text is **actually correct** for that date —
i.e. that it has been cross-checked against an independent, date-matched
authoritative consolidation? This feature surfaces that confidence, and
honestly flags the periods where we **cannot** confirm it.

**Design status:** the data model, the rank derivation, **and the presentation**
are now **settled** (this doc) — the presentation as the *attestation rail*, see
`## Presentation`. **Built** (P1 + P2, 2026-06-18; see `## Status`). The 5-rank
vocabulary and the epistemics below are unchanged from the original CCM framing,
except that presentation treats a consolidation as an **interval**, not a point
(see `## Presentation` → "The one rule").
What changed on CC adoption: *where the calendar comes from*. We derive it from
the existing `Consolidation` table — **not** from a new model, and **not**
by ingesting the CCM `verification_coverage[]` wire key. The reasoning is in the
decisions below; the CCM-side source remains
`../CodeChronicleMapping/docs/cc-provenance-contract.md` for the wire shape, but
CC no longer consumes it for e-Laws editions (see decision 5).

## CC design decisions (settled)

1. **No new model. The calendar is `Consolidation`.** Each row already *is*
   an attestation interval `[effective_from, effective_to]` for one e-Laws
   consolidation period, built from that page's own banner
   (`scripts/build_elaws_consolidations.py`) and live on prod (OBC 2006: 20,
   2012: 34). A captured consolidation page is **one fact read two ways** — the
   thing we link to (source provenance) *and* the thing we cross-checked against
   (confidence). We do not maintain a second calendar. The model is named
   **`Consolidation`** — the dropped `Elaws` prefix named the *source*, not the
   rows; PDF reprints (decision 5) will be rows in the same table.

2. **`basis`/`as_of` are not stored — they're interval geometry.** A
   continuously-attested span is a positive-width interval; a point attestation
   (a PDF/gazette reprint) is a zero-width interval (`start == end`). *Inside* an
   interval ⇒ attested ⇒ interval claims (ranks 2–3) legitimate; in a *gap
   between* intervals ⇒ not attested ⇒ rank 4/5 — regardless of whether the
   neighbours are points or spans. `periodic ⟺ start == end`, derived, never a
   column. This is *more* expressive than the discriminator: a hybrid edition (a
   continuous span, then later point reprints) needs no special case.

3. **`not_covered` is dropped.** We do not ship a consolidation until every
   provision in it is covered, so the explicit physical-exception list (blank /
   OCR-dead pages) is always empty. The one remaining coverage exclusion is
   **computed, not stored**: a consolidation at date C covers provision P only if
   P had a version in force at C — the **existence rule**. It handles
   amendment-added and revoked provisions for free, off the version timeline CC
   already has (`effective_date`/`ineffective_date`).

4. **`effective_to` becomes `NOT NULL`; the un-promisable tail is a zero-range
   point.** A historical period is genuinely closed `[from, to]` — e-Laws
   republished at its end, which *proves* the text held across it. The *current*
   consolidation has no closing republication, so we cannot promise it forward;
   it is encoded as a **zero-range point** `[d, d]` (attested at the instant, no
   forward promise). `NULL` (which previously meant "the live row") is
   eliminated. This puts open-tail honesty **in the data**, so the rank table
   self-derives with no special-casing and no external "currency" cutoff:
   - a date inside a *closed* period is bracketed both sides → **rank 2**;
   - a date after the *current* zero-range point has only a prior bound →
     **rank 4/5** (the open tail, resting on our reconstruction).
   The current period getting rank 4 while equivalent historical periods get
   rank 2 is the *correct* asymmetry: the only difference is whether a later
   consolidation exists to close the bracket.

5. **The CCM wire key `verification_coverage[]` is not ingested for e-Laws.** CC
   already owns the e-Laws calendar via `Consolidation`. The wire key
   becomes relevant only for the PDF/periodic editions CC *cannot* self-build (no
   e-Laws snapshots) — those would load into the renamed `Consolidation` table
   (with a `source`/`kind` column distinguishing an e-Laws URL from a PDF
   reference) when acquisition unblocks upstream. Optionally, a load-time
   assertion can cross-check CCM's emitted `[start, end]` envelope against the
   consolidation rows to catch drift, without storing CCM's copy.

6. **The base regulation is the *first* attestation — a plain zero-range point.**
   The base reg's enactment is folded into the calendar as a **zero-range
   attestation candidate** (the "first consolidation"), competing for
   covering/prior/following exactly like an e-Laws consolidation and rendered —
   with its own `▪` square glyph + a link to the reg's `source_url` — **only when
   selected**. It is *not* always-on and does *not* span an interval. Rationale:
   "no chain to have gotten wrong" licenses a reliable attestation at the
   **enactment instant** (reconstructing the as-enacted text applies no amendments),
   but *not* a whole-window claim — a missed amendment inside what we think is the
   base version's window is exactly the risk this UI guards against, so a
   base-version date past enactment with no consolidation reads **rank-4 open
   tail**, not force-verified. The existing machinery scopes it with no special
   rank-table case: `ver_at(enactment)` is the base version (so the same-version
   test makes it attest only the base version → rank-5 reconstructed prior for
   amended versions), and for an amendment-added provision `ver_at(enactment)` is
   `None` (the existence rule drops it). Because "latest-prior-wins," a later
   consolidation always beats the base for the prior slot, so the base never
   double-draws against a real consolidation (no overlap). Passed to
   `derive_status(version, query_date, base=...)` by the assemblers (date = base
   `Regulation.effective_date`, label = `O. Reg. {reg_id}`, link = `source_url`);
   never used to verify amended text against its own source. (When the table
   generalizes per decision 5 — a `kind`/`source` column for PDF reprints — the
   base reg could instead be a row with `kind="base"` — equivalent, but not worth
   a migration now.)

## The statuses — 5 ranks, derived at query time

Nothing per-version is stored. CC derives the rank from two things it already
has: the `Consolidation` rows for the edition + each version's
`effective_date`/`ineffective_date`. A single version's window can sit at a high
rank early and a low rank late, so the rank is **per (provision, query-date)**,
computed on read — never baked onto a version.

The discrete **covered consolidation dates** are the `effective_from` of each
`Consolidation` row (the current row being a zero-range point); the
*interior* of a closed `[from, to]` is the e-Laws-attested-unchanged span that
makes ranks 2–3 legitimate. A date "covers" provision P only if P had a version
in force at it (the existence rule, decision 3) — non-covering dates fall through
to the next consolidation.

Given a query `(provision P, date D)`, the version `V` in force at `D`, the
prior covered consolidation `Cᵢ` (largest covering-P date `≤ D`) and the
following `Cⱼ` (smallest covering-P date `> D`):

| Rank | Claim (wording TBD) | Condition |
|---|---|---|
| 1 | Verified against the **[date]** consolidation | `D` equals a covered consolidation date |
| 2 | Unchanged between the **[date]** and **[date]** consolidations | `Cᵢ` and `Cⱼ` both exist **and** the same version is in force at both |
| 3 | Matches the **[date]** consolidation; **[effective\|end]** date reconstructed | `Cᵢ` and `Cⱼ` both exist **and** a version boundary falls inside `(Dᵢ, Dⱼ)` |
| 4 | Unchanged since the **[date]** consolidation, **[x]** days before | only `Cᵢ` exists **and** no version boundary after `Dᵢ` |
| 5 | Changed since the **[date]** consolidation, **[x]** days before — not yet confirmed | only `Cᵢ` exists **and** a version boundary after `Dᵢ` |

- **"Did P change between two consolidations?"** is read off the **chain's own
  version boundaries** (`effective_date`/`ineffective_date`), which are gated to
  agree with both consolidations at CCM build time. No pairwise comparison data
  ships — there is no `O(points²)` matrix to load.
- **The meaningful break is rank 3 ↔ 4** (a consolidation vouches for this
  date's text vs. we're resting on our own reconstruction). Rank 3 is
  text-solid (it matches the consolidation on its own side); only the *when* is
  reconstructed.
- **`x`** is measured from the bracketing consolidation to the **queried** date
  (not to today).
- For a fully-covered e-Laws edition, rank 3 is rare: e-Laws republishes on every
  amendment commencement, so consolidation boundaries coincide with version
  boundaries. Rank 3 is primarily a *periodic* (PDF reprint) phenomenon, where
  reprints can straddle an interim change.

## Epistemics CC must preserve (why the ranks are shaped this way)

A consolidation published "as of D" certifies the cumulative net in-force state
**at that instant** and nothing else. Carry these into whatever UI emerges:

- **A point attestation does not stretch to D−1 or D+1.** D+1: an amendment we
  lack. D−1: two cancelling errors in `(D−1, D]` net out at D while D−1 is
  wrong. So rank 1 is only the *exact* covered date. (Decision 4's zero-range
  current point encodes the "no stretch to D+1" rule structurally.)
- **Interval claims (ranks 2–3) are legitimate only for a *continuous* service**
  (e-Laws attests "nothing changed" between its own snapshots). A *periodic*
  publisher makes no claim about the gaps — its interior is reconstruction-only.
  (Decision 2: this is interval-interior vs. inter-interval gap.)
- **Bracketed ≠ verified.** A change-and-revert inside one inter-consolidation
  window is invisible at both ends. Bracketing makes it improbable, never
  impossible — so a bracketed interval is labelled "bracketed," and we always
  expose the bracket dates + derivation for audit.
- **Recency (rank 4) supports *stability only*.** "Amendments take time to
  draft" softens an *unchanged* tail (rank 4 may decay toward "unknown" as `x`
  grows); it does **nothing** for a *reconstructed change* (rank 5 gets no
  recency benefit).
- **No backward extrapolation.** A *future* consolidation says nothing about a
  past query — so a date before the first covered consolidation is
  `unconfirmed`, never a low rank. (This is why the table has a "only `Cᵢ`" row
  but no "only `Cⱼ`" row.)
- **Default for any uncovered date: `unconfirmed`.** Never render absence of
  coverage as confidence.

## Relationship to existing CC models

- **`Consolidation`** is now *the* source for the calendar (decision 1), not
  a neighbour to disambiguate. The original framing treated it as a different
  assertion ("which page shows this as it read?") from `verification_coverage`
  ("over which span did we cross-check?"); we concluded these are two readings of
  the same captured-page fact and unified them. Both `resolve()` callers key on
  `version.effective_date` (`api/formatters.py`, the permalink's
  `_provenance_result`), which coincides with a row's `effective_from`, so the
  zero-range change (decision 4) keeps source links resolving.
- **`verified` (bool on `CodeEdition`, from CCM `VERIFIED_EDITIONS`)** — the
  coarse, manual, whole-edition sign-off. `verification_coverage` is its
  date-resolved, computed companion; frame them as a pair. (OBC 1997 is
  `verified=False`, dev-only.)
- **`regulations[].commencement[]` / `RegulationClause.commencement`** — the
  existing derivation behind a rank-3 *reconstructed date*; the natural "how did
  you get this date?" drill-down (`templates/partials/_commencement_detail.html`).
- **`CorpusCurrency`** — the masthead's global "current to **[date]**" stamp.
  With zero-range current points (decision 4) the rank derivation no longer
  needs it; it remains the global data-freshness display.

## Presentation — settled (the attestation rail)

Settled over an iterative mockup (`.tmp/verification-coverage-mockup.html`, v8 —
throwaway; this section is the canonical spec). The feature **replaces** the
single `e-Laws consolidation · as it read …` line at the bottom of
`_provenance_band.html` (lines ~118–130) with one **attestation rail**: a single
horizontal timeline of the version's in-force window, annotated with the
consolidations that bracket the query date.

### The one rule

The in-force **line** spans the version's window `[From, Until]`, drawn to scale,
and is **always the in-force colour** (`--secondary`). Its **texture** is the
verification, not its hue:

- **solid** = a consolidation's validity range attests this stretch;
- **dashed, same colour & thickness** = in force here, but no consolidation
  attests it (reconstruction).

"Show consolidation validity as a range" falls out for free: a consolidation's
solid run *is* its `[effective_from, effective_to]`. This refines the rank table
above — a consolidation is an **interval**, not a point. Concretely: *covered* =
the query date lies inside one consolidation's interval (subsumes the old rank-1
"exact date" and rank-2 "closed-period interior" into one state, because an
e-Laws closed period is a single positive-width row); *bracketed* = the query
date sits in a **dashed gap between two zero-range** point consolidations
(periodic / PDF reprints); *open tail* / *reconstructed* / *new provision* as in
the rank table.

### Marker vocabulary (luminance + redundant shape channel; one hue break)

- **`◄════►`** — a consolidation's interval: an **outward arrowhead at each end**
  of its solid run. The two heads **fuse into a `◆` diamond** at zero range, so a
  multi-year e-Laws period and a one-instant reprint use the *same* primitive,
  clamped. An end that falls **outside** the in-force window is dropped (no head);
  a consolidation **wholly outside** the window collapses to a **single inward
  head** parked in a fixed off-line slot (prior → `►` at left, following → `◄`
  at right).
- **Hollow ring `◯`** (accent outline) — a **reconstructed in-force date**: the
  band's `From` when no consolidation pins exactly when the version commenced
  (the rank-3/5 reconstruction). Drawn **once**, as the `From` marker — the
  reconstructed boundary and the in-force `From` are the same fact (the "merge").
- **Filled square `▪`** — the **base regulation's enactment**, a *zero-range*
  attestation point (decision 6). Same primitive as a zero-range consolidation,
  but a distinct glyph because it's the *source*, not an e-Laws snapshot. It's the
  "first consolidation": it renders only when it's the selected
  covering/prior/following — a `▪` in the covering/prior lane when in-window, or in
  the off-line-left gutter when it predates the window. A *later* consolidation
  always wins the prior slot, so the `▪` never collides with a consolidation
  diamond.
- **Highlight tick** (`--highlight`, same token as the band's query-date tick) —
  the queried date's position on the line.

The single hue break is texture-internal (solid accent vs. dashed accent), with
the reconstruction signalled by the **ring**, not a colour. Strike-red is **not**
used (an earlier draft did; dropped — a reconstructed change is a ring, same as
any boundary, distinguished only by whether a following consolidation brackets it).

### Date row + leader lines (fixed lanes)

All dates sit in **one same-height row above the line**; a thin **leader line**
drops from each to its exact point on the timeline. The leader's *target* encodes
the date's kind (line-end = `from`/`until`; arrowhead/diamond = a consolidation;
highlight tick = query). Each label is two lines: a role caption + the date
(`yyyy-mm-dd`).

- **Fixed lanes (decided: option B).** Label x is standardized, not data-driven —
  `from` 18% · in-window `prior/covering` ~36% · `query date` 50% · in-window
  `following` ~64% · `until` 82%, with **off-line prior 6% / off-line following
  94%** in the gutters. The in-force window is drawn **18%→82%**, leaving
  symmetric off-line gutters (this spacing stops `until`/`following` and
  `from`/`prior` captions merging).
- **Leaders carry the position.** A leader is **vertical** for the anchored
  markers — `from`, `until`, and the off-line slots (nothing to reconcile, they're
  fixed) — and **leans** for the data-driven ones (in-window consolidations, the
  query). The lean *is* information: in an open tail the `query date` leader rakes
  hard toward `current`; in a new provision it rakes back toward `from`.
- **Role wording (final).** `from` · `until` · `query date` ·
  `prior`/`covering`/`following consolidation`. The word **`consolidation` is the
  link** (to that consolidation's e-Laws URL). `covering` (never "current") is the
  one whose interval contains the query date — "current" wrongly implies *now* for
  a past range. The off-line / open-tail `until` reads `current` (italic) when the
  version is still in force.
- **Label-collision is a 1-D solver** (implementation): given each date's true x,
  assign a row x minimizing total lean subject to `|rowX − neighbourX| ≥ minGap`;
  a left-to-right greedy pass suffices for ≤5 labels and is a no-op (all leaders
  vertical) when everything already fits. A pre-pass merges two labels within ε
  into one (e.g. a consolidation that starts exactly at `From`).

### The states (mock cards → rank → wording)

| State (rank) | Geometry | Status wording (final) |
|---|---|---|
| **Covered** (1) | query inside one consolidation's solid interval | "Verified against the **[from – to]** consolidation, whose range covers the query date." |
| **Bracketed · unchanged** (2) | query in a dashed gap; prior + following diamonds; version spans both | "Unchanged between the **[prior]** and **[following]** reprints — bracketed both sides, span between not directly attested." |
| **Bracketed · reconstructed** (3) | as 2, but `From` ring falls inside the bracket | "Text matches the **[prior]** consolidation; the **[From]** in-force date is reconstructed. **[following]** confirms no later change." |
| **Open tail · unchanged** (4) | solid to the last consolidation's `to`, then dashed to `current`; no following | "Verified through **[to]**; unchanged since, but no later consolidation attests the tail." |
| **Open tail · reconstructed** (5) | off-line prior `►`; `From` ring; dashed line; no following | "Changed since the **[prior]** consolidation; the **[From]** in-force date is reconstructed and no later consolidation has confirmed it." |
| **New provision** (unconfirmed) | `From` ring; fully dashed; no prior, no following | "Introduced by amendment on **[From]** — predates every published consolidation, so it is not yet confirmed." |

`[x]`-days decay (rank 4) is **not** a separate visual — the dashed tail already
carries "unattested"; the day-count, if shown, lives in the status sentence only.

### Where it surfaces & the audit affordance

- One rail in `_provenance_band.html` replaces the consolidation line; both
  assemblers — `_format_single_result()` (`api/formatters.py`) and
  `_provenance_result()` (`core/views/regulation.py`) — feed it, so it reaches
  every surface (search, transition-compare, permalink) at once.
- **Derivation ⌄** disclosure reuses `_commencement_detail.html` to show the
  bracket dates + the commencement derivation behind a reconstructed `From`.
- Mobile (`tasks/5.x-mobile-*`): the rail is horizontal-scroll-free at narrow
  widths because positions are %; the date row's leader solver must fall back to
  fewer visible labels (TBD at build).

## Implementation plan

**P1 — data + derivation (no new model):**

1. `Consolidation.effective_to` → `NOT NULL`; migration backfills existing
   `NULL` (live) rows to `effective_to = effective_from`.
2. `scripts/build_elaws_consolidations.py` current-banner branch returns
   `(from, from)` instead of `(from, None)`; update the NULL docstrings on the
   script, the model field, and `resolve()`.
3. Simplify `ConsolidationManager.resolve()` — drop the
   `effective_to__isnull` arm (no NULLs remain).
4. Pure `derive_status(version, query_date)` reading `Consolidation` rows +
   version dates; existence-rule coverage; the 5-rank logic above. Returns the
   rank **plus** the supporting facts (prior/next covered dates, `x`, source)
   for the audit affordance.
5. Unit tests against real OBC 2006/2012 rows: each rank, the head
   (`unconfirmed`, no backward extrapolation), the tail past the current point,
   and the amendment-added provision.
6. **Verify before flipping the column:** confirm the current version's
   `effective_date` equals the live consolidation's `effective_from` on the real
   rows, so source links do not silently vanish.

**P2 — presentation (attestation rail):** the `## Presentation` spec is settled;
build order:

1. **Render contract.** `derive_status()` (P1.4) returns a render dict the
   template can consume without geometry logic. Shape per (provision, query-date):
   ```
   {
     rank: 1..5 | "unconfirmed",
     status_text: str,                       # the final wording, dates interpolated
     in_force: {from: date, until: date|None},   # None ⇒ "current"
     query_date: date,
     consolidations: [                       # 0..n, each an interval
       {from: date, to: date,                # from == to ⇒ zero-range diamond
        url: str, role: "covering"|"prior"|"following",
        off_line: "left"|"right"|None,       # wholly outside in_force window
        clamp_left: bool, clamp_right: bool} # an end outside window ⇒ no head
     ],
     reconstructed_from: bool,               # draw From as a ring (rank 3/5/new)
   }
   ```
   Geometry (lane x, leader targets, % positions, the 1-D label solver) is the
   template/JS's job from these facts — keep `derive_status()` pure data.
2. **Template.** New `templates/partials/_attestation_rail.html` (the rail markup
   from the mock), included by `_provenance_band.html` in place of the
   consolidation line. Positions computed from the contract; CSS uses existing
   role tokens (`--secondary` line, `--highlight` tick, `--ink-3` leaders) — no
   new colours. Lane constants + the leader collision pass live in a small
   `static/js` helper or server-side in the formatter (decide at build; the mock
   does it inline).
3. **Wire both assemblers.** `_format_single_result()` and `_provenance_result()`
   attach the contract dict; `never_in_force` versions suppress the rail (as the
   old line was).
4. **Derivation ⌄** reuses `_commencement_detail.html` for the reconstructed-From
   drill-down.
5. Visual regression / template tests for each of the six states.

## Status

- **Data model + derivation (P1):** **built** (2026-06-18). `effective_to` is now
  `NOT NULL` (migration `0039`, backfills any live `NULL` → `effective_from`); the
  build script emits the live row as a zero-range `(from, from)`; `resolve()` is
  the plain closed-interval query; `core/verification.derive_status()` returns the
  render contract. Tests: `core/tests/test_verification.py` (9, all six states +
  the no-backward-extrapolation head + amendment-added + suppression) and the
  updated `core/tests/test_consolidations.py` (zero-range current semantics) pass;
  ruff + mypy + pyright clean. **P1.6 finding:** the committed calendar has *zero*
  `NULL` tails (every OBC row is a closed interval, e.g. 2012 ends `2024-12-31`),
  so dropping the `isnull` arm is a behaviour no-op on real data — no source link
  that resolved before can vanish; the only residual invariant
  (`effective_date == effective_from` for a live zero-range row) holds because a
  consolidation period *begins* at the current version's commencement.
- **Presentation (P2):** **built** (2026-06-18). `core/verification.rail_geometry()`
  ports the settled v8 mock to deterministic server-side % (fixed lanes ⇒ no JS
  label solver needed); `build_rail()` chains derive→geometry for the assemblers.
  `templates/partials/_attestation_rail.html` renders static HTML + inline SVG from
  that dict; the `.vrail` CSS is scoped inline in `base.html` (real tokens, the
  mock's geometry). Wired into both assemblers (`_format_single_result` uses the
  user's query date; `_provenance_result` uses the version's own `effective_date`,
  replacing the old "as it read" line).
  - **The rail is now the band's body.** `_provenance_band.html` was restructured:
    the rail sits as the flex-1 cell, superseding the old From·rail·Until·Dur cells
    and the "✓ Covers" cell (a compact From/Until remains only as the no-rail
    fallback for never-in-force / no-query-date). From/Until **commencement
    provenance** moved into the rail's status row as the **Derivation** (`cmOpen`)
    and **End date** (`cmOpenUntil`) disclosures. The graphic is `@xl`-gated (verbal
    status is the narrow/compare-pane fallback).
  - **Base regulation (decision 6).** Folded in as a **zero-range attestation
    candidate** (the "first consolidation") — competes for covering/prior/following
    like any consolidation, renders with a `▪` square only when selected, never
    always-on (so no overlap), never an interval (base-version dates past enactment
    are honest rank-4 open tails, not force-verified). The assemblers build
    `base={date,label,url}` from the base `Regulation` and pass it to `build_rail`.
  - Tests: `test_verification.py` now **21** (derive + geometry-vs-mock + base-reg +
    partial render); full sweep (verification, templates, band, formatters,
    consolidations) **111 green**; ruff + mypy + pyright clean. Mock at
    `.tmp/verification-coverage-mockup.html` (v8, throwaway).
- **Contract note:** `tasks/complete/provenance/ccm-output-contract.md` should
  record that CC derives confidence from the consolidation table + `CorpusCurrency`,
  not from the wire `verification_coverage[]` — coordinate with CCM (the wire key
  may narrow to PDF/periodic editions). Not yet updated.
- **Blocked upstream:** periodic (PDF/NBC) coverage depends on CCM acquiring
  consolidation PDFs; until then non-OBC editions have no consolidation rows
  (all dates `unconfirmed`).
