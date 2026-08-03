# History links must carry the AS-OF date

> History doesn't seem to use the date picker. Must be fixed

**Status: fixed 2026-08-03.**

## What was wrong

`templates/history.html` linked each entry as `?q=` and nothing else. The
AS-OF picker overrides whatever the parser reads out of the query text, so a
link with only the words re-ran the same question at the **default** date.

The failure was silent. The page returned a different edition's text under the
same question, and it did so under the date the same card displays in a chip
two lines below the link. On a product whose claim is "as it read on that
date", that is the worst shape a bug can take.

## Why it was one line

Nothing was missing from the data. `services/search_service.py:142` writes the
picker's date into the params **before** the row is stored:

```python
params["date"] = date_override
```

So `parsed_params["date"]` is the date the search really ran at, already in
the ISO form `?d=` parses. The receiving half was already built and validated
(`core/views/search.py:134`). Only the link was short.

## What changed

- `templates/history.html` — the link now carries
  `&d={{ item.parsed_params.date }}`, guarded by an `if`. A row with no stored
  date links with the words alone rather than sending an empty parameter.
- `core/tests/test_history.py` — new file, five tests. Four cover the link;
  the fifth follows it and asserts the search page seeds `initial_date`,
  because the two ends live in different files and only the round trip proves
  they agree.

## Notes

- The province needs no parameter. It is force-set to `ON`, which is why every
  stored row reads `'ON'`.
- The `urlencode` filter percent-encodes a space. It does not use `+`.
- Match the link with a pattern when you test it. A bare `d=` also matches the
  SVG path attributes the page is full of.
