from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_codeeditionprovisionversion_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="corpuscurrency",
            name="coverage_end",
            field=models.DateField(blank=True, null=True),
        ),
    ]
