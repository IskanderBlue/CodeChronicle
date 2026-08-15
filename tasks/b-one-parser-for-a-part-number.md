# One parser for "which Part is this provision in"

## Goal

Read a provision's part number in one place. Two functions do it today, and
they disagree about one input.

## The two

**`core/views/regulation.py`**, `_leading_part`, groups the regulation-detail
page's clause targets:

```python
def _leading_part(provision_id: str) -> str:
    match = re.match(r"\d+", provision_id)
    return match.group(0) if match else ""
```

**`config/part_applicability.py`**, `part_of`, decides which applicability rule
governs a scored result:

```python
def part_of(provision_id: str) -> int | None:
    ...  # first dotted segment, and also reads a container id "Part 9"
```

Both read the leading numeric segment. `3.1.4.2.` is Part 3 to each of them,
and `11.2.1.1.` is Part 11 to each of them.

## Why this is not a two-minute change

**They disagree on a container id.** `_leading_part("Part 9")` returns `""`.
`part_of("Part 9")` returns `9`. A part-level row's own id has that shape, and
the regulation-detail page groups on the string `_leading_part` returns.

So making `_leading_part` call `part_of` changes how that page groups a
part-level target. That may be an improvement — a clause that amends `Part 9`
would join the Part 9 group instead of an empty one — but it is a behaviour
change in a page this work never touched, with its own tests.

Somebody has to decide what the regulation-detail page **should** do with a
container target before the two can share a parser.

## What to build

1. Decide the container question. Look at what `core.views.regulation` does
   with the empty string today, and whether any real clause target has that
   shape. `RegulationClause.resolved_provisions` is where to look.
2. Move the parser to one place. `config.part_applicability.part_of` is the
   better home: `config` has no Django imports, so a view can call it and the
   scorer can too.
3. Make `_leading_part` a thin adapter for the caller that wants a string, or
   change the caller to hold the integer.

## Done when

- One function reads a part number, and both callers use it.
- The regulation-detail page's grouping of a container target is a decision
  somebody wrote down, not an accident of two regular expressions.
- `core/tests/test_regulation_views.py` passes, with any changed expectation
  explained.

## Related

- `core/views/regulation.py`, `config/part_applicability.py`.
- `tasks/b-boost-parts-by-building-type.md` — the work that added the second
  parser.
