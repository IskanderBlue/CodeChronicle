"""Rename CodeSystem → Code and ProvinceCodeMap → ProvinceCode.

Also renames db_tables and the ProvinceCode.code_system field → code.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_keyword_idf_matview"),
    ]

    operations = [
        # Rename models
        migrations.RenameModel(
            old_name="CodeSystem",
            new_name="Code",
        ),
        migrations.RenameModel(
            old_name="ProvinceCodeMap",
            new_name="ProvinceCode",
        ),
        # Rename db_tables
        migrations.AlterModelTable(
            name="code",
            table="codes",
        ),
        migrations.AlterModelTable(
            name="provincecode",
            table="province_codes",
        ),
        # Rename field: ProvinceCode.code_system → ProvinceCode.code
        migrations.RenameField(
            model_name="provincecode",
            old_name="code_system",
            new_name="code",
        ),
        # Update Meta options
        migrations.AlterModelOptions(
            name="code",
            options={"verbose_name": "Code", "verbose_name_plural": "Codes"},
        ),
        migrations.AlterModelOptions(
            name="provincecode",
            options={
                "verbose_name": "Province Code",
                "verbose_name_plural": "Province Codes",
            },
        ),
    ]
