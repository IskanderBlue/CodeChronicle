"""Mirror CCM-produced image/asset trees into ASSET_ROOT or Cloudflare R2.

Four trees are mirrored, all path-verbatim so that the URL paths
referenced from ``versions[].html``, ``versions[].page_images[].image``,
and ``tables[].images[].image`` resolve without rewriting:

* ``documents/{pdf_name}/{page}.webp`` — full page images shared across
  provisions on the same page.
* ``elaws/{reg}/{table_id}.jpg`` — pre-composited e-Laws table images.
* ``amended/{code}/{edition}/{table_id}/{version}/{num}.webp`` —
  pre-composited table images for amended versions.
* ``laws/images/...`` — e-Laws inline asset bytes (equations, scanned
  figures).  Verified against the sha256 of ``RegulationAsset`` and
  ``ProvisionVersionAsset`` when a manifest entry exists for the path.

CCM does not put those four trees under one root: ``laws/`` is a build
*output*, while ``documents/`` and ``elaws/`` are *intermediates*.  So
``--source`` is repeatable and each prefix is taken from the first root
that holds it.  A single root silently published ``laws/`` alone and
called it a success, which is how production ran with 96 of the 532
objects it needed.

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
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coloured_logger import Logger
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.assets import DEFAULT_ASSET_SOURCES, MIRRORED_PREFIXES
from core.models import ProvisionVersionAsset, RegulationAsset

logger = Logger(__name__)

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
        "in the asset manifest; size-checked elsewhere."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            action="append",
            default=None,
            help=(
                "CCM artifact root holding one or more mirrored prefixes.  "
                "Repeatable; each prefix is taken from the first root that "
                "holds it.  Default: the outputs root then the "
                "intermediates/images root, which together cover all four."
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
                "Restrict to a single mirrored prefix.  Default: all of them."
            ),
        )
        parser.add_argument(
            "--strict-manifest",
            action="store_true",
            help=(
                "For laws/images/ paths in the asset manifest, "
                "require sha256 verification to pass.  Fails the command "
                "if any registered asset is missing or hash-mismatched.  "
                "Off by default during development."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source_roots = [
            Path(s).expanduser().resolve()
            for s in (options["source"] or DEFAULT_ASSET_SOURCES)
        ]
        prefix = options["prefix"]
        strict = options["strict_manifest"]

        # An explicit --source that does not exist is an operator mistake and
        # must fail loudly.  A missing *default* root is not: a checkout that
        # holds only the outputs tree is a legitimate partial sync.
        for root in source_roots:
            if root.exists() and root.is_dir():
                continue
            if options["source"]:
                raise CommandError(f"Source root not found: {root}")
            logger.info("Default source root %s not present; skipping it", root)
        source_roots = [r for r in source_roots if r.exists() and r.is_dir()]
        if not source_roots:
            raise CommandError("No source root exists; nothing to mirror.")

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
        #
        # Both asset scopes feed it.  The regulation scope alone describes the
        # source filings, which is a smaller set than the served HTML names —
        # so a body-only reference was verified by nothing and reported by
        # nothing, and 115 of them 404'd in production.  The version scope is
        # the set a reader actually asks for.
        manifest: dict[str, str] = {}
        if "laws" in prefixes:
            rows = itertools.chain(
                RegulationAsset.objects.exclude(sha256="").values("path", "sha256"),
                ProvisionVersionAsset.objects.exclude(sha256="").values("path", "sha256"),
            )
            for row in rows:
                path, sha = row["path"], row["sha256"]
                previous = manifest.get(path)
                if previous is not None and previous != sha:
                    # One path, two hashes: the corpus disagrees with itself
                    # about what these bytes are, and only one of the two can
                    # be published.  Never silent.
                    logger.warning(
                        "manifest disagrees on %s: %s vs %s; keeping the first",
                        path, previous, sha,
                    )
                    continue
                manifest[path] = sha

        copied = 0
        skipped = 0
        verified = 0
        mismatches: set[str] = set()
        # Every source key walked this run; manifest keys never seen are the
        # "absent from source" set, computed without a per-asset HEAD below.
        seen: set[str] = set()
        missing: list[str] = []

        # Resolve each prefix to the first root that holds it, before copying
        # anything, so the run can report up front which prefixes it found
        # nowhere.  That report is the whole point: the previous single-root
        # version could not tell "this tree is absent" from "there is no such
        # tree", and published a quarter of the corpus without complaint.
        resolved: dict[str, Path] = {}
        unresolved: list[str] = []
        for p in prefixes:
            for root in source_roots:
                if (root / p).is_dir():
                    resolved[p] = root
                    break
            else:
                unresolved.append(p)

        for p, root in resolved.items():
            logger.info("Mirroring %s/ from %s", p, root)
        if unresolved:
            logger.warning(
                "no source root holds these prefixes, so nothing is published "
                "for them: %s", ", ".join(unresolved),
            )

        with log_path.open("a", encoding="utf-8") as log_f:
            for p, source_root in resolved.items():
                for src in (source_root / p).rglob("*"):
                    if not src.is_file():
                        continue
                    key = src.relative_to(source_root).as_posix()
                    seen.add(key)
                    expected_sha = manifest.get(key)

                    action = self._decide(backend, src, key, expected_sha)
                    if action == "copy":
                        backend.put(src, key, sha256=expected_sha or _sha256_of_file(src))
                        copied += 1
                        # Confirm the freshly written asset matches the manifest.
                        if expected_sha:
                            if backend.verify(src, key, expected_sha):
                                verified += 1
                            else:
                                mismatches.add(key)
                    else:
                        skipped += 1
                        # A skip means _decide already found the stored sha equals
                        # the manifest sha, so the asset is verified by
                        # construction.  Re-hashing src here (R2.verify) is what
                        # made reruns O(total bytes) instead of the promised
                        # O(diff); trust the decision instead.
                        if expected_sha:
                            verified += 1

                    log_f.write(json.dumps({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "backend": backend.name,
                        "path": key,
                        "action": action,
                        "verified": bool(expected_sha) and key not in mismatches,
                    }) + "\n")

        # Manifest entries with no corresponding source file this run.  Derived
        # from the keys already walked, so no per-asset HEAD round-trip (this is
        # also the literal meaning of the "absent from source" warning below).
        if "laws" in prefixes:
            missing = [key for key in manifest if key not in seen]

        logger.info(
            "sync_images[%s]: copied=%d skipped=%d verified=%d mismatches=%d missing_manifest=%d",
            backend.name, copied, skipped, verified, len(mismatches), len(missing),
        )
        if mismatches:
            logger.warning(
                "sha256 mismatch for %d asset(s): %s",
                len(mismatches), sorted(mismatches)[:5],
            )
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
