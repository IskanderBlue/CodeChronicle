# Keyword vocabulary: drop the dead `" " in kw` branch; reconcile the hyphen policy

The searchable-keyword vocabulary is built by `scripts/extract_keywords.py` from
every edition's per-version `keyword_counts`, and queried through an exact
JSONB key match. One line in that build is **defensive dead code** that
misrepresents how the filter actually behaves, and the real behaviour it hides
has a coverage cost worth a deliberate decision.

## The dead branch

`scripts/extract_keywords.py:55`

```python
filtered_keywords = sorted([kw for kw in keywords if kw.isalpha() or " " in kw])
```

The `" " in kw` disjunct keeps any keyword containing a space. **No CCM keyword
ever contains a space.** The producer's tokenizer
(`Canada_building_code_mcp`-modelled `extract_keyword_counts` in the CCM repo,
`src/chronicle_mapping/shared/keywords.py`) splits on every non-`[a-z0-9-]`
character, so a phrase like "fire resistance rating" is emitted as three
single-word keys — never one phrase key. Verified against a shipped edition:
across `OBC_1997.json` (3,382 versions, 7,257 distinct keys), **zero** keys
contain a space.

So the `" " in kw` branch never fires. Its harm is not a bug — it's that it
**throws off anyone reading the filter**: the code reads as "we keep multiword
phrase keys," implying phrase search exists, when in fact the only operative
clause is `.isalpha()`. Delete the disjunct (or, if space-joined keys are a
genuine future intent, add a comment + a test that actually exercises it — but
today it is inert).

## The real behaviour it hides: `.isalpha()` drops every hyphenated key

With `" " in kw` inert, the effective filter is `kw.isalpha()`. That drops
**every hyphenated key** from the searchable vocabulary. In `OBC_1997.json`
that was **791 of 7,257 distinct keys (~11%)** — and not just noise: standard
designations (`a101-m`, a CSA/ASTM number), appendix references (`a-1`), and,
before the producer fix below, species compounds (`spruce-pine-fir`). These
ship in `keyword_counts` but are unreachable through the keyword channel:

- **Filter is exact-key, not substring.** `api/search/engine.py:242`
  `Q(keyword_counts__has_key=term)` — a query `"spruce"` never matches a stored
  key `"spruce-pine-fir"`.
- **The compound can't be a query term either.** It's dropped from
  `VALID_KEYWORDS`, and `api/llm_parser.py:263` constrains query keywords to
  that list, so the parser can't emit it.

Net: a hyphenated stored key is reachable only via the `rapidfuzz` fuzzy
fallback (`api/search/engine.py:336`), not BM25/`has_key`.

## Coordinated producer-side change (CCM, landed)

CCM now splits hyphenated compounds into their component words in
`extract_keyword_counts` (`shared/keywords.py`, `_split_hyphenated`): a dash is
a token boundary for search, so `spruce-pine-fir` → `spruce`, `pine`, `fir`
(all alphabetic, all indexable). Objective codes (`F03-OS1.2`, encoded
`f03-os1-dot-2`) stay whole — their internal hyphen is part of the identifier.

After CCM editions are reassembled, the residual hyphenated keys reaching CC
will be a small set: objective codes (`f03-os1.2`) and any alphanumeric
standard refs. **CC still drops all of them via `.isalpha()`.** Whether those
precise identifiers should be searchable is CC's call — they're exactly the
kind of term a professional user types.

## The fix (CC side)

1. **Remove the moot `" " in kw` disjunct** in `scripts/extract_keywords.py:55`
   so the filter states what it does.
2. **Decide the hyphen policy for the residual keys** (objective codes,
   standard refs). Options: (a) keep dropping them (accept they're
   fuzzy-only); (b) admit hyphenated-but-otherwise-wordlike keys into
   `VALID_KEYWORDS` and let `has_key` match them exactly (a user typing
   `F03-OS1.2` or `A101-M` then hits directly). Pick one deliberately rather
   than inheriting it from an `.isalpha()` side effect.
3. Add a test that pins whichever policy is chosen, so the intent is legible in
   code rather than emergent from a filter expression.

Context: surfaced 2026-07-07 during CCM OBC-1997 parity work (the
`spruce-pine-fir` keyword divergence between the e-Laws and PDF paths). The
CCM-side producer split is the paired change.

## Decision (2026-07-23, Iskander)

Option (b): hyphenated-but-otherwise-wordlike keys (objective codes,
standard refs like `A101-M`) ARE admitted into VALID_KEYWORDS and match
via has_key exactly. Implement by replacing the `.isalpha()` filter with
one that also accepts hyphenated keys, drop the dead `" " in kw` disjunct,
and pin the policy with a test.
