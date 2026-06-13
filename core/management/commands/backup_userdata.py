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

Schedule daily/weekly (cron on the VM, or a scheduled job).  Restore: see the
recovery plan §7 — ``pg_restore`` the decrypted dump into a fresh database, then
re-run ``load_edition`` to refill the corpus.

    python manage.py backup_userdata                 # dump → encrypt → upload to R2
    python manage.py backup_userdata --dest .tmp/    # local file only (for drills)
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coloured_logger import Logger
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = Logger(__name__)

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
                self._save_local(upload_path, Path(options["dest"]).expanduser(), upload_name)
            else:
                self._upload_r2(upload_path, upload_name)
                if options["keep"] is not None:
                    self._prune_r2(keep=options["keep"])

        logger.info("backup_userdata: done (%s)", upload_name)

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

    def _save_local(self, src: Path, dest_dir: Path, name: str) -> None:
        import shutil

        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_dir / name)
        logger.info("backup written locally: %s", dest_dir / name)

    def _upload_r2(self, src: Path, name: str) -> None:
        client, bucket = self._r2_client()
        key = f"db-backups/{name}"
        logger.info("uploading → r2://%s/%s", bucket, key)
        client.upload_file(str(src), bucket, key)

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

        import boto3  # lazy: only needed for the upload path

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
