"""Off-host logical backup of the *irreproducible* data only.

Implements ``docs/security/disaster-recovery-plan.md`` §7.  The corpus tables
(provisions, versions, clauses, …) are re-loadable from CCM via ``load_edition``,
so this dumps their *schema* but skips their *rows* (``--exclude-table-data``),
backing up only the user/operational data we cannot rebuild: ``users``,
``search_history``, ``engagement_events``, ``auth_events``, the LLM-cache and
Django/allauth/dj-stripe tables, and anything new (included by default — only the
known-reproducible corpus tables are excluded).

Pipeline: ``pg_dump`` (custom format) → encrypt with ``age`` to a recipient
*public* key (the box never holds the private key, so a compromised backup host
cannot read its own backups) → upload to the R2 backups bucket → delete local
temp files.  Every step fails loudly; an unencrypted PII dump is never uploaded
unless ``--allow-unencrypted`` is passed explicitly.

Because it runs unattended, every failure here is silent by default.  Three
things answer that, and they are deliberately not the same thing:

* the upload is **read back** with ``head_object`` and its size checked, so a
  PUT that did not land cannot report success;
* each run writes a ``BackupRun`` row, success or failure, which ``/insights/``
  reads for freshness — that is the *record*;
* on finishing, the run pings ``BACKUP_HEALTHCHECK_URL`` — that is the *alarm*,
  and it lives off this host so it still fires when this host does not.

Schedule daily (a systemd timer on the VM — Container-Optimized OS has no
cron).  Restore: see the
recovery plan §7 — ``pg_restore`` the decrypted dump into a fresh database, then
re-run ``load_edition`` to refill the corpus.

    python manage.py backup_userdata                 # dump → encrypt → upload to R2
    python manage.py backup_userdata --dest .tmp/    # local file only (for drills)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from coloured_logger import Logger
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now as timezone_now

from core.models import BackupRun

logger = Logger(__name__)

#: How long to wait on the dead-man's-switch ping.  Short on purpose: the ping
#: is a notification, and a slow notifier must never hold up or fail a backup
#: that has already succeeded.
PING_TIMEOUT_SECONDS = 10

#: Reproducible-from-CCM corpus tables — we keep their schema in the dump but
#: skip their (bulky) rows.  Single source of truth for the exclude-list; the
#: guard test ``test_backup_userdata`` asserts every name here is a real model
#: table, so a rename/typo can't silently let the big tables into the backup.
CORPUS_TABLES: tuple[str, ...] = (
    "codes",
    "code_editions",
    "province_codes",
    "regulations",
    "regulation_clauses",
    "regulation_assets",
    "code_edition_provisions",
    "code_edition_provision_versions",
    "code_edition_provision_version_clauses",
    "provision_version_tables",
    "provision_mappings",
    "provision_dispositions",
    "edition_transitions",
    "corpus_currency",
    # Added 2026-08-07 after a restore drill. These four are corpus-derived like
    # the rest, but were kept, and a kept table that holds a foreign key into an
    # excluded table cannot restore: the parent rows are not there, so
    # pg_restore reports the constraint as a *warning* and leaves it off the
    # restored database. Five constraints failed that way. They also carried the
    # bulk — `provision_cross_references` alone was 42,983 rows in a 1.7 MB dump
    # that exists to hold 6 users. Rebuilt by `load_edition`, except
    # `consolidations`, which `load_consolidations` rebuilds from
    # `data/elaws_consolidations.json` in this repository.
    "provision_cross_references",
    "provision_cross_reference_alternates",
    "provision_version_assets",
    "consolidations",
)


class Command(BaseCommand):
    help = (
        "Encrypted, off-host logical backup of irreproducible user data "
        "(excludes the CCM-reproducible corpus). See disaster-recovery-plan.md §7."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dest",
            default=None,
            help=(
                "Write the (encrypted) dump to this local directory instead of "
                "uploading to R2. For restore drills / testing the pipeline."
            ),
        )
        parser.add_argument(
            "--allow-unencrypted",
            action="store_true",
            help=(
                "Skip encryption. Refused by default — the dump is concentrated "
                "PII. Only for a local --dest drill on a trusted machine."
            ),
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=None,
            help=(
                "After upload, prune the R2 backup prefix to the newest N objects. "
                "Omit to rely on a bucket lifecycle policy instead (preferred)."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Record the run, then ping, whichever way it goes.

        The record and the ping both have to happen on the failure path too.  A
        row written only on success cannot distinguish a broken backup from one
        that never started, and a ping sent only on success makes the alarm
        wait for its timeout before saying what the command already knew.
        """
        run = BackupRun.objects.create(
            kind=BackupRun.Kind.LOCAL if options["dest"] else BackupRun.Kind.UPLOAD
        )
        try:
            location, size = self._run_backup(**options)
        except Exception as exc:
            run.finished_at = timezone_now()
            run.error = str(exc)[:4000]
            run.save(update_fields=["finished_at", "error"])
            self._ping(ok=False, detail=str(exc))
            raise
        run.finished_at = timezone_now()
        run.succeeded = True
        run.location = location
        run.size_bytes = size
        run.save(update_fields=["finished_at", "succeeded", "location", "size_bytes"])
        self._ping(ok=True, detail=f"{location} ({size} bytes)")

    def _run_backup(self, **options: Any) -> tuple[str, int]:
        encrypt = not options["allow_unencrypted"]
        recipient = getattr(settings, "BACKUP_AGE_RECIPIENT", "") or ""
        if encrypt and not recipient:
            raise CommandError(
                "BACKUP_AGE_RECIPIENT (an age public key, 'age1…') is not set. "
                "Set it, or pass --allow-unencrypted for a local drill."
            )

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base_name = f"cc-userdata-{stamp}.dump"

        # Work in a private temp dir so the plaintext dump never lands in a
        # world-readable location, and is removed even on failure.
        with tempfile.TemporaryDirectory(prefix="ccbackup-") as tmp:
            tmp_path = Path(tmp)
            dump_path = tmp_path / base_name
            self._pg_dump(dump_path)

            upload_path, upload_name = dump_path, base_name
            if encrypt:
                enc_path = tmp_path / (base_name + ".age")
                self._age_encrypt(dump_path, enc_path, recipient)
                # Drop the plaintext as soon as the ciphertext exists.
                dump_path.unlink(missing_ok=True)
                upload_path, upload_name = enc_path, enc_path.name

            if options["dest"]:
                written = self._save_local(
                    upload_path, Path(options["dest"]).expanduser(), upload_name
                )
                location, size = str(written), written.stat().st_size
            else:
                location, size = self._upload_r2(upload_path, upload_name)
                if options["keep"] is not None:
                    self._prune_r2(keep=options["keep"])

        logger.info("backup_userdata: done (%s)", upload_name)
        return location, size

    # -- steps ---------------------------------------------------------------

    def _pg_dump(self, out_path: Path) -> None:
        """Dump schema for all tables + data for everything except the corpus."""
        db = settings.DATABASES["default"]
        if "postgresql" not in db.get("ENGINE", ""):
            raise CommandError(f"backup_userdata supports PostgreSQL only (got {db.get('ENGINE')}).")

        argv = [
            "pg_dump",
            "--format=custom",       # -Fc: compressed, pg_restore-able, selective
            "--no-owner",
            "--no-privileges",       # restore into any role
            "--host", str(db.get("HOST") or "localhost"),
            "--port", str(db.get("PORT") or "5432"),
            "--username", str(db.get("USER") or ""),
            "--dbname", str(db.get("NAME") or ""),
            "--file", str(out_path),
        ]
        for table in CORPUS_TABLES:
            argv += ["--exclude-table-data", f"public.{table}"]

        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = str(db["PASSWORD"])
        # Neon (and any managed PG) requires TLS; never silently downgrade.
        env.setdefault("PGSSLMODE", str(db.get("OPTIONS", {}).get("sslmode") or "require"))

        logger.info("pg_dump → %s (excluding data for %d corpus tables)", out_path.name, len(CORPUS_TABLES))
        self._run(argv, env=env, what="pg_dump")
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise CommandError("pg_dump produced no output.")

    def _age_encrypt(self, src: Path, dst: Path, recipient: str) -> None:
        logger.info("encrypting → %s (age, recipient %s…)", dst.name, recipient[:12])
        self._run(["age", "--recipient", recipient, "--output", str(dst), str(src)], what="age")
        if not dst.exists() or dst.stat().st_size == 0:
            raise CommandError("age produced no output.")

    def _save_local(self, src: Path, dest_dir: Path, name: str) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        written = dest_dir / name
        shutil.copy2(src, written)
        logger.info("backup written locally: %s", written)
        return written

    def _upload_r2(self, src: Path, name: str) -> tuple[str, int]:
        """Upload, then read the object back and check it.

        `upload_file` returning is not evidence the object exists.  It logs
        before it calls R2, and a multipart upload that completes with a
        truncated body still returns.  A `head_object` afterwards is the first
        statement that the bytes are there and are the right number of them —
        without it a silent failure reports success, and the daily backup looks
        healthy until the day somebody needs it.
        """
        client, bucket = self._r2_client()
        key = f"db-backups/{name}"
        expected = src.stat().st_size
        logger.info("uploading → r2://%s/%s (%d bytes)", bucket, key, expected)
        client.upload_file(str(src), bucket, key)

        try:
            head = client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            raise CommandError(
                f"upload reported success but r2://{bucket}/{key} cannot be read back: {exc}"
            ) from exc
        stored = int(head.get("ContentLength", -1))
        if stored != expected:
            raise CommandError(
                f"r2://{bucket}/{key} is {stored} bytes, expected {expected}. "
                "The stored backup is not the one that was made."
            )
        logger.info("verified in the bucket: %s (%d bytes)", key, stored)
        return f"r2://{bucket}/{key}", stored

    def _ping(self, *, ok: bool, detail: str) -> None:
        """Tell the dead-man's switch the run finished, and how.

        Never raises.  A backup that succeeded must not be reported as failed
        because the notifier was unreachable — and the switch handles that case
        already: a missing ping is exactly what it alarms on.
        """
        url = getattr(settings, "BACKUP_HEALTHCHECK_URL", "") or ""
        if not url:
            return
        target = url.rstrip("/") + ("" if ok else "/fail")
        try:
            request = urllib.request.Request(
                target, data=detail.encode("utf-8")[:10000], method="POST"
            )
            with urllib.request.urlopen(request, timeout=PING_TIMEOUT_SECONDS) as resp:
                logger.info("healthcheck ping %s → HTTP %s", "ok" if ok else "fail", resp.status)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning("healthcheck ping failed (the backup itself is unaffected): %s", exc)

    def _prune_r2(self, *, keep: int) -> None:
        client, bucket = self._r2_client()
        resp = client.list_objects_v2(Bucket=bucket, Prefix="db-backups/")
        objs = sorted(resp.get("Contents", []), key=lambda o: o["LastModified"], reverse=True)
        stale = objs[keep:]
        for obj in stale:
            client.delete_object(Bucket=bucket, Key=obj["Key"])
        if stale:
            logger.info("pruned %d old backup object(s), kept newest %d", len(stale), keep)

    # -- helpers -------------------------------------------------------------

    def _r2_client(self):
        required = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
        missing = [s for s in required if not getattr(settings, s, "")]
        # A dedicated backups bucket is strongly preferred over the assets bucket.
        bucket = getattr(settings, "R2_BACKUP_BUCKET", "") or getattr(settings, "R2_BUCKET", "")
        if not bucket:
            missing.append("R2_BACKUP_BUCKET (or R2_BUCKET)")
        if missing:
            raise CommandError("R2 upload requires: " + ", ".join(missing))

        client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
        return client, bucket

    def _run(self, argv: list[str], *, what: str, env: dict[str, str] | None = None) -> None:
        try:
            subprocess.run(argv, env=env, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise CommandError(f"{what}: executable not found ({argv[0]}). Is it installed/on PATH?") from exc
        except subprocess.CalledProcessError as exc:
            # stderr may carry the connection string context but not the password.
            raise CommandError(f"{what} failed (exit {exc.returncode}): {exc.stderr.strip()}") from exc
