"""Rename CodeEdition.system → CodeEdition.code FK field.

Also updates the unique constraint and index names.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_provenance_models"),
    ]

    operations = [
        # Drop old constraint and index (they reference the old field name)
        migrations.RemoveConstraint(
            model_name="codeedition",
            name="code_system_edition_unique",
        ),
        migrations.RemoveIndex(
            model_name="codeedition",
            name="code_edition_effective_idx",
        ),
        # Rename the field
        migrations.RenameField(
            model_name="codeedition",
            old_name="system",
            new_name="code",
        ),
        # Recreate constraint and index with new field name
        migrations.AddConstraint(
            model_name="codeedition",
            constraint=models.UniqueConstraint(
                fields=["code", "edition_id"],
                name="code_edition_code_edition_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="codeedition",
            index=models.Index(
                fields=["code", "effective_date"],
                name="code_edition_effective_idx",
            ),
        ),
    ]
