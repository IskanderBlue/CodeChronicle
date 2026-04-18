"""Add ``html`` field to ProvisionVersionTable.

Stores structured table markup sourced from e-Laws (or another
consolidated HTML publication) when a point-in-time form is available
for that version.  When empty, the renderer falls back to ``images``.
See ``tasks/provenance/4-display.md`` for the per-version render rule.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_provision_mapping_rename"),
    ]

    operations = [
        migrations.AddField(
            model_name="provisionversiontable",
            name="html",
            field=models.TextField(blank=True, default=""),
        ),
    ]
