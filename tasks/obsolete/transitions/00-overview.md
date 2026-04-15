# Edition Provenance & Model Restructure — Overview

## Core Idea

Two distinct legal facts per provision, both tracked to their source:

1. **Commencement** — "When did this provision come into force?" Answered by
   the commencement section of the enacting regulation. Single value per
   provision per map version (inherit from edition-level when not overridden).

2. **Amendment history** — "Which regulation put this text here?" The full
   ordered chain of regulations that introduced or modified each provision,
   most recent first. Sections from the base regulation have no amendments.

Together these answer the forensic question: "Section X as it read on [date]
was introduced by [amendment reg] and came into force on [date] per
[commencement reg, provision]."

A `Transition` record carries commencement provenance. Amendment history is
a separate concern tracked per CodeMapNode.

**Audience**: forensic engineers who need certainty about exactly what was
in force on what date. We aim to be the definitive source — full amendment
depth, no silent assumptions.

## Problems Solved

1. **No provenance** — `CodeEdition.effective_date` and `superseded_date` are
   bare dates with no link to the regulation that established them.
2. **CodeMap vs CodeEdition confusion** — linked by stringly-typed
   `map_codes` ArrayField instead of a FK. Physical-file fields on wrong model.
3. **Transition data lacks real citations** — `transitions.json` has
   hand-written summaries, no actual provision quotes.
4. **`amendments` vs `amendments_applied`** — `amendments` is never consumed.
5. **Scattered date/regulation fields** — `effective_date`, `regulation`,
   `source_url` on CodeEdition are disconnected from their source provision.
6. **Commencement and amendment conflated** — the attribution pipeline
   answered "who last amended this?" but stored it where commencement
   provenance belongs. These are now explicitly separate.
7. **`ProvinceCodeMap` misnomer** — maps province → CodeSystem, not map.
   Should be `ProvinceCodeSystem`.
8. **No jurisdiction-aware in-force model** — NBC is published once but
   adopted on different dates by different provinces.

## Decisions (2026-03-26)

### Commencement: single field, not array

Each section has at most one commencement per map version. If not overridden
at the section level, inherit from the map-level `commencement` (the edition's
default commencement). Expand to array only if we encounter real split
commencement at the provision level (not expected).

### Amendments: full chain, as deep as it goes

Track every regulation that ever modified a provision, ordered most recent
first. We are the definitive source. CCM's `Section.amended_by` (currently
a single dict) expands to `amendments: list[dict]`.

### Display: provenance rail alongside content

Provenance is **immediately visible** when a result card is expanded — not
behind a toggle. Positioned as a rail:
- **Right side** for the current/matching edition
- **Left side** for the older edition in transition compare view
- **Below content** on mobile (collapses to tappable footer)

Most recent amendment shown by default; "N earlier amendments" expandable
to show the full chain.

### Color coding: provision-specific vs edition-general

- **Edition-general** (inherited commencement, base regulation): neutral/subdued
  styling. No special marker — this is the default state.
- **Provision-specific** (non-default commencement date, or amended by a
  non-base regulation): accent left-border on the provenance rail. Signals
  "this provision has its own provenance story."

### Copy button

Copies a structured legal reference:

```
OBC 2012, Div B, § 3.1.4.7. — Fire Separations
In force: 2015-01-01 (O. Reg. 332/12, s. 4.4.1.1(2))
Amended by: O. Reg. 139/17, s. 82
```

## Task Sequence

1. [Transition model + Amendment model + CodeMap FK + backfill](1-schema-and-backfill.md)
2. [Update code paths](2-update-code-paths.md)
3. [Remove old fields + cleanup](3-remove-old-fields.md)
4. [Template changes: provenance rail display](4-template-provenance.md)

Data population is handled by CodeChronicleMapping — see
`CodeChronicleMapping/tasks/transitions/`.

## Model Summary

```
ProvinceCodeSystem   ON → OBC           (which system does this province use?)
       ↓
CodeSystem           OBC                (the code family)
       ↓
CodeEdition          OBC 2024           (a specific legal edition)
       ↓
Transition           O. Reg. 163/24     (commencement: why it's in force)
       ↓
CodeMap              OBC_Vol1, OBC_Vol2  (physical map files, FK to edition)
       ↓
CodeMapNode          1.1.1.1.           (individual provisions)
     ↓   ↓
     ↓   Amendment    O. Reg. 139/17    (amendment: who put this text here)
     ↓
Transition           (provision-level)  (per-node commencement override)
```

## Data Flow: CCM → CodeChronicle

CCM map JSON produces two provenance structures per section:

```json
{
  "id": "3.1.4.7.",
  "division": "B",
  "commencement": {
    "regulation": "O. Reg. 332/12",
    "source_url": "https://...",
    "provision_id": "s. 4.4.1.1(2)",
    "provision_quote": "...",
    "effective_date": "2015-01-01"
  },
  "amendments": [
    {
      "regulation": "O. Reg. 139/17",
      "source_url": "https://...",
      "provision_id": "s. 82",
      "effective_date": "2017-07-01"
    },
    {
      "regulation": "O. Reg. 361/13",
      "source_url": "https://...",
      "provision_id": "s. 34",
      "effective_date": "2015-01-01"
    }
  ]
}
```

Sections with no `commencement` inherit from `CodeMap.commencement` (the
edition default). Sections with empty `amendments` are from the base
regulation (no annotation needed in the UI).

`load_maps` imports these into:
- `Transition` records (commencement, edition-level and node-level)
- `Amendment` records (per-node, ordered)

## What We Have vs What We're Missing

### Currently populated

| Data | Source | Status |
|------|--------|--------|
| Edition effective/superseded dates | `metadata.json` | Dates exist, **no provenance** |
| Whole-code transition overlaps (OBC) | `transitions.json` | Dates + summaries, **no quotes** |
| Provision-scoped transitions (OBC 2012 v08→v09) | `transitions.json` + `load_maps` stamping | Provisions identified, **no quotes** |
| Transition overlaps (BCBC, QCC, QSC, QPC, QECB) | `transitions.json` | Summaries only |
| Section-level commencement (e-Laws OBC) | CCM enricher | Per-section commencement attached to map JSON |
| Last-amender attribution (e-Laws OBC) | CCM enricher | Single `amended_by` dict per section |

### Missing or incomplete

| Data | Source needed | Status |
|------|---------------|--------|
| Full amendment chain per section | CCM: Legislative History + amending body | **Only last amender tracked** — need full chain |
| In-force provenance (commencement provisions) | e-Laws source regulation filings | Partially populated (OBC 2006: 91%, OBC 2012: 8%) |
| Transition provision quotes (Div C §4.1.x) | Cached e-Laws HTML | Done (7 TransitionRule objects) |
| Per-provision commencement (Y-prefix) | Cached e-Laws HTML | Done (438 provisions resolved) |
| Pre-e-Laws commencement/transition provisions | Gazette pipeline (currently discarded) | Not started |
| NBC in-force provenance | NRC publication + provincial instruments | Not started |
| Provincial adoption provenance | Per-province government sources | Not started |
