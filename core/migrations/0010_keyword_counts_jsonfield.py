"""Replace keywords ArrayField with keyword_counts JSONField.

Three-step migration:
1. Add keyword_counts JSONField
2. (Data conversion — intentionally a no-op; see below)
3. Remove old keywords field and swap GIN index

Step 2 once back-filled ``keyword_counts`` from the old ``keywords`` list,
one CodeMapNode row at a time.  The whole CodeMapNode table is dropped in
0024, so that data is discarded a few migrations later — and on a populated
corpus (~250k nodes) the per-row loop turns a from-scratch ``migrate`` into a
multi-hour, cross-region stall before the app can even start.  Neutralised to
a no-op: the column still exists for 0011-0023 (which only need its schema,
not its contents), then 0024 removes the table entirely.  Final schema is
identical.
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_codemapnode_division"),
    ]

    operations = [
        # 1. Add the new JSONField
        migrations.AddField(
            model_name="codemapnode",
            name="keyword_counts",
            field=models.JSONField(
                blank=True,
                help_text='{"keyword": count} — term frequency per node',
                null=True,
            ),
        ),
        # 2. Data conversion — no-op: keyword_counts is dropped with the whole
        #    CodeMapNode table in 0024, so back-filling 250k rows here (a
        #    cross-region per-row loop) is pure waste that stalls migrate.
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
        # 3. Drop old GIN index on keywords ArrayField
        migrations.RemoveIndex(
            model_name="codemapnode",
            name="code_mapnode_keywords_gin",
        ),
        # 4. Remove old keywords field
        migrations.RemoveField(
            model_name="codemapnode",
            name="keywords",
        ),
        # 5. Add GIN index on keyword_counts JSONField
        migrations.AddIndex(
            model_name="codemapnode",
            index=GinIndex(fields=["keyword_counts"], name="code_mapnode_kwcounts_gin"),
        ),
    ]
