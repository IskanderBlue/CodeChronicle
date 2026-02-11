from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_map_and_metadata_models"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="pdf_directory",
        ),
    ]
