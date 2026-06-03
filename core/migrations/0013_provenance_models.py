"""Create provenance models: Regulation, RegulationClause,
CodeEditionProvision, CodeEditionProvisionVersion,
ProvisionVersionTable, ProvisionEditionMapping.

Also adds CodeEdition.ineffective_date and amendment_chain_complete.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_rename_codesystem_to_code"),
    ]

    operations = [
        # --- CodeEdition new fields ---
        migrations.AddField(
            model_name="codeedition",
            name="ineffective_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="codeedition",
            name="amendment_chain_complete",
            field=models.BooleanField(default=False),
        ),
        # --- Regulation ---
        migrations.CreateModel(
            name="Regulation",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("reg_id", models.CharField(max_length=50, unique=True)),
                ("role", models.CharField(
                    choices=[("base", "Base"), ("amendment", "Amendment")],
                    max_length=20,
                )),
                ("filed_date", models.DateField(blank=True, null=True)),
                ("effective_date", models.DateField()),
                ("source_pdf", models.CharField(blank=True, default="", max_length=200)),
                ("source_pages", models.JSONField(blank=True, null=True)),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="regulations",
                        to="core.codeedition",
                    ),
                ),
                (
                    "amends",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="amended_by",
                        to="core.regulation",
                    ),
                ),
            ],
            options={
                "db_table": "regulations",
            },
        ),
        migrations.AddIndex(
            model_name="regulation",
            index=models.Index(
                fields=["edition", "effective_date"],
                name="regulations_edition__c7e8a1_idx",
            ),
        ),
        # --- RegulationClause ---
        migrations.CreateModel(
            name="RegulationClause",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("clause_id", models.CharField(max_length=50)),
                ("parent_clause", models.CharField(blank=True, default="", max_length=50)),
                ("action", models.CharField(
                    choices=[
                        ("revoke_and_substitute", "Revoke and substitute"),
                        ("amend_add", "Amend by adding"),
                        ("amend_strike_sub", "Amend by striking and substituting"),
                        ("revoke", "Revoke"),
                    ],
                    max_length=50,
                )),
                ("target_level", models.CharField(
                    blank=True,
                    choices=[
                        ("article", "Article"),
                        ("sentence", "Sentence"),
                        ("clause", "Clause"),
                        ("subclause", "Subclause"),
                        ("subsection", "Subsection"),
                        ("section", "Section"),
                        ("part", "Part"),
                        ("table", "Table"),
                    ],
                    default="",
                    max_length=50,
                )),
                ("target_id", models.CharField(blank=True, default="", max_length=200)),
                ("clause_text", models.TextField(blank=True, default="")),
                ("strike_text", models.TextField(blank=True, null=True)),
                ("sub_text", models.TextField(blank=True, null=True)),
                ("page", models.IntegerField(blank=True, null=True)),
                ("bbox", models.JSONField(blank=True, null=True)),
                ("overlay", models.JSONField(blank=True, null=True)),
                (
                    "regulation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="clauses",
                        to="core.regulation",
                    ),
                ),
            ],
            options={
                "db_table": "regulation_clauses",
            },
        ),
        migrations.AddIndex(
            model_name="regulationclause",
            index=models.Index(
                fields=["regulation"],
                name="regulation_c_regulat_b3e1a2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="regulationclause",
            index=models.Index(
                fields=["target_id"],
                name="regulation_c_target__a9f3b1_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="regulationclause",
            constraint=models.UniqueConstraint(
                fields=("regulation", "clause_id"),
                name="clause_regulation_clause_id_unique",
            ),
        ),
        # --- CodeEditionProvision ---
        migrations.CreateModel(
            name="CodeEditionProvision",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("provision_id", models.CharField(max_length=200)),
                ("level", models.CharField(
                    choices=[
                        ("division", "Division"),
                        ("part", "Part"),
                        ("section", "Section"),
                        ("subsection", "Subsection"),
                        ("article", "Article"),
                        ("sentence", "Sentence"),
                        ("clause", "Clause"),
                    ],
                    max_length=20,
                )),
                ("division", models.CharField(blank=True, default="", max_length=50)),
                ("version_count", models.PositiveSmallIntegerField(default=1)),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="provisions",
                        to="core.codeedition",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="core.codeeditionprovision",
                    ),
                ),
                (
                    "appendix_of",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="appendix_entries",
                        to="core.codeeditionprovision",
                    ),
                ),
            ],
            options={
                "db_table": "code_edition_provisions",
            },
        ),
        migrations.AddIndex(
            model_name="codeeditionprovision",
            index=models.Index(
                fields=["edition", "division", "provision_id"],
                name="code_editio_edition_a2b4c1_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="codeeditionprovision",
            index=models.Index(
                fields=["parent"],
                name="code_editio_parent__d1e5f2_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="codeeditionprovision",
            constraint=models.UniqueConstraint(
                fields=("edition", "provision_id", "division"),
                name="provision_edition_id_division_unique",
            ),
        ),
        # --- CodeEditionProvisionVersion ---
        migrations.CreateModel(
            name="CodeEditionProvisionVersion",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("version", models.PositiveSmallIntegerField(default=0)),
                ("action", models.CharField(
                    choices=[
                        ("original", "Original"),
                        ("added", "Added"),
                        ("revoke_and_substitute", "Revoke and substitute"),
                        ("amend_add", "Amend by adding"),
                        ("amend_strike_sub", "Amend by striking and substituting"),
                        ("revoked", "Revoked"),
                    ],
                    default="original",
                    max_length=50,
                )),
                ("effective_date", models.DateField()),
                ("ineffective_date", models.DateField(blank=True, null=True)),
                ("title", models.CharField(blank=True, default="", max_length=500)),
                ("html", models.TextField(blank=True, default="")),
                ("page_images", models.JSONField(blank=True, null=True)),
                ("keyword_counts", models.JSONField(blank=True, null=True)),
                (
                    "provision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="core.codeeditionprovision",
                    ),
                ),
                (
                    "clause",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="provision_versions",
                        to="core.regulationclause",
                    ),
                ),
                (
                    "transition_provision",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="transition_targets",
                        to="core.codeeditionprovisionversion",
                    ),
                ),
            ],
            options={
                "db_table": "code_edition_provision_versions",
                "ordering": ["version"],
            },
        ),
        migrations.AddIndex(
            model_name="codeeditionprovisionversion",
            index=models.Index(
                fields=["provision", "effective_date"],
                name="code_editio_provisi_c3d6e7_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="codeeditionprovisionversion",
            index=models.Index(
                fields=["clause"],
                name="code_editio_clause__f4a7b8_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="codeeditionprovisionversion",
            index=models.Index(
                fields=["effective_date", "ineffective_date"],
                name="code_editio_effecti_a5b8c9_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="codeeditionprovisionversion",
            constraint=models.UniqueConstraint(
                fields=("provision", "version"),
                name="version_provision_version_unique",
            ),
        ),
        # --- ProvisionVersionTable ---
        migrations.CreateModel(
            name="ProvisionVersionTable",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("table_id", models.CharField(max_length=200)),
                ("caption", models.CharField(blank=True, default="", max_length=500)),
                ("images", models.JSONField(default=list)),
                ("notes", models.TextField(blank=True, default="")),
                ("order", models.PositiveSmallIntegerField(default=0)),
                (
                    "version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tables",
                        to="core.codeeditionprovisionversion",
                    ),
                ),
            ],
            options={
                "db_table": "provision_version_tables",
                "ordering": ["order"],
            },
        ),
        migrations.AddConstraint(
            model_name="provisionversiontable",
            constraint=models.UniqueConstraint(
                fields=("version", "table_id"),
                name="table_version_table_id_unique",
            ),
        ),
        # --- ProvisionEditionMapping ---
        migrations.CreateModel(
            name="ProvisionEditionMapping",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("mapping_type", models.CharField(max_length=20)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "old_provision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mapped_forward",
                        to="core.codeeditionprovision",
                    ),
                ),
                (
                    "new_provision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mapped_back",
                        to="core.codeeditionprovision",
                    ),
                ),
            ],
            options={
                "db_table": "provision_edition_mappings",
            },
        ),
        migrations.AddConstraint(
            model_name="provisioneditionmapping",
            constraint=models.UniqueConstraint(
                fields=("old_provision", "new_provision"),
                name="provision_mapping_unique",
            ),
        ),
    ]
