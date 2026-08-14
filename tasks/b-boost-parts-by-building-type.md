# Boost the part the reader is actually in

## Goal

Use the kind of building in the query to rank one part of the code above
another. A reader who asks about a house wants Part 9. A reader who asks
about an office tower wants Part 3. Today the search treats every part alike.

## Why this card exists

`tasks/complete/keywords-from-the-query-first.md` deleted the `building_type`
field from the LLM parser on 14 August 2026. That field was inert — no code
read it — and the model mirrored its value into the scored keyword list, where
it did harm.

The idea behind the field was right. The delivery was wrong. A building type
is a property of the reader's project. It is not a word the provision text
contains, so it must never be a scored term. It belongs on the *ranking*, as
a hint about which part of the code to prefer.

## The structure it would use

Division B of OBC 2012 holds these parts:

| Part | Title |
|---|---|
| 1 | General |
| 3 | Fire Protection, Occupant Safety and Accessibility |
| 4 | Structural Design |
| 5 | Environmental Separation |
| 6 | Heating, Ventilating and Air-Conditioning |
| 7 | Plumbing |
| 8 | Sewage Systems |
| 9 | Housing and Small Buildings |
| 10 | Change of Use |
| 11 | Renovation |
| 12 | Resource Conservation and Environmental Integrity |

Part 9 and Part 3 are the pair that matters most. **The split is by size and
occupancy, not by "residential" against "commercial".** Part 9 is "Housing and
Small Buildings"; a small apartment building is in Part 9, and a large
residential tower is in Part 3. Do not write the rule as residential against
commercial, because that is not what the code does.

The guard-height article measures what is left to win. Asking
`guard height for a stair in a house` at 1 June 2008 now answers
`9.8.8.3. Height of Guards` first, but `3.4.6.5. Guards` — Part 3, exit stairs
in a large building — is **second**, above `9.8.8.1. Required Guards`, which is
the Part 9 provision that says when the reader needs a guard at all. Six of the
top 20 are Part 3. A house is not governed by any of them here.

The Part 3 title wins on shortness: `Guards` is one word, and the BM25F title
field rewards a match that fills the field. Nothing in the score knows which
part the reader is in.

## Open questions

These need answers before anybody writes code.

1. **Where does the signal come from?** The query text, an explicit control,
   or both. An explicit control is honest and costs the reader a click; a
   derived signal is invisible and can be wrong.
2. **How strong is the boost?** A multiplier on the score, a tie-break, or a
   filter. A filter is dangerous: a house *does* use Part 3 provisions
   through cross-references.
3. **Does the part number mean the same thing in every edition?** Check
   OBC 1997, 2006, 2012 and 2024 before assuming Part 9 is Part 9 throughout.
   The article already found the article number moving between editions.
4. **What about Division A and Division C?** Definitions live in Division A
   1.4.1.2., and a reader asking what a word means needs them.

## Rules

- **A building type is never a scored keyword.** That is the mistake this card
  exists to avoid repeating.
- **Nothing becomes unreachable.** A boost changes an order. A filter removes
  an answer, and a house can be governed by a Part 3 provision.
- **Measure it on real queries.** The guard-height query above is one test
  case. Collect more from `SearchHistory` before and after.

## Done when

- A query about a house ranks Part 9 provisions above their Part 3
  counterparts, for the same words.
- No provision becomes unreachable.
- The measurement is recorded here, before and after.

## Related

- `tasks/complete/keywords-from-the-query-first.md` — removed `building_type`.
  It has landed, so this card is unblocked.
- `api/search/engine.py` — BM25F, and `BM25F_TITLE_WEIGHT`, which is what
  currently lets a short Part 3 title win.
