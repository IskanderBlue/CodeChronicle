# Edition Provenance & Model Restructure — Overview

## Core Idea

Every date-bounded legal state — "this edition is in force," "this provision
commences later," "the old edition is grandfathered" — is a **Transition**.

A `Transition` is the answer to "says who?" It carries:
- The source document and specific provision
- The actual quoted text of that provision
- The effective date and end date
- What it applies to (an edition or a specific provision)
- Which jurisdiction it applies in (for national codes adopted by provinces)

One model. One table. Different FK relationships express what each transition
applies to.

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
6. **Three names for one concept** — edition in-force, provision commencement,
   and grandfathered overlap are all the same thing.
7. **`ProvinceCodeMap` misnomer** — maps province → CodeSystem, not map.
   Should be `ProvinceCodeSystem`.
8. **No jurisdiction-aware in-force model** — NBC is published once but
   adopted on different dates by different provinces.

## Design Issue: Commencement vs Amendment (2026-03-25)

The Transition model covers **commencement** — when a provision comes into
force. But **amendment** (when the text of an already-in-force provision
is changed by a later regulation) is a different event that is not modeled.

These are distinct questions:
- **Commencement**: "When did this provision come into force?" → answered
  by the Transition model (effective_date, provision_quote from the
  commencement section of the enacting regulation).
- **Amendment history**: "Which regulation's text am I reading?" → not
  currently modeled. Would require tracking which regulation last
  amended each provision, separate from the commencement Transition.

The CodeChronicleMapping pipeline currently has:
- **Commencement data**: Y-prefix timeline + source filing commencement
  sections. Correctly captures when provisions commenced.
- **Attribution map**: Legislative History + amending body targets.
  Correctly identifies which regulation last amended each provision.
  But this is amendment history, not commencement provenance.

### What this means for the Transition model

The Transition model as designed is correct for commencement. For
amendment history, we need either:
- A separate field on CodeMapNode (e.g., `last_amended_by`)
- A separate model (e.g., `Amendment`)
- An additional Transition record type with a different semantic

Decision needed before implementation.

## Task Sequence

1. [Transition model + CodeMap FK + backfill](1-schema-and-backfill.md)
2. [Update code paths](2-update-code-paths.md)
3. [Remove old fields + cleanup](3-remove-old-fields.md)
4. [Template changes for provenance display](4-template-provenance.md)

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
Transition           O. Reg. 163/24     (why it's in force, with jurisdiction)
       ↓
CodeMap              OBC_Vol1, OBC_Vol2  (physical map files, FK to edition)
       ↓
CodeMapNode          1.1.1.1.           (individual provisions)
       ↓
Transition           (provision-level)  (per-node commencement or exception)
```

## What We Have vs What We're Missing

### Currently populated (will migrate to Transition records)

| Data | Source | Status |
|------|--------|--------|
| Edition effective/superseded dates | `metadata.json` | Dates exist, **no provenance** |
| Whole-code transition overlaps (OBC) | `transitions.json` | Dates + summaries, **no quotes** |
| Provision-scoped transitions (OBC 2012 v08→v09) | `transitions.json` + `load_maps` stamping | Provisions identified, **no quotes** |
| Transition overlaps (BCBC, QCC, QSC, QPC, QECB) | `transitions.json` | Summaries only |

### Missing entirely

| Data | Source needed |
|------|---------------|
| In-force provenance (commencement provisions) | e-Laws source regulation filings |
| Transition provision quotes (Div C §4.1.x) | Cached e-Laws HTML (not parsed) |
| Per-provision commencement (grey-background) | Cached e-Laws HTML (CSS class TBD) |
| Pre-e-Laws commencement/transition provisions | Gazette pipeline (currently discarded) |
| NBC in-force provenance | NRC publication + provincial instruments |
| Provincial adoption provenance | Per-province government sources |
