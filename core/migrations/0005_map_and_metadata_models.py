from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import migrations, models


class Migration(migrations.Migration):
    """Create map storage and metadata models."""
    dependencies = [
        ('core', '0004_user_pdf_directory'),
    ]

    operations = [
        migrations.CreateModel(
            name='CodeMap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code_name', models.CharField(max_length=100)),
                ('map_code', models.CharField(max_length=100, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Code Map',
                'verbose_name_plural': 'Code Maps',
                'db_table': 'code_maps',
            },
        ),
        migrations.CreateModel(
            name='CodeMapNode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('node_id', models.CharField(max_length=200)),
                ('title', models.CharField(max_length=500)),
                ('page', models.IntegerField(blank=True, null=True)),
                ('page_end', models.IntegerField(blank=True, null=True)),
                ('html', models.TextField(blank=True, null=True)),
                ('notes_html', models.TextField(blank=True, null=True)),
                ('keywords', ArrayField(base_field=models.CharField(max_length=100), blank=True, null=True, size=None)),
                ('bbox', models.JSONField(blank=True, null=True)),
                ('parent_id', models.CharField(blank=True, max_length=200, null=True)),
                (
                    'code_map',
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='nodes', to='core.codemap'),
                ),
            ],
            options={
                'verbose_name': 'Code Map Node',
                'verbose_name_plural': 'Code Map Nodes',
                'db_table': 'code_map_nodes',
            },
        ),
        migrations.CreateModel(
            name='CodeSystem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=20, unique=True)),
                ('display_name', models.CharField(blank=True, default='', max_length=200)),
                ('is_national', models.BooleanField(default=False)),
                (
                    'document_type',
                    models.CharField(
                        choices=[('code', 'code'), ('guide', 'guide')],
                        default='code',
                        max_length=20,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Code System',
                'verbose_name_plural': 'Code Systems',
                'db_table': 'code_systems',
            },
        ),
        migrations.CreateModel(
            name='CodeEdition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('edition_id', models.CharField(max_length=50)),
                ('year', models.IntegerField()),
                ('map_codes', ArrayField(base_field=models.CharField(max_length=100), size=None)),
                ('effective_date', models.DateField()),
                ('superseded_date', models.DateField(blank=True, null=True)),
                ('pdf_files', models.JSONField(blank=True, null=True)),
                ('download_url', models.CharField(blank=True, default='', max_length=500)),
                ('amendments', models.JSONField(blank=True, null=True)),
                ('regulation', models.CharField(blank=True, default='', max_length=200)),
                ('version_number', models.IntegerField(blank=True, null=True)),
                ('source', models.CharField(blank=True, default='', max_length=50)),
                ('source_url', models.CharField(blank=True, default='', max_length=500)),
                ('amendments_applied', models.JSONField(blank=True, null=True)),
                ('is_guide', models.BooleanField(default=False)),
                (
                    'system',
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='editions', to='core.codesystem'),
                ),
            ],
            options={
                'verbose_name': 'Code Edition',
                'verbose_name_plural': 'Code Editions',
                'db_table': 'code_editions',
            },
        ),
        migrations.CreateModel(
            name='ProvinceCodeMap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('province', models.CharField(max_length=2, unique=True)),
                (
                    'code_system',
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='provinces', to='core.codesystem'),
                ),
            ],
            options={
                'verbose_name': 'Province Code Map',
                'verbose_name_plural': 'Province Code Maps',
                'db_table': 'province_code_maps',
            },
        ),
        migrations.AddConstraint(
            model_name='codemapnode',
            constraint=models.UniqueConstraint(fields=('code_map', 'node_id'), name='code_map_node_unique'),
        ),
        migrations.AddIndex(
            model_name='codemapnode',
            index=models.Index(fields=['node_id'], name='code_mapnode_node_id_idx'),
        ),
        migrations.AddIndex(
            model_name='codemapnode',
            index=GinIndex(fields=['keywords'], name='code_mapnode_keywords_gin'),
        ),
        migrations.AddConstraint(
            model_name='codeedition',
            constraint=models.UniqueConstraint(fields=('system', 'edition_id'), name='code_system_edition_unique'),
        ),
        migrations.AddIndex(
            model_name='codeedition',
            index=models.Index(fields=['system', 'effective_date'], name='code_edition_effective_idx'),
        ),
    ]
