"""Guard tests for the backup_userdata exclude-list (no DB / external tools needed)."""

from django.apps import apps

from core.management.commands.backup_userdata import CORPUS_TABLES


def test_corpus_tables_are_real_db_tables():
    """Every excluded corpus table must map to an actual model table.

    Catches a typo or a model rename that would silently let a bulky,
    supposedly-excluded corpus table back into the user-data-only backup.
    """
    real_tables = {m._meta.db_table for m in apps.get_models()}
    unknown = [t for t in CORPUS_TABLES if t not in real_tables]
    assert not unknown, f"CORPUS_TABLES entries match no model db_table: {unknown}"


def test_irreproducible_tables_are_not_excluded():
    """The data we cannot rebuild must never be in the exclude-list."""
    must_back_up = {"users", "search_history", "engagement_events", "auth_events"}
    leaked = must_back_up & set(CORPUS_TABLES)
    assert not leaked, f"irreproducible tables wrongly excluded from backup: {leaked}"


def test_no_kept_table_points_into_an_excluded_table():
    """A backed-up table must not hold a foreign key into an excluded one.

    The exclude-list keeps each table's *schema* and drops its *rows*. So a
    kept table whose rows reference an excluded table references rows that the
    restore does not have, and the foreign key cannot be created. pg_restore
    reports that as a **warning**, not an error: it exits 0 and leaves the
    constraint off the restored database. The operator sees a restore that
    worked and gets a database with less integrity than the one they lost.

    A restore drill on 2026-08-07 hit exactly this — five constraints, from
    ``provision_cross_references``, ``provision_cross_reference_alternates``,
    ``provision_version_assets`` and ``elaws_consolidations``. All four were
    corpus-derived and belonged in the exclude-list.

    The rule is one-directional. An excluded table may point at a kept table;
    it has no rows to dangle.
    """
    excluded = set(CORPUS_TABLES)
    offenders = []

    for model in apps.get_models():
        if model._meta.db_table in excluded:
            continue
        for field in model._meta.get_fields():
            if not (field.many_to_one or field.one_to_one) or not field.concrete:
                continue
            if field.related_model is None:
                continue
            target = field.related_model._meta.db_table
            if target in excluded:
                offenders.append(f"{model._meta.db_table}.{field.name} -> {target}")

    assert not offenders, (
        "these tables are backed up but reference excluded corpus tables, so "
        "their foreign keys will not survive a restore — exclude them too, or "
        "stop excluding what they point at: " + ", ".join(sorted(offenders))
    )
