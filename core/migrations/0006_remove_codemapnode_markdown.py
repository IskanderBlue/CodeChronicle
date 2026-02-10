from django.db import migrations


class Migration(migrations.Migration):
    """Drop unused markdown field after pre-rendering into html."""

    dependencies = [
        ("core", "0005_map_and_metadata_models"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="codemapnode",
            name="markdown",
        ),
    ]
