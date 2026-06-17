# Verification coverage — per-(provision, date) confidence statuses

When a user reads a provision "as it read on date D," how confident are we that
our reconstruction of the in-force text is **actually correct** for that date —
i.e. that it has been cross-checked against an independent, date-matched
authoritative consolidation? This feature surfaces that confidence, and
honestly flags the periods where we **cannot** confirm it.

CCM now emits the **data** (an edition-level attestation calendar) and defines
the **statuses** (a 5-rank vocabulary + a query-time derivation). This doc
captures both for CC adoption. **Presentation is deliberately left open** — see
`## Presentation — open for discussion`. Nothing CC-side is built yet.

Source of truth for the wire shape + algorithm:
`../CodeChronicleMapping/docs/cc-provenance-contract.md` →
`## Top-level: verification_coverage[]` (and the CCM-side task
`../CodeChronicleMapping/tasks/verification-coverage.md`). Restated inline below
for convenience; if the two ever drift, the CCM contract wins.

## The data — `verification_coverage[]` (new top-level edition key)

Always present on every consolidated edition JSON (`[]` when no verification
source covers the edition), mirroring `mapping_coverage[]`: **absence of
coverage never reads as confidence.** A `basis` discriminator carries the
epistemic difference between a continuous service and periodic reprints.

```jsonc
// e-Laws — a continuous point-in-time service: one entry spans the verified region
"verification_coverage": [
  { "basis": "continuous", "start": "2014-01-01", "end": "2025-01-01",
    "source": "ontario.ca e-Laws point-in-time" }
]

// PDF / gazette reprints — periodic: one entry per as-of instant (not yet emitted)
"verification_coverage": [
  { "basis": "periodic", "as_of": "2010-01-01", "source": "NBC 2010 consolidated reprint" },
  { "basis": "periodic", "as_of": "2015-06-01", "source": "NBC 2015 consolidated reprint",
    "not_covered": ["3.1.4.7.", "9.10.18.6."] }
]
```

- **`start` / `end`** (continuous) — ISO date or `null` (open boundary). **These
  are the honest *verified* span, NOT the edition span.** They come from the
  actual snapshot coverage, which routinely differs from when the edition was in
  force: OBC 1997 commenced 1998 but the span starts `2003-09-01` (first e-Laws
  snapshot); OBC 2012's span ends `2025-01-01` (last captured snapshot) though
  the edition is still in force. **Consequence: a continuous edition can have an
  unverified head before `start` and an unverified open tail after `end`** — do
  not assume e-Laws is fully confident end-to-end.
- **`as_of`** (periodic) — the single instant the reprint attests.
- **`not_covered`** (periodic, optional) — provision IDs a reprint did *not*
  attest (blank / OCR-dead pages). `O(exceptions)`, never `O(provisions ×
  points)`; for a listed provision, fall through to the next consolidation.
- **`source`** — human-readable provenance string.

**What's emitted today:** e-Laws editions (OBC 1997/2006/2012) carry the
`continuous` entry. Every gazette/PDF edition carries `[]` until consolidation
PDFs are sourced (CCM-side work, blocked on acquisition). So in practice CC will
see one `continuous` entry for OBC and `[]` for NBC/others initially.

## The statuses — 5 ranks, derived at query time

Nothing per-version is stored. CC derives the rank from **two things it already
has**: this edition-level calendar + each version's `effective_date /
ineffective_date`. A single version's window can sit at a high rank early and a
low rank late, so the rank is **per (provision, query-date)**, computed on
read — never baked onto a version.

Given a query `(provision P, date D)`, the version `V` in force at `D`, the
prior covered consolidation `Cᵢ` (largest covered date `≤ D`) and the following
`Cⱼ` (smallest covered date `> D`):

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

## Epistemics CC must preserve (why the ranks are shaped this way)

A consolidation published "as of D" certifies the cumulative net in-force state
**at that instant** and nothing else. Carry these into whatever UI emerges:

- **A point attestation does not stretch to D−1 or D+1.** D+1: an amendment we
  lack. D−1: two cancelling errors in `(D−1, D]` net out at D while D−1 is
  wrong. So rank 1 is only the *exact* covered date.
- **Interval claims (ranks 2–3) are legitimate only for a *continuous* service**
  (e-Laws attests "nothing changed" between its own snapshots). A *periodic*
  publisher makes no claim about the gaps — its interior is reconstruction-only.
- **Bracketed ≠ verified.** A change-and-revert inside one inter-consolidation
  window is invisible at both ends. Bracketing makes it improbable, never
  impossible — so a bracketed interval is labelled "bracketed," and we always
  expose the bracket dates + derivation for audit.
- **Recency (rank 4) supports *stability only*.** "Amendments take time to
  draft" softens an *unchanged* tail (rank 4 may decay toward "unknown" as `x`
  grows); it does **nothing** for a *reconstructed change* (rank 5 gets no
  recency benefit).
- **Default for any uncovered date: `unconfirmed`.** Never render absence of
  coverage as confidence.

## Relationship to existing CC models — do not conflate

- **`ElawsConsolidation`** (`tasks/provision-source-links.md`, Axis 2) is the
  closest neighbour and the most important distinction. That model answers
  *"which e-Laws consolidation page shows this as it read?"* — a **source link**
  (presentation provenance). `verification_coverage` answers *"over which span
  did we cross-check our reconstruction against e-Laws?"* — a **confidence
  claim**. They draw on the same underlying e-Laws snapshot calendar but make
  different assertions. **Likely reuse:** the `continuous` `[start, end]` should
  line up with the span `ElawsConsolidation` rows cover for the edition — worth
  reconciling the two date sources rather than maintaining them independently.
  Decide deliberately whether ranks read from `verification_coverage[]`, from
  `ElawsConsolidation`, or a reconciled view.
- **`verified` (bool, from CCM `VERIFIED_EDITIONS`)** — the coarse, manual,
  whole-edition sign-off. `verification_coverage` is its date-resolved, computed
  companion. Frame them as a pair; don't duplicate. (Note OBC 1997 is currently
  `verified=False` — see `provision-source-links.md`.)
- **`regulations[].commencement[]`** (`source` / `computation` / `depends_on`)
  is the existing derivation behind a rank-3 *reconstructed date* — the natural
  "how did you get this date?" drill-down.

## Presentation — open for discussion (NOT decided here)

The labels in the rank table are placeholders. Everything below is deliberately
left for a design conversation:

- **Final label wording** per rank (and how to fill `[date]` / `[x]` / the
  `effective|end` choice in rank 3).
- **Colour / icon system.** CCM's only recorded principle: encode order in
  **luminance + a redundant non-colour channel** (icon/fill), not a rainbow (hue
  isn't perceived as ordered past green/amber/red and is worst-case for
  colour-blind users / small chips); put the one hue break at the cool↔warm
  (consolidation-backed ↔ reconstruction-only) boundary, i.e. rank 3 ↔ 4. Not
  binding.
- **Where it surfaces** — the existing `_provenance_band.html` strip? a chip on
  the version card? search results vs. permalink vs. transition-compare? Mobile
  (`tasks/5.x-mobile-*`) treatment.
- **Rank-4 decay visualization** as `x` grows, and the threshold where it reads
  as "unknown."
- **The audit affordance** — how the bracket dates + commencement derivation are
  exposed for ranks 2/3.

## Status

- **CCM (producer):** `verification_coverage[]` is emitted (e-Laws `continuous`;
  gazette/PDF `[]`), validated at write time, and specified in
  `docs/cc-provenance-contract.md`. Done, not yet committed.
- **CC (consumer):** not started. Needs (1) a place to read/store the calendar
  off the loaded edition JSON, (2) the rank-derivation function above, (3) the
  presentation decisions. The wire shape should also be folded into the
  authoritative contract (`tasks/complete/provenance/ccm-output-contract.md`)
  once stable — coordinate; don't fork it.
- **Blocked upstream:** periodic (PDF/NBC) coverage depends on CCM acquiring
  consolidation PDFs; until then non-OBC editions are `[]` (all dates
  `unconfirmed`).
