# `cross_references[]` gains `alternates[]` — and `to_provision_id` changes meaning

> **✅ Landed 2026-07-28.** Adopted CC-side: `ProvisionCrossReferenceAlternate`
> child model (migration `0041`, folded in — no separate migration), loader
> resolves `alternates[]` verbatim, `.cross-ref-alt` chip on both search and the
> permalink page. Reloaded all three OBC editions: **153 alternate rows** (29
> 1997, 62 2006, 62 2012), 0 unanchored. Contract updated at
> `tasks/complete/provenance/ccm-output-contract.md` §`cross_references[]`.
> Original ask preserved below.

> **⚠️ Adoption is required, not optional.** An earlier draft of this note said
> nothing breaks if CC ignores `alternates[]`. That is no longer true. Please
> read "What changed for the consumer" before shipping the next CCM import.

**From CCM.** Producer side is implemented; the records ship with the next
build of all three OBC editions.

Authoritative contract section to update when adopted:
`tasks/complete/provenance/ccm-output-contract.md` §`cross_references[]`.

## What changed for the consumer

On a record carrying a curator `note`, `to_provision_id` used to be **our
corrected answer**. It is now **what the Code printed**, and our answer moves
into `alternates[]`.

**127 records now carry an `alternates[]` entry** — 5 in OBC 1997, 60 in OBC
2006, 62 in OBC 2012 (measured on the shipped builds). If CC renders only
`to_provision_id`, every one of them silently links to the *uncorrected*
provision: the NFPA 13 `3.15.x`→`3.16.x` renumbers, the CSA B64.6.1
`7.6.4.2.`→`7.6.2.4.` transposition, the CGSB glass rows, the ISO 8201 fire
alarm row. No error, no dangling reference, no gate fires — both ids resolve to
real provisions. It just points at the wrong one.

A further 91 corrected records still lead with our reading, unchanged from
today: those are the ones whose printed id was **never enacted**, so there is
no printed link to show. We verified the split holds exactly — every record
whose primary is not the printed id has a printed id that exists nowhere in
that edition. A further 41 ship a note with an empty target, where the printed
id was never enacted and no better reading could be established.

The **shape** is unchanged and no field was removed, so ingestion will not
fail. Only the meaning moved.

Separately, four records that cited a **table whose article the edition never
enacted** used to resolve to that table's grandparent — `Table 9.23.17.2.A.`
landed on Section `9.23.` with an empty `note`, which read as an ordinary link.
The producer no longer walks a table id up the trunk, so those are now
adjudicated and carry a `note` (three point at the article the Crown itself
later named; one at the companion table named in the same sentence). Nothing
for CC to change — the targets simply got correct.

### Why we made this change

Because the Code's own words outrank our reading of them. A registry row that
cites the wrong provision is still what the Crown enacted; substituting our
correction told the reader the Code said something it did not, and gave them no
way to check us. Now both links ship — printed first, ours beside it, the
`note` explaining the difference — and the reader judges.

Placement is derived, never declared: if the printed id resolves it is the
primary link and our reading (if any) is the alternate; if it does not resolve,
our reading becomes the primary; if there is neither, the record ships an empty
target with the `note` alone, exactly as before.

## What changed and why

The Documents-Referenced registry tables carry a reverse index — *standard X
is referenced at provision P*. Two OBC 1997 rows carry **each other's** Code
Reference:

| row | prints | the provision that actually names the standard |
|---|---|---|
| `CAN/CGSB-12.11-M90` *Wired Safety Glass* | `4.3.6.1.(1)` | `3.3.1.18.(2)` |
| `CAN/CGSB-12.20-M89` *Structural Design of Glass* | `3.3.1.18.(2)` | `4.3.6.1.(1)` |

Both OBC 2006 and OBC 2012 (independently sourced from e-Laws) place them the
other way round, so the association is wrong in the 1997 rendering.

The point for the wire shape: **each printed id links correctly.**
`4.3.6.1.(1)` really is Article 4.3.6.1.; it is merely printed in the wrong
row. So the existing dispositions were both unusable —

- a **redirect** would break a link that was never wrong, and
- a **no-link** would drop a citation that resolves fine.

We also do not edit the Crown's text: the row ships verbatim. The links are
our addition, so that is where the finding belongs — link **both** provisions
and say why two appear.

The same shape covers a citation that outlived its target: OBC 1997's
`CAN/CSA-B125-93` row cites Article `7.2.10.7.`, which required shower valves
to conform to B125 until it was revoked and reserved on 2004-09-01, the
requirement moving to Sentence `7.6.5.2.(1)`. The row was never updated.
Primary link stays on the reserved Article (that is what the Crown filed);
`7.6.5.2.` rides alongside so the reader lands somewhere useful.

## Wire shape

```json
{
  "from_provision_id": "2.6.3.2.", "from_division": "", "from_version": 6,
  "surface_text": "4.3.6.1.(1)",
  "container": "table", "table_id": "Table-2.6.3.2.", "start": 8412, "end": 8424,
  "to_provision_id": "4.3.6.1.", "to_division": "",
  "targets": [ {"version": 0, "effective_date": "...", "ineffective_date": "..."} ],
  "alternates": [
    {
      "to_provision_id": "3.3.1.18.", "to_division": "",
      "targets": [ {"version": 0, "effective_date": "...", "ineffective_date": "..."} ]
    }
  ],
  "note": "This row and the row for CAN/CGSB-12.20-M89 appear to carry each other's Code Reference. …"
}
```

- **`alternates[]` is omitted when empty** — not `[]`. Read it as
  `record.get("alternates", [])`. Around 130 records out of ~43,000 carry one;
  always-emitting would cost more than it documents.
- Each element has the **same three keys** a primary link has —
  `to_provision_id`, `to_division`, `targets[]` — resolved and date-sliced by
  the same code path, so `targets` is stored verbatim exactly as the primary's
  is. No note per alternate; the record's single `note` explains the pair.
- Today `len(alternates) <= 1`. The field is a list because "printed vs
  intended" is not obviously the only case, but nothing yet needs more.

## Why inside the record rather than a second record

`§cross_references[]` states *one record per citation*, *one row per record*,
and CC renders a span as `html[start:end]` with no matching. Two records
sharing `start`/`end` would wrap the same text twice. Keeping the alternate
inside the record preserves both invariants and leaves the anchoring code
alone.

## Suggested rendering (CC's call)

The presentation already exists: multi-version fan-out attaches **chips** to a
span rather than a second anchor. An alternate provision fits the same
treatment — one anchor on the printed target, a chip for the alternate, the
`note` as the tooltip/expander explaining why both. The distinction worth
preserving is that the primary is *what the Code printed* and the alternate is
*what the evidence says was meant*; collapsing them into two equal links loses
the thing the note is there to say.

Ingestion-wise this is a new nullable relation off `ProvisionCrossReference`
(or a JSON column, if the ≤1 cardinality holds) — CCM has no opinion.

## Producer-side detail, for context

`data/inputs/manual-supplements/cross-ref-corrections.json` no longer lets the
curator say where the links land. The old `resolves_to` / `annotate_only` /
`also_resolves_to` trio encoded one question the writer can answer for itself —
*does the printed id resolve?* — and nothing forced them to agree with it, so a
well-formed entry could quietly suppress a link the Crown printed. All three
are retired (the loader raises on them) in favour of a single
`intended_provision_id` + `intended_division`: the provision we believe was
meant, stated as a fact about the Code rather than an instruction about the
output.

Entries are curator-authored and sign-off gated; the corroboration detector
(`validate/docref_target_corroboration.py`) surfaces the leads, a human rules
on each.
