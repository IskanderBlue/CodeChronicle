"""Create keyword_idf materialized view for IDF scoring.

Computes inverse document frequency per keyword per map_code corpus.
Refreshed after load_maps via REFRESH MATERIALIZED VIEW CONCURRENTLY.
"""

from django.db import migrations

CREATE_MATVIEW = """
CREATE MATERIALIZED VIEW IF NOT EXISTS keyword_idf AS
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

CREATE UNIQUE INDEX IF NOT EXISTS keyword_idf_lookup
    ON keyword_idf (map_code, keyword);
"""

DROP_MATVIEW = """
DROP MATERIALIZED VIEW IF EXISTS keyword_idf;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_keyword_counts_jsonfield"),
    ]

    operations = [
        migrations.RunSQL(CREATE_MATVIEW, DROP_MATVIEW),
    ]
