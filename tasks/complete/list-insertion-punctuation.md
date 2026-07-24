# List-insertion punctuation — details-page copy

Copy for the **details page** at `/list-punctuation/` (`core:list_punctuation`,
`templates/list_punctuation.html`) explaining an editorial decision in the
building-code mapping: how the mapping punctuates a phrase that an amendment
inserts into an existing list. Two granularities — a one-line summary and a
fuller paragraph — plus a worked example, all cited to real provisions.

The rule this describes is implemented in CCM at
`src/chronicle_mapping/amendment/html/insert.py:708-723`. A per-provision
disclosure of each decision is specified in CCM `tasks/supplied-separator-note.md`;
until that ships, this page is the only place the convention is stated.

## What this page must not claim

The rule was built by chasing e-Laws parity — every non-peer guard in the code
is justified by an e-Laws witness. So the page cannot present divergence from
e-Laws as a principled goal. The honest framing separates two marks that sit
side by side in the output:

- **the separator joining the inserted phrase** — supplied by us; the amendment
  is silent; a convention, not a finding;
- **every other mark in the sentence, including a pre-existing serial comma** —
  as filed, left alone.

Earlier drafts of this copy blurred them and defended the first with the
justification that only applies to the second.

## Summary (one sentence)

> When an amendment adds a phrase to an existing list, the amending regulation
> almost never says how to punctuate the join, so the CodeChronicle mapping
> supplies that separator by a fixed convention — matching the separator the
> surrounding text already uses at the insertion point — and leaves every other
> mark in the sentence exactly as enacted.

## Detail (paragraph)

> The CodeChronicle mapping reconstructs each provision from the regulation as
> enacted and applies every amendment exactly as that amendment directs. But an
> amendment that inserts a phrase into a list — for example, *adding "a sewage
> system" after "plumbing system"* — directs the words and not the punctuation
> that joins them. Something has to be chosen, so the mapping chooses
> consistently: it matches the separator the surrounding text already uses at
> the insertion point, joining the new phrase with a comma where the neighbouring
> items are comma-separated, and with a plain space otherwise. The convention
> does not apply where the added text is not a list item — a parenthetical
> qualifier, a phrase led by *and* or *or*, or a subordinate clause beginning
> *as*, *where*, or *if*, each of which attaches to the preceding term rather
> than extending the list — and those attach with a space. This is a drafting
> convention, not a finding about the record: it is the one mark on the page the
> regulation did not put there. Everything around it is untouched, so where the
> list already carried a serial comma before its final *or*/*and*, that comma
> survives the insertion.

## Worked example

O. Reg. 22/98, s. 33 amends the definition of *building system* in Ontario
Building Code 1997, Article 11.1.1.2.

| | text |
|---|---|
| As enacted (O. Reg. 403/97) | …a plumbing system, or an electrical system. |
| Amendment directs | add *"a sewage system"* after *"plumbing system"* |
| CodeChronicle mapping | …a plumbing system, **a sewage system,** or an electrical system. |
| Ontario e-Laws consolidation | …a plumbing system, a sewage system **or** an electrical system. |

Two separate things are happening in that one line, and they are worth keeping
apart. The comma the mapping *supplied* is the one after *plumbing system* — the
join. The comma before *or* is the serial comma the 1997 regulation already
carried; the mapping leaves it, and the e-Laws consolidation drops it. Only the
second is a difference from e-Laws, and it is not the convention's doing.

## On the e-Laws divergence

The page should say that e-Laws re-punctuates lists in both directions, and cite
it, because an uncited swipe at the official source is worse than no sentence at
all. Witnesses, all curated in CCM's parity allowlist:

- **e-Laws drops a serial comma the filing has** — OBC 2006, 8.2.1.5.(1): O. Reg.
  350/06 files *"no Class 1, 2, or 3 sewage system"*; e-Laws renders *"Class 1, 2
  or 3"*. Also OBC 2006, 3.4.7.5.(3) (*"3.4.3.2., and 3.4.3.4."* → *"3.4.3.2. and
  3.4.3.4."*) and the Subsection 3.11.9. heading.
- **e-Laws adds a serial comma the print doesn't have** — OBC 1997, 2.7.2.1. and
  2.7.2.2.: print reads *"Parts 3, 5, 6, 7 and 9"*; e-Laws inserts one.
- **Both within a single provision** — OBC 1997, 1.1.3.2., where e-Laws adds and
  drops serial commas across the same definition list (print-verified against
  the 1997 gazette).

No amending regulation directs any of these. That is the whole point: they are
presentation choices at consolidation, which is exactly what the mapping's own
join convention is too — the difference being that ours is written down here.
