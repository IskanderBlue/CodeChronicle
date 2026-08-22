"""Guard tests for backup_userdata: the exclude-list, and the silence.

The exclude-list tests need no database and no external tool.  The rest do
need a database, because what they hold is the record of each run.
"""

import urllib.request

import pytest
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.management.commands.backup_userdata import CORPUS_TABLES, Command
from core.models import BackupRun
from telemetry.insights import backup_state


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


# ---------------------------------------------------------------------------
# The record, the verification and the dead-man's switch.
#
# All three exist because of one property of this command: it runs unattended,
# so every failure is silent by default.  The tests below hold the three places
# that silence was possible.
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_pipeline(monkeypatch, tmp_path):
    """Replace pg_dump and age with files, leaving the surrounding logic real.

    The point of these tests is the bookkeeping around the pipeline, not the
    pipeline: neither binary is present in CI, and shelling out would test
    PostgreSQL rather than this module.
    """

    def fake_dump(self, out_path):
        out_path.write_bytes(b"PGDMP-stub")

    def fake_encrypt(self, src, dst, recipient):
        dst.write_bytes(b"age-stub" + src.read_bytes())

    monkeypatch.setattr(Command, "_pg_dump", fake_dump)
    monkeypatch.setattr(Command, "_age_encrypt", fake_encrypt)
    return tmp_path


@pytest.mark.django_db
def test_a_local_drill_is_recorded_as_a_drill(stub_pipeline, settings):
    """A --dest run uploads nothing, so it must not refresh the backup clock."""
    settings.BACKUP_AGE_RECIPIENT = "age1stub"
    call_command("backup_userdata", dest=str(stub_pipeline))

    run = BackupRun.objects.get()
    assert run.kind == BackupRun.Kind.LOCAL
    assert run.succeeded
    assert run.size_bytes and run.size_bytes > 0
    assert backup_state()["last_good"] is None, "a drill must not count as a backup"


@pytest.mark.django_db
def test_a_failed_run_is_recorded_with_its_error(stub_pipeline, settings, monkeypatch):
    """A row written only on success cannot tell broken from never-started."""
    settings.BACKUP_AGE_RECIPIENT = "age1stub"

    def boom(self, out_path):
        raise CommandError("pg_dump failed (exit 1): connection refused")

    monkeypatch.setattr(Command, "_pg_dump", boom)
    with pytest.raises(CommandError):
        call_command("backup_userdata", dest=str(stub_pipeline))

    run = BackupRun.objects.get()
    assert not run.succeeded
    assert "connection refused" in run.error
    assert run.finished_at is not None


@pytest.mark.django_db
def test_the_upload_is_read_back_and_a_short_object_fails(stub_pipeline, settings):
    """`upload_file` returning is not evidence the object is there, or whole."""
    settings.BACKUP_AGE_RECIPIENT = "age1stub"

    class ShortUpload:
        def upload_file(self, path, bucket, key):
            self.uploaded = key

        def head_object(self, Bucket, Key):  # noqa: N803 — boto3's own casing
            return {"ContentLength": 1}

    Command._r2_client = lambda self: (ShortUpload(), "bucket")  # type: ignore[method-assign]
    try:
        with pytest.raises(CommandError, match="not the one that was made"):
            call_command("backup_userdata")
    finally:
        del Command._r2_client

    assert not BackupRun.objects.get().succeeded


@pytest.mark.django_db
def test_a_dead_ping_never_fails_a_good_backup(stub_pipeline, settings, monkeypatch):
    """The switch already alarms on a missing ping; failing here would be worse.

    Reporting a successful backup as failed because the notifier was down
    inverts the whole point of the alarm.
    """
    settings.BACKUP_AGE_RECIPIENT = "age1stub"
    settings.BACKUP_HEALTHCHECK_URL = "https://example.invalid/ping"

    def refuse(*args, **kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    call_command("backup_userdata", dest=str(stub_pipeline))

    assert BackupRun.objects.get().succeeded


@pytest.mark.django_db
def test_an_empty_history_reads_as_stale(settings):
    """Never-run and history-lost are the same situation, and neither is healthy."""
    state = backup_state()
    assert state["is_stale"]
    assert state["last_good"] is None
