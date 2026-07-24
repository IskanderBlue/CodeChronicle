# Periodic (PDF/print) edition consolidation coverage

**Gated on new ingestion:** a periodic edition — NBC, print OBC (pre-1997),
or any edition with no e-Laws snapshots — entering the corpus. Blocked
upstream on CCM acquiring the consolidation PDFs/reprints; until then,
non-e-Laws editions have no `Consolidation` rows and every date on them
derives `unconfirmed`.

## What this is

The verification-coverage feature (attestation rail, 5-rank confidence
derivation) is fully built and live for e-Laws editions — design, decisions,
and implementation record in `tasks/complete/verification-coverage.md`. For
e-Laws editions CC self-builds the attestation calendar from each cached
consolidation page's own banner; the CCM `verification_coverage[]` wire key
is deliberately **not** ingested for them (recorded in
`tasks/complete/provenance/ccm-output-contract.md`).

Periodic editions are the case the wire key exists for: CC cannot self-build
their calendar (no e-Laws snapshots), so their attestation points — reprint
dates — must arrive from CCM.

## When a periodic edition lands

1. **Settle the wire shape with CCM** — `verification_coverage[]` narrowed to
   periodic editions; each reprint becomes a zero-range `[d, d]` attestation
   point (the machinery already treats `start == end` as a point; a
   change-straddling reprint is where rank 3 actually occurs).
2. **Generalize `Consolidation` rows** for non-e-Laws sources — a
   `kind`/`source` column distinguishing an e-Laws URL from a PDF/reprint
   reference (decision 5 in the completed card anticipated this; the base-reg
   `kind="base"` row noted there is an optional tidy-up at the same time).
3. **Load path** — ingest the wire key into `Consolidation` at `load_edition`
   time for periodic editions only; e-Laws editions keep the
   `load_consolidations` self-build. Optional: for e-Laws editions, assert
   CCM's emitted envelope matches CC's rows (drift check, no storage).
4. **No derivation changes expected** — `derive_status()` /
   `rail_geometry()` are interval-geometry-driven and already handle
   zero-range points, gaps (bracketed ranks 2–3), and open tails.
