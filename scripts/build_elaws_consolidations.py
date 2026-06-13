"""Build the e-Laws consolidation date-range map for CodeChronicle.

An e-Laws *consolidation snapshot* is NOT a source (the regulation is the
source); it is a point-in-time rendering of the assembled code that we link to
so a user can see a provision "as it read" on a given date. e-Laws republishes a
new consolidation each time an amendment commences, and each republication
states the date range it covers. This script emits one row per real
consolidation period:

    {"code", "edition", "version", "url", "effective_from", "effective_to"}

resolved later by as-of date.

Design — read each consolidation's own banner, not a derived index:

  * Every cached consolidation page states its range itself: a historical
    version carries "Historical version for the period <from> to <to>", and the
    live page carries "Consolidation Period: From <from> to <currency date>".
    We strip tags (e-Laws is an SPA, so the banner words are split across tags
    and can't be grepped from raw HTML) and read that range straight from the
    file. No neighbour inference, no separate date index.

  * URL + e-Laws version come from the cache filename, per spec: the cache file
    ``120332_v38.html`` becomes ``.../laws/regulation/120332/v38`` (prefix with
    ``_v`` -> ``/v``). This matters: CCM's *snapshot* JSONs number versions on an
    internal sequence that does NOT match the e-Laws version id (OBC 1997's
    snapshots are v13-v25 while its e-Laws cache is v1-v13), so the version for
    the URL must come from the cache filename — never from the snapshot index.

  * Stub exclusion is automatic: a placeholder/never-published or revoked slot
    (~58 KB) has no period banner, so it yields nothing and is skipped.

The per-version snapshot JSONs are consulted ONLY to map a cache-file prefix to
its (code, edition) — a reg->edition fact that is independent of version number.

Usage:
    python scripts/build_elaws_consolidations.py \
        [--ccm ../CodeChronicleMapping] [--out data/elaws_consolidations.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ELAWS_BASE_URL = "https://www.ontario.ca/laws/regulation/"

# Snapshot filename: CODE_EDITION_vNN_<number>-<year>.json (version index here is
# CCM-internal — used only for the reg, never for the URL).
SNAPSHOT_RE = re.compile(
    r"^(?P<code>[A-Za-z0-9]+)_(?P<edition>[A-Za-z0-9]+)_v\d+_"
    r"(?P<reg>\d+-\d+)\.json$"
)
# Cache filename: <prefix>_v<N>.html — prefix is the e-Laws consolidation id, N
# is the authoritative e-Laws version number.
CACHE_RE = re.compile(r"^(?P<prefix>\d+)_v(?P<version>\d+)\.html$")

_DATE = r"([A-Za-z]+ \d{1,2}, \d{4})"
HISTORICAL_RE = re.compile(rf"Historical version for the period {_DATE} to {_DATE}")
CURRENT_RE = re.compile(rf"Consolidation Period: From {_DATE} to ")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def elaws_id(reg_filename_part: str) -> str:
    """``"403-97"`` (number-year, as snapshot filenames encode it) -> ``"970403"``.

    The e-Laws consolidation id is the two-digit year followed by the regulation
    number zero-padded to four digits — matching the ``elaws_cache`` filenames.
    """
    number, year = reg_filename_part.split("-")
    return f"{year}{int(number):04d}"


def _iso(human_date: str) -> str:
    """``"April 10, 2024"`` -> ``"2024-04-10"``."""
    return datetime.strptime(human_date, "%B %d, %Y").date().isoformat()


def extract_period(path: Path) -> tuple[str, str | None] | None:
    """Return ``(effective_from, effective_to)`` from the page's own banner.

    ``effective_to`` is the inclusive last day e-Laws states for the period, or
    ``None`` for the live "current" consolidation. Returns ``None`` when the page
    has no period banner (a stub / non-consolidation slot).
    """
    html = path.read_text(encoding="utf-8", errors="replace")
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html))
    m = HISTORICAL_RE.search(text)
    if m:
        return _iso(m.group(1)), _iso(m.group(2))
    m = CURRENT_RE.search(text)
    if m:
        return _iso(m.group(1)), None
    return None


def build(ccm_root: Path) -> list[dict]:
    snapshots_dir = ccm_root / "data" / "intermediates" / "snapshots"
    cache_dir = ccm_root / "data" / "intermediates" / "elaws_cache"
    if not snapshots_dir.is_dir():
        sys.exit(f"snapshots dir not found: {snapshots_dir}")
    if not cache_dir.is_dir():
        sys.exit(f"elaws_cache dir not found: {cache_dir}")

    # Map each e-Laws cache prefix to its (code, edition) via the snapshots'
    # regulation — a fact independent of version numbering.
    prefix_edition: dict[str, tuple[str, str]] = {}
    for snap in snapshots_dir.glob("*_v*_*.json"):
        m = SNAPSHOT_RE.match(snap.name)
        if m:
            prefix_edition[elaws_id(m["reg"])] = (m["code"], m["edition"])

    rows: list[dict] = []
    for cache in sorted(cache_dir.glob("*_v*.html")):
        cm = CACHE_RE.match(cache.name)
        if not cm:
            continue
        prefix, version = cm["prefix"], int(cm["version"])
        edition = prefix_edition.get(prefix)
        if edition is None:
            print(f"  skip {cache.name}: prefix {prefix} maps to no edition", file=sys.stderr)
            continue
        period = extract_period(cache)
        if period is None:
            print(f"  skip {cache.name}: no period banner (stub/non-consolidation)", file=sys.stderr)
            continue
        code, edition_id = edition
        eff_from, eff_to = period
        rows.append(
            {
                "code": code,
                "edition": edition_id,
                "version": version,
                "url": f"{ELAWS_BASE_URL}{prefix}/v{version}",
                "effective_from": eff_from,
                "effective_to": eff_to,
            }
        )

    rows.sort(key=lambda r: (r["code"], r["edition"], r["version"]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ccm",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "CodeChronicleMapping",
        help="Path to the CodeChronicleMapping repo (default: sibling of this repo).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "elaws_consolidations.json",
        help="Where to write the consolidation map JSON.",
    )
    args = parser.parse_args()

    rows = build(args.ccm.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    by_edition: dict[str, int] = {}
    for r in rows:
        key = f"{r['code']} {r['edition']}"
        by_edition[key] = by_edition.get(key, 0) + 1
    print(f"Wrote {len(rows)} consolidation rows to {args.out}")
    for ed, n in sorted(by_edition.items()):
        print(f"  {ed}: {n} periods")


if __name__ == "__main__":
    main()
