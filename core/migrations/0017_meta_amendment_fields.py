"""Add meta-amendment fields to ``RegulationClause``.

Populates from CCM impl-26 Wave 1 emissions:

- ``target_reg`` — on forward-pointer clauses that amend another
  regulation's clauses rather than a base-code provision.  Empty string
  means the target is a base-code provision (back-compat default).
- ``amended_by`` — on target-regulation back-pointer stubs, listing the
  meta-amending clauses that revoked/substituted this one.

Also relaxes ``action`` to allow blank so the meta-amendment stub and
forward-pointer entries (which carry pointer fields only today — see
impl-27) can be persisted without a synthesised action value.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_provisionversiontable_html"),
    ]

    operations = [
        migrations.AddField(
            model_name="regulationclause",
            name="target_reg",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="regulationclause",
            name="amended_by",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="regulationclause",
            name="action",
            field=models.CharField(
                blank=True,
                choices=[
                    ("revoke_and_substitute", "Revoke and substitute"),
                    ("amend_add", "Amend by adding"),
                    ("amend_strike_sub", "Amend by striking and substituting"),
                    ("revoke", "Revoke"),
                    ("renumber", "Renumber"),
                ],
                default="",
                max_length=50,
            ),
        ),
    ]
