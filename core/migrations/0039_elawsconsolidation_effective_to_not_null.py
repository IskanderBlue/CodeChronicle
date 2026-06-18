"""Make ``ElawsConsolidation.effective_to`` NOT NULL (verification-coverage decision 4).

NULL previously meant "the live consolidation, open-ended". We replace that with a
zero-range point ``[effective_from, effective_from]``: the current consolidation is
attested at its instant with no forward promise, so a date past it falls into the
reconstruction-only tail rather than being silently "covered". Backfill the existing
live rows before tightening the column.
"""

from django.db import migrations, models
from django.db.models import F


def backfill_live_rows(apps, schema_editor):
    ElawsConsolidation = apps.get_model("core", "ElawsConsolidation")
    ElawsConsolidation.objects.filter(effective_to__isnull=True).update(
        effective_to=F("effective_from")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_termsacceptance"),
    ]

    operations = [
        migrations.RunPython(backfill_live_rows, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="elawsconsolidation",
            name="effective_to",
            field=models.DateField(),
        ),
    ]
