"""Rename the ElawsConsolidation model to Consolidation.

The "Elaws" prefix named the data *source* (e-Laws), not the model — the rows are
consolidations regardless of where they were built from. RenameModel updates the
Django state and FK references; AlterModelTable does the actual table rename (the
db_table was explicit, so RenameModel alone leaves it pinned); AlterField carries
the FK's new ``related_name`` (state only, no SQL). The unique-constraint and index
names keep their original identifiers — internal, invisible, not worth a churn.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0039_elawsconsolidation_effective_to_not_null"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="ElawsConsolidation",
            new_name="Consolidation",
        ),
        migrations.AlterModelTable(
            name="consolidation",
            table="consolidations",
        ),
        migrations.AlterField(
            model_name="consolidation",
            name="edition",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="consolidations",
                to="core.codeedition",
            ),
        ),
    ]
