"""Mirror CCM-produced image/asset trees into ASSET_ROOT or Cloudflare R2.

Three trees are mirrored, all path-verbatim so that the URL paths
referenced from ``versions[].html``, ``versions[].page_images[].image``,
and ``tables[].images[].image`` resolve without rewriting:

* ``documents/{pdf_name}/{page}.webp`` — full page images shared across
  provisions on the same page.
* ``amended/{code}/{edition}/{table_id}/{version}/{num}.webp`` —
  pre-composited table images for amended versions.
* ``laws/images/...`` — e-Laws inline asset bytes (equations, scanned
  figures).  Verified against ``RegulationAsset.sha256`` when a manifest
  entry exists for the path.

Sync is content-addressed and idempotent: a file is only re-written when
the destination is absent, the destination size differs, or (for
``laws/images/``) the destination sha256 fails to match the manifest.
The decision per file is appended to ``image_sync_log.jsonl`` so reruns
are O(diff).

Two destination backends share that decision logic:

* ``local`` (default) — copies into ``ASSET_ROOT`` (or ``--dest``).  This
  is the dev path; assets are served by Django/nginx from disk.
* ``r2`` — uploads to the Cloudflare R2 bucket configured by the
  ``R2_*`` settings.  Production assets are served from R2 at the edge by
  a Worker (see Terraform ``modules/cloudflare``); the sync side stores
  each object's sha256 as user metadata so reruns can skip unchanged
  objects with a single ``HEAD`` (no re-download).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coloured_logger import Logger
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import RegulationAsset

logger = Logger(__name__)

MIRRORED_PREFIXES = ("documents", "amended", "laws")
LOG_FILENAME = "image_sync_log.jsonl"
SHA_METADATA_KEY = "sha256"


def _sha256_of_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class _LocalBackend:
    """Write to a local directory tree (the dev / on-disk serving path)."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root

    def _dest(self, key: str) -> Path:
        return self.root / key

    def head(self, key: str) -> tuple[bool, int, str | None]:
        """Return (exists, size, sha256).  Local has no cheap stored sha."""
        dest = self._dest(key)
        if not dest.exists():
            return (False, 0, None)
        return (True, dest.stat().st_size, None)

    def stored_sha(self, key: str) -> str | None:
        dest = self._dest(key)
        return _sha256_of_file(dest) if dest.exists() else None

    def put(self, src: Path, key: str, sha256: str | None) -> None:
        import shutil

        dest = self._dest(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    def verify(self, src: Path, key: str, expected_sha: str) -> bool:
        return self.stored_sha(key) == expected_sha


class _R2Backend:
    """Upload to a Cloudflare R2 bucket via the S3-compatible API."""

    name = "r2"

    def __init__(self) -> None:
        missing = [
            setting
            for setting in ("R2_ENDPOINT_URL", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
            if not getattr(settings, setting, "")
        ]
        if missing:
            raise CommandError(
                "--backend r2 requires these settings/env vars: " + ", ".join(missing)
            )

        import boto3  # local dep; imported lazily so the local backend never needs it

        self.bucket = settings.R2_BUCKET
        # R2 ignores region but botocore requires one; "auto" is the documented value.
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )

    def head(self, key: str) -> tuple[bool, int, str | None]:
        from botocore.exceptions import ClientError

        try:
            resp = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return (False, 0, None)
            raise
        return (True, int(resp.get("ContentLength", 0)), resp.get("Metadata", {}).get(SHA_METADATA_KEY))

    def stored_sha(self, key: str) -> str | None:
        # No cheap remote sha beyond what head() already surfaced from
        # metadata; force a re-upload rather than download to recompute.
        return None

    def put(self, src: Path, key: str, sha256: str | None) -> None:
        extra = {"Metadata": {SHA_METADATA_KEY: sha256}} if sha256 else {}
        self.client.upload_file(str(src), self.bucket, key, ExtraArgs=extra or None)

    def verify(self, src: Path, key: str, expected_sha: str) -> bool:
        # The upload is integrity-checked by the S3 API, so the stored
        # object equals src; verifying src against the manifest is
        # equivalent and avoids a round-trip download.
        return _sha256_of_file(src) == expected_sha


class Command(BaseCommand):
    help = (
        "Mirror CCM-produced image/asset trees into ASSET_ROOT or R2.  "
        "Idempotent and content-addressed for laws/images/ paths "
        "registered in RegulationAsset; size-checked elsewhere."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            default=str(Path("..") / "CodeChronicleMapping" / "data" / "outputs"),
            help=(
                "CCM build artifact root containing documents/, amended/, "
                "and laws/ subdirectories."
            ),
        )
        parser.add_argument(
            "--backend",
            choices=("local", "r2"),
            default="local",
            help="Destination backend.  Default: local (ASSET_ROOT on disk).",
        )
        parser.add_argument(
            "--dest",
            default=None,
            help="Local backend only: destination root.  Defaults to settings.ASSET_ROOT.",
        )
        parser.add_argument(
            "--prefix",
            choices=MIRRORED_PREFIXES,
            default=None,
            help=(
                "Restrict to a single prefix (documents/amended/laws).  "
                "Default: all three."
            ),
        )
        parser.add_argument(
            "--strict-manifest",
            action="store_true",
            help=(
                "For laws/images/ paths registered in RegulationAsset, "
                "require sha256 verification to pass.  Fails the command "
                "if any registered asset is missing or hash-mismatched.  "
                "Off by default during development."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source_root = Path(options["source"]).expanduser().resolve()
        prefix = options["prefix"]
        strict = options["strict_manifest"]

        if not source_root.exists() or not source_root.is_dir():
            raise CommandError(f"Source root not found: {source_root}")

        # The decision log always lives on disk next to the local root, even
        # for R2 runs, so reruns stay auditable without a bucket read.
        local_root = (
            Path(options["dest"]).expanduser().resolve()
            if options["dest"]
            else Path(settings.ASSET_ROOT).resolve()
        )

        if options["backend"] == "r2":
            backend: _LocalBackend | _R2Backend = _R2Backend()
            log_dir = local_root
        else:
            backend = _LocalBackend(local_root)
            log_dir = local_root

        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / LOG_FILENAME

        prefixes = (prefix,) if prefix else MIRRORED_PREFIXES

        # Build manifest of registered assets (sha256 by path) for the
        # laws/ tree so we can verify byte-for-byte.
        manifest: dict[str, str] = {}
        if "laws" in prefixes:
            for row in RegulationAsset.objects.exclude(sha256="").values("path", "sha256"):
                manifest[row["path"]] = row["sha256"]

        copied = 0
        skipped = 0
        verified = 0
        mismatches: list[str] = []
        missing: list[str] = []

        with log_path.open("a", encoding="utf-8") as log_f:
            for p in prefixes:
                src_dir = source_root / p
                if not src_dir.exists():
                    logger.info("Source subtree %s not present at %s; skipping", p, src_dir)
                    continue
                for src in src_dir.rglob("*"):
                    if not src.is_file():
                        continue
                    key = src.relative_to(source_root).as_posix()
                    expected_sha = manifest.get(key)

                    action = self._decide(backend, src, key, expected_sha)
                    if action == "copy":
                        backend.put(src, key, sha256=expected_sha or _sha256_of_file(src))
                        copied += 1
                    else:
                        skipped += 1

                    if expected_sha:
                        if backend.verify(src, key, expected_sha):
                            verified += 1
                        else:
                            mismatches.append(key)

                    log_f.write(json.dumps({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "backend": backend.name,
                        "path": key,
                        "action": action,
                        "verified": bool(expected_sha) and key not in mismatches,
                    }) + "\n")

        # Report manifest entries we never saw at the destination.
        if "laws" in prefixes:
            for key in manifest:
                if not backend.head(key)[0]:
                    missing.append(key)

        logger.info(
            "sync_images[%s]: copied=%d skipped=%d verified=%d mismatches=%d missing_manifest=%d",
            backend.name, copied, skipped, verified, len(mismatches), len(missing),
        )
        if mismatches:
            logger.warning("sha256 mismatch for %d asset(s): %s", len(mismatches), mismatches[:5])
        if missing:
            logger.warning(
                "manifest registered %d asset(s) absent from source: %s",
                len(missing), missing[:5],
            )

        if strict and (mismatches or missing):
            raise CommandError(
                f"--strict-manifest: {len(mismatches)} mismatch(es), "
                f"{len(missing)} missing.  Refusing to declare success."
            )

    def _decide(
        self,
        backend: _LocalBackend | _R2Backend,
        src: Path,
        key: str,
        expected_sha: str | None,
    ) -> str:
        """Return ``"copy"`` if the file must be (re)written, else ``"skip"``.

        For laws/ paths with a manifest sha, we copy if the destination is
        absent OR its known sha doesn't match the expected one.  For other
        paths, we copy when absent or size differs — a cheap check that's
        good enough for content-addressed build artifacts.
        """
        exists, size, stored_sha = backend.head(key)
        if not exists:
            return "copy"
        if expected_sha:
            current = stored_sha if stored_sha is not None else backend.stored_sha(key)
            return "skip" if current == expected_sha else "copy"
        return "skip" if size == src.stat().st_size else "copy"
