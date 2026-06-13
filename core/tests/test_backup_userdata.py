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
