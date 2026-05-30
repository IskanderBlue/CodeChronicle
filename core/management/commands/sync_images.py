"""Mirror CCM-produced image/asset trees into the local ASSET_ROOT.

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

Sync is content-addressed and idempotent: a file is only re-copied when
the destination is absent, the destination size differs, or (for
``laws/images/``) the destination sha256 fails to match the manifest.
The decision per file is appended to ``image_sync_log.jsonl`` in
``ASSET_ROOT`` so reruns are O(diff).

S3 migration plan: swap the per-file ``_copy_file`` call for a boto3
upload.  Path layout, manifest format, and ingest-time verification all
stay identical — only the destination writer changes.
"""

from __future__ import annotations

import hashlib
import json
import shutil
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


def _sha256_of_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


class Command(BaseCommand):
    help = (
        "Mirror CCM-produced image/asset trees into ASSET_ROOT.  "
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
            "--dest",
            default=None,
            help=(
                "Destination root.  Defaults to settings.ASSET_ROOT."
            ),
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
        dest_root = Path(options["dest"]).expanduser().resolve() if options["dest"] else Path(settings.ASSET_ROOT).resolve()
        prefix = options["prefix"]
        strict = options["strict_manifest"]

        if not source_root.exists() or not source_root.is_dir():
            raise CommandError(f"Source root not found: {source_root}")

        dest_root.mkdir(parents=True, exist_ok=True)
        log_path = dest_root / LOG_FILENAME

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
                    rel = src.relative_to(source_root).as_posix()
                    dest = dest_root / rel

                    expected_sha = manifest.get(rel)
                    action = self._decide(src, dest, expected_sha)
                    if action == "copy":
                        _copy_file(src, dest)
                        copied += 1
                    else:
                        skipped += 1

                    if expected_sha:
                        actual = _sha256_of_file(dest)
                        if actual != expected_sha:
                            mismatches.append(rel)
                        else:
                            verified += 1

                    log_f.write(json.dumps({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "path": rel,
                        "action": action,
                        "verified": bool(expected_sha) and rel not in mismatches,
                    }) + "\n")

        # Report manifest entries we never saw on disk.
        if "laws" in prefixes:
            for rel in manifest.keys():
                if not (dest_root / rel).exists():
                    missing.append(rel)

        logger.info(
            "sync_images: copied=%d skipped=%d verified=%d mismatches=%d missing_manifest=%d",
            copied, skipped, verified, len(mismatches), len(missing),
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

    def _decide(self, src: Path, dest: Path, expected_sha: str | None) -> str:
        """Return ``"copy"`` if the file must be (re)written, else ``"skip"``.

        For laws/ paths with a manifest sha, we copy if the destination is
        absent OR its current bytes don't hash to the expected sha.
        For other paths, we copy when absent or size differs — cheap
        check that's good enough for build artifacts.
        """
        if not dest.exists():
            return "copy"
        if expected_sha:
            if _sha256_of_file(dest) == expected_sha:
                return "skip"
            return "copy"
        if dest.stat().st_size != src.stat().st_size:
            return "copy"
        return "skip"
