# One parser for "which Part is this provision in"

**Done on 16 August 2026.** The blocking question answered itself in the
data. No output changed. See "What the corpus said".

## The result

`config.part_applicability.part_of` is the one parser of a part number, and
the only one. `core.views.regulation._leading_part` is **gone**, not wrapped:
`_group_provisions` now holds the part as an `int | None` and calls `part_of`
directly.

An adapter was the card's own fallback ("a thin adapter for the caller that
wants a string"), and it would have left two functions where the card asked
for one. The caller did not want a string. It bucketed on the string, then
converted it back with `int(part) if part.isdigit()` to sort, and read it as
falsy to mean "no Part" — a round trip through a form nothing needed.
`_APPENDIX_TABLE_PART` is now `9` rather than `"9"` for the same reason.

`part_of` reads **two vocabularies**, which is what the card could not decide
about:

| Source | A part-level id looks like |
|---|---|
| `CodeEditionProvision.provision_id` | `Part 9` |
| `RegulationClause.target_id` | `9` — bare, because `target_level` sits beside it |

## What the corpus said

The card asked somebody to decide what the regulation-detail page should do
with a container target such as `Part 9`. There is no such target. All four
part-level clause targets in the corpus store the bare number, which
the old regular expression already read correctly. So the two functions never disagreed
on a real id, and the decision was not needed.

**Nothing this page renders changed.** The parser had one caller,
`_group_provisions`, fed from `Regulation.commencement[*].resolved_provisions`
— not from `RegulationClause.target_id`. Measured over that real input: 1,177
references, 704 distinct ids, **zero** disagreements. Measured again on the
finished grouping, over all 89 commencement rows in the corpus: every group
label, and the order of every provision and table inside it, is identical. The
search side is unchanged too — no provision id lost its part.

## Two hardening edits, and their honest status

`part_of` is now shared, so it was widened for id shapes the *other*
vocabulary holds. Neither shape reaches a caller today. They are recorded here
so nobody later reads them as bug fixes:

- **`2(2)` and `3(20)`** — a subsection with a sentence, and no dot. `part_of`
  returned `None`, because it required the whole first segment to be digits.
  It now takes the leading digits of that segment, so these read as Part 2 and
  Part 3.
- **`350/06`, `332/12`, `403/97`** — regulation citations, carried at
  `target_level="regulation"`. Their leading digits are not a part number, so
  `part_of` refuses an id whose first segment holds a `/`.

The `/` test is on the first segment alone. Applied to the whole id it also
rejected `11.5.1.1.D/E.`, a real Part 11 table with a slash in a later
segment, and took the part away from every row of it. That near miss is
`test_a_slash_deeper_in_the_id_is_not_a_citation`.

## Done when

- [x] One function reads a part number, and both callers use it.
- [x] The regulation-detail page's grouping of a container target is a
  decision somebody wrote down. The decision is that the case does not arise;
  the data is quoted above.
- [x] `core/tests/test_regulation_views.py` passes, with any changed
  expectation explained. No expectation changed, because no rendered output
  changed. `TestPartOfReadsBothVocabularies` in
  `api/tests/test_part_applicability.py` covers the three widened shapes.

## Related

- `config/part_applicability.py`, `core/views/regulation.py`.
- `tasks/complete/boost-parts-by-building-type.md` — the work that added the
  second parser.
- `_APPENDIX_TABLE_PART` in `core/views/regulation.py` stays where it is. It
  is not a parser: appendix tables carry no part in their id at all, and the
  constant records that in the OBC they are all Part 9 housing tables.
