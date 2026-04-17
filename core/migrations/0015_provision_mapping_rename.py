"""Rename ProvisionEditionMapping → ProvisionMapping, add
introduced_by_version FK, and tighten the mapping_type / action
choices to match the unified ProvisionMapping contract.

Background: CCM emits a single top-level ``provision_mappings[]``
array in its consolidated edition JSON that covers both intra-edition
renumbers (driven by gazette directives) and cross-edition identity
changes.  CC's previous ``ProvisionEditionMapping`` model captured only
the cross-edition case; the rename removes the misleading "Edition" in
the name and adds the FK back to the version that introduced an
intra-edition mapping.

The table is empty in production today (CCM was emitting
``"edition_mappings": []``), so no data migration is needed — the
rename + add-field sequence is sufficient.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_rename_codeedition_system_to_code"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="ProvisionEditionMapping",
            new_name="ProvisionMapping",
        ),
        migrations.AlterModelTable(
            name="provisionmapping",
            table="provision_mappings",
        ),
        migrations.AddField(
            model_name="provisionmapping",
            name="introduced_by_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="introduced_mappings",
                to="core.codeeditionprovisionversion",
            ),
        ),
        migrations.AlterField(
            model_name="provisionmapping",
            name="mapping_type",
            field=models.CharField(
                choices=[
                    ("renumbered", "Renumbered"),
                    ("split", "Split"),
                    ("merged", "Merged"),
                    ("replaced", "Replaced"),
                ],
                max_length=20,
            ),
        ),
        # Add `renumber` to RegulationClause.action choices and
        # `renumbered` to CodeEditionProvisionVersion.action choices.
        # CCM emits both today; without these alterations Django's
        # choices validation would reject the values at ingest.
        migrations.AlterField(
            model_name="regulationclause",
            name="action",
            field=models.CharField(
                choices=[
                    ("revoke_and_substitute", "Revoke and substitute"),
                    ("amend_add", "Amend by adding"),
                    ("amend_strike_sub", "Amend by striking and substituting"),
                    ("revoke", "Revoke"),
                    ("renumber", "Renumber"),
                ],
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="codeeditionprovisionversion",
            name="action",
            field=models.CharField(
                choices=[
                    ("original", "Original"),
                    ("added", "Added"),
                    ("revoke_and_substitute", "Revoke and substitute"),
                    ("amend_add", "Amend by adding"),
                    ("amend_strike_sub", "Amend by striking and substituting"),
                    ("revoked", "Revoked"),
                    ("renumbered", "Renumbered"),
                ],
                default="original",
                max_length=50,
            ),
        ),
    ]
