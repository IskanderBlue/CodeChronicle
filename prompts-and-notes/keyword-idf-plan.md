# Keyword IDF Weighting — Implementation Plan

## Goal

Weight keyword matches by rarity (inverse document frequency) so that specific terms like "sprinkler" rank higher than ubiquitous terms like "building". Works universally across OBC (full text) and NBC (coordinate index only).

## Current Behaviour

- `engine.py` scores exact keyword matches as `len(matches) / len(query_terms)` — all keywords weighted equally.
- Common keywords dilute ranking; a section matching "fire" + "building" scores the same as one matching "fire" + "sprinkler".

---

## Step 1: Model — `KeywordFrequency`

Add a new model in `core/models.py`:

```python
class KeywordFrequency(models.Model):
    keyword = models.CharField(max_length=100)
    map_code = models.CharField(max_length=50)
    doc_count = models.IntegerField(default=0)  # number of CodeMapNodes containing this keyword

    class Meta:
        db_table = 'keyword_frequencies'
        constraints = [
            models.UniqueConstraint(fields=['keyword', 'map_code'], name='kw_freq_unique'),
        ]
        indexes = [
            models.Index(fields=['map_code', 'keyword'], name='kw_freq_lookup_idx'),
        ]
```

- One row per (keyword, map_code) pair.
- `doc_count` = how many `CodeMapNode` rows in that map contain the keyword.

## Step 2: Management Command — `build_keyword_frequencies`

New command `core/management/commands/build_keyword_frequencies.py`:

1. Truncate `keyword_frequencies` table.
2. For each `CodeMap`, iterate all `CodeMapNode.keywords` arrays.
3. Count occurrences per keyword, bulk-insert into `KeywordFrequency`.
4. Run after `load_maps` (add a note to `load_maps` or chain them).

Pseudocode:
```python
for code_map in CodeMap.objects.all():
    counts: dict[str, int] = defaultdict(int)
    for keywords in CodeMapNode.objects.filter(code_map=code_map).values_list('keywords', flat=True):
        for kw in set(keywords or []):  # set() to count per-doc, not per-occurrence
            counts[kw.lower()] += 1
    KeywordFrequency.objects.bulk_create([
        KeywordFrequency(keyword=kw, map_code=code_map.map_code, doc_count=ct)
        for kw, ct in counts.items()
    ])
```

## Step 3: Scoring Update — `engine.py`

### 3a. Load IDF weights at search time

At the start of `_search_code_db`, fetch frequencies for the query terms:

```python
from math import log

total_docs = CodeMapNode.objects.filter(code_map__map_code=map_code).count()
freq_map = dict(
    KeywordFrequency.objects.filter(
        map_code=map_code, keyword__in=list(expanded_terms)
    ).values_list('keyword', 'doc_count')
)

def idf(term: str) -> float:
    dc = freq_map.get(term, 0)
    if dc == 0:
        return 1.0  # unknown term gets neutral weight
    return log(total_docs / dc) + 1  # standard IDF with +1 smoothing
```

### 3b. Replace equal-weight scoring

Current (L130-134):
```python
score = len(original_matches) / len(query_terms)
```

New:
```python
score = sum(idf(t) for t in original_matches) / sum(idf(t) for t in query_terms)
```

Same change for synonym matches (L137):
```python
score = (sum(idf(t) for t in matches) / sum(idf(t) for t in expanded_terms)) * 0.9
```

This preserves the 0–1 score range (ratio of weighted matches to weighted total) while boosting rare-term matches.

## Step 4: Cache IDF in Memory (Optional Optimisation)

If search latency is a concern, cache the frequency dict per map_code at module level or via Django's cache framework. The data only changes on `load_maps`, so invalidation is straightforward — clear on command run.

## Step 5: Tests

- `test_keyword_frequency_build`: Load a small map, run command, assert counts.
- `test_idf_scoring`: Two sections — one with "fire" + "building", one with "fire" + "sprinkler". Query "fire sprinkler" should rank the second higher.
- `test_empty_frequencies`: Graceful fallback when `KeywordFrequency` table is empty (score reverts to equal-weight).

## Step 6: Migration & Deploy

1. `makemigrations` → new migration for `KeywordFrequency`.
2. `migrate` on deploy.
3. Run `build_keyword_frequencies` after `load_maps` in deploy script.
4. No breaking changes — search API response shape is unchanged.

---

## Risk / Notes

- IDF table is derived data; can always be rebuilt from `CodeMapNode.keywords`.
- No impact on NBC copyright — we're only counting keywords, not storing code text.
- `VALID_KEYWORDS` list in `config/keywords.py` is unaffected; it remains the LLM constraint list.
- Consider filtering out ultra-common stop-word-like keywords (e.g., "the", "and") from `VALID_KEYWORDS` separately — IDF will naturally down-weight them, but removing them saves LLM token budget.
