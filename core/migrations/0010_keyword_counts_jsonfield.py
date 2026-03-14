"""Replace keywords ArrayField with keyword_counts JSONField.

Three-step migration:
1. Add keyword_counts JSONField
2. Convert existing keywords lists to {kw: 1} dicts
3. Remove old keywords field and swap GIN index
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import migrations, models


def convert_keywords_to_counts(apps, schema_editor):
    CodeMapNode = apps.get_model("core", "CodeMapNode")
    for node in CodeMapNode.objects.filter(keywords__isnull=False).iterator(chunk_size=500):
        node.keyword_counts = {kw: 1 for kw in node.keywords}
        node.save(update_fields=["keyword_counts"])


def convert_counts_to_keywords(apps, schema_editor):
    CodeMapNode = apps.get_model("core", "CodeMapNode")
    for node in CodeMapNode.objects.filter(keyword_counts__isnull=False).iterator(chunk_size=500):
        node.keywords = sorted(node.keyword_counts.keys())
        node.save(update_fields=["keywords"])


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
        # 2. Migrate data: keywords list -> keyword_counts dict
        migrations.RunPython(convert_keywords_to_counts, convert_counts_to_keywords),
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
