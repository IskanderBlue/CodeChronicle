# Keyword TF-IDF Scoring — Implementation Plan

## Goal

Upgrade search ranking from equal-weight keyword matching to TF-IDF scoring. Rare, domain-specific terms (e.g., "sprinkler") should rank higher than ubiquitous terms (e.g., "building"). Sections that mention a term many times should rank higher than those mentioning it once.

## Current Behaviour

- `CodeMapNode.keywords` is an `ArrayField` (deduplicated list of strings) — no term frequency info.
- `engine.py` scores keyword matches as `len(matches) / len(query_terms)` — all keywords weighted equally.
- `config/keywords.py` contains ~7,800 entries including concatenated-phrase garbage (`abuildingbeingdemolishedfloor`) and common English stop words (`about`, `above`, `actually`).
- `scripts/extract_keywords.py` only processes `sections`, missing `tables` keywords entirely.

---

## Phase 1: Clean the Keyword Pipeline

### 1a. Fix `extract_keywords.py`

- Include `tables` in addition to `sections` when iterating map files.
- *(The rebuilt maps from CodeChronicleMapping will fix the concatenated-phrase garbage at source.)*

### 1b. Filter `VALID_KEYWORDS` to Domain-Meaningful Terms

Three-pass filter applied after extraction:

1. **Stop word removal** — Remove common English words using NLTK/spaCy stop word list. Cuts ~30-40% of entries.
2. **Document frequency ceiling** — After Phase 2 lands, drop any keyword appearing in >X% of nodes (tune X; start at 80%). These have no discriminative value and IDF would near-zero them anyway.
3. **LLM batch filter** — Send remaining keywords in batches to an LLM: *"Which of these are meaningful building code domain terms?"* One-time cost, produces a curated ~1,500-2,000 term list.

Output: a cleaned `VALID_KEYWORDS` for the LLM constraint list, plus a foundation for meaningful IDF computation.

---

## Phase 2: Store Keyword Counts (TF)

### 2a. Migration — Change `keywords` field

Change `CodeMapNode.keywords` from `ArrayField` to `JSONField`:

```python
# core/models.py
class CodeMapNode(models.Model):
    # Before: keywords = ArrayField(models.CharField(max_length=100), null=True, blank=True)
    # After:
    keyword_counts = models.JSONField(
        null=True, blank=True,
        help_text='{"keyword": count} — term frequency per node',
    )
```

Migration should convert existing data:

```python
# In the migration's RunPython
from django.db import migrations

def convert_keywords_to_counts(apps, schema_editor):
    CodeMapNode = apps.get_model('core', 'CodeMapNode')
    for node in CodeMapNode.objects.filter(keywords__isnull=False).iterator(chunk_size=500):
        node.keyword_counts = {kw: 1 for kw in node.keywords}  # existing data is deduplicated, so count=1
        node.save(update_fields=['keyword_counts'])
```

Note: the GIN index on `ArrayField` must be dropped; add a GIN index on `keyword_counts` instead for `jsonb` containment queries.

### 2b. Update `load_maps.py`

Change keyword loading to accumulate counts instead of deduplicating into a set:

```python
# When loading from map JSON:
raw_keywords = section.get("keywords", [])
keyword_counts: dict[str, int] = {}
for kw in raw_keywords:
    if isinstance(kw, str):
        key = kw.lower()
        keyword_counts[key] = keyword_counts.get(key, 0) + 1

# When merging duplicate node_ids:
existing_counts = existing.keyword_counts or {}
for kw, ct in keyword_counts.items():
    existing_counts[kw] = existing_counts.get(kw, 0) + ct
existing.keyword_counts = existing_counts
```

### 2c. Update `extract_keywords.py`

Iterate both `sections` and `tables`. Extract keys from `keyword_counts` dicts (or raw `keywords` lists from map JSON).

---

## Phase 3: Materialized View for IDF

Instead of a separate `KeywordFrequency` model, use a PostgreSQL materialized view. This keeps IDF as derived data with no extra Django model to maintain.

### 3a. Create the Materialized View

Raw SQL migration:

```sql
CREATE MATERIALIZED VIEW keyword_idf AS
SELECT
    cm.map_code,
    kw.key                                          AS keyword,
    COUNT(DISTINCT cmn.id)                          AS doc_count,
    (SELECT COUNT(*) FROM code_map_nodes cmn2
     WHERE cmn2.code_map_id = cm.id)                AS total_docs,
    LN((SELECT COUNT(*) FROM code_map_nodes cmn2
        WHERE cmn2.code_map_id = cm.id)::float
       / GREATEST(COUNT(DISTINCT cmn.id), 1)) + 1  AS idf
FROM code_maps cm
JOIN code_map_nodes cmn ON cmn.code_map_id = cm.id,
     LATERAL jsonb_each_text(cmn.keyword_counts) AS kw(key, value)
GROUP BY cm.id, cm.map_code, kw.key;

CREATE UNIQUE INDEX keyword_idf_lookup
    ON keyword_idf (map_code, keyword);
```

### 3b. Unmanaged Django Model for ORM Access

```python
# core/models.py
class KeywordIDF(models.Model):
    map_code = models.CharField(max_length=50, primary_key=True)
    keyword = models.CharField(max_length=100)
    doc_count = models.IntegerField()
    total_docs = models.IntegerField()
    idf = models.FloatField()

    class Meta:
        managed = False
        db_table = 'keyword_idf'
```

### 3c. Refresh After Map Loads

Add to the end of `load_maps` management command (or chain a separate command):

```python
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY keyword_idf;")
```

`CONCURRENTLY` requires the unique index (created above) and avoids locking reads during refresh.

---

## Phase 4: TF-IDF Scoring in `engine.py`

### 4a. Load IDF Weights at Search Time

At the start of `_search_code_db`, fetch IDF values for the query terms:

```python
from math import log
from core.models import KeywordIDF

idf_rows = KeywordIDF.objects.filter(
    map_code=map_code, keyword__in=list(expanded_terms)
)
idf_map: dict[str, float] = {row.keyword: row.idf for row in idf_rows}

def get_idf(term: str) -> float:
    return idf_map.get(term, 1.0)  # unknown term gets neutral weight
```

### 4b. Change `keyword_counts` Lookup

Update the candidate loop to read from `keyword_counts` (JSONField) instead of `keywords` (ArrayField):

```python
# Before:
keywords = set(kw.lower() for kw in (node.keywords or []))

# After:
kw_counts: dict[str, int] = node.keyword_counts or {}
keywords = set(kw_counts.keys())
```

### 4c. Replace Equal-Weight Scoring with TF-IDF

```python
# Before (L134):
score = len(original_matches) / len(query_terms)

# After — TF-IDF:
def tf(term: str, counts: dict[str, int]) -> float:
    """Log-normalized term frequency."""
    raw = counts.get(term, 0)
    return (1 + log(raw)) if raw > 0 else 0.0

score = (
    sum(tf(t, kw_counts) * get_idf(t) for t in original_matches)
    / sum(get_idf(t) for t in query_terms)
)
match_type = "exact"
```

Same pattern for synonym matches (currently L137):
```python
score = (
    sum(tf(t, kw_counts) * get_idf(t) for t in matches)
    / sum(get_idf(t) for t in expanded_terms)
) * 0.9
match_type = "synonym"
```

This preserves the 0–1ish score range (ratio of weighted matches to weighted total) while boosting sections that mention rare terms frequently.

### 4d. Update Query Filtering

The DB-level candidate filter changes from `ArrayField` overlap to `JSONField` key containment:

```python
# Before:
criteria |= Q(keywords__overlap=list(expanded_terms))

# After — check if any query term is a key in the JSONB:
for term in expanded_terms:
    criteria |= Q(keyword_counts__has_key=term)
```

Note: `has_key` uses the GIN index on `keyword_counts`.

### 4e. Optional: Cache IDF per Map Code

If search latency is a concern, cache the `idf_map` dict per `map_code` using Django's cache framework. Invalidate on `REFRESH MATERIALIZED VIEW` (i.e., after `load_maps`).

```python
from django.core.cache import cache

CACHE_KEY = f"idf_map:{map_code}"
idf_map = cache.get(CACHE_KEY)
if idf_map is None:
    idf_rows = KeywordIDF.objects.filter(
        map_code=map_code, keyword__in=list(expanded_terms)
    )
    idf_map = {row.keyword: row.idf for row in idf_rows}
    cache.set(CACHE_KEY, idf_map, timeout=3600)
```

---

## Phase 5: Tests

- **`test_keyword_counts_migration`**: Load a small map, verify `keyword_counts` is a dict with correct counts.
- **`test_matview_refresh`**: Load maps, refresh matview, assert `KeywordIDF` rows exist with expected `doc_count` and `idf` values.
- **`test_tfidf_scoring`**: Two sections — one with `{"fire": 1, "building": 10}`, one with `{"fire": 8, "sprinkler": 3}`. Query "fire sprinkler" should rank the second higher.
- **`test_empty_idf_fallback`**: Graceful fallback when matview is empty (score reverts to equal-weight via `get_idf` returning 1.0).
- **`test_keyword_filter_pipeline`**: Verify stop words, high-frequency terms, and garbage keywords are excluded from `VALID_KEYWORDS`.

---

## Phase 6: Migration & Deploy Sequence

1. `makemigrations` for `keyword_counts` JSONField + drop old `keywords` ArrayField.
2. Data migration to convert existing `keywords` lists to `{kw: 1}` dicts.
3. SQL migration to create `keyword_idf` materialized view + unique index.
4. `migrate` on deploy.
5. Run `load_maps` (populates `keyword_counts` from rebuilt map JSON).
6. `REFRESH MATERIALIZED VIEW CONCURRENTLY keyword_idf;` (automated at end of `load_maps`).
7. No breaking changes — search API response shape is unchanged.

---

## Risk / Notes

- Materialized view is derived data; can always be rebuilt from `keyword_counts` via `REFRESH`.
- No impact on NBC copyright — only storing keyword counts, not code text.
- `VALID_KEYWORDS` in `config/keywords.py` remains the LLM constraint list; cleaned separately in Phase 1.
- The `keywords__overlap` GIN query must be updated to `keyword_counts__has_key` everywhere it appears.
- `_suggest_similar_keywords()` in `engine.py` iterates `node.keywords` — must update to iterate `node.keyword_counts.keys()`.
- Score normalization: TF-IDF scores are still ratios (weighted match / weighted total) so they stay in a comparable range to the current 0–1 scores. Section-ref and exact-ID matches (scored 1.5–2.5) remain unaffected.
- `REFRESH MATERIALIZED VIEW CONCURRENTLY` requires PostgreSQL 9.4+ and a unique index (provided).
