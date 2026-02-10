import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from config import code_metadata

CCM_REGULATIONS_PATH = Path("..") / "CodeChronicle-Mapping" / "data" / "regulations.json"


def _ccm_entry_to_edition(entry: dict[str, Any]) -> dict[str, Any]:
    version = entry["version"]
    version_number = entry["version_number"]
    output_stem = entry["output_file"].removesuffix(".json")
    edition_id = f"{version}_v{version_number:02d}"
    edition = {
        "edition_id": edition_id,
        "year": int(version),
        "map_codes": [output_stem],
        "effective_date": entry["effective_date"],
        "source": entry.get("source", ""),
        "regulation": entry.get("regulation", ""),
        "version_number": version_number,
        "source_url": entry.get("elaws_url", ""),
        "amendments_applied": entry.get("amendments_applied"),
    }
    return edition


def _compute_superseded_dates(
    editions: list[dict[str, Any]],
    next_effective: str | None,
) -> None:
    editions.sort(key=lambda e: e["effective_date"])
    for index, edition in enumerate(editions):
        if index + 1 < len(editions):
            edition["superseded_date"] = editions[index + 1]["effective_date"]
        else:
            edition["superseded_date"] = next_effective


def _expand_obc_from_ccm(code_editions: dict[str, list[dict[str, Any]]]) -> bool:
    if not CCM_REGULATIONS_PATH.exists():
        return False

    data = json.loads(CCM_REGULATIONS_PATH.read_text(encoding="utf-8"))
    obc_entries = [e for e in data.get("OBC", []) if e.get("effective_date")]
    if not obc_entries:
        return False

    ccm_editions = [_ccm_entry_to_edition(entry) for entry in obc_entries]

    obc_editions = code_editions.get("OBC", [])
    obc_2024 = next((e for e in obc_editions if e.get("edition_id") == "2024"), None)
    next_effective = obc_2024.get("effective_date") if obc_2024 else None
    _compute_superseded_dates(ccm_editions, next_effective)

    existing_ids = {e.get("edition_id") for e in obc_editions}
    merged = [e for e in ccm_editions if e.get("edition_id") not in existing_ids]
    code_editions["OBC"] = merged + obc_editions
    return True


class Command(BaseCommand):
    help = "Export code metadata constants to a JSON file."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--output",
            default=Path("config") / "metadata.json",
            help="Output JSON path (default: config/metadata.json).",
        )

    def handle(self, *args, **options) -> None:
        output_path = Path(options["output"]).expanduser().resolve()
        code_editions = {k: list(v) for k, v in code_metadata.CODE_EDITIONS.items()}
        expanded = _expand_obc_from_ccm(code_editions)
        if not expanded:
            self.stderr.write(
                f"CCM regulations not found at {CCM_REGULATIONS_PATH}; exporting constants only."
            )

        payload = {
            "code_editions": code_editions,
            "guide_editions": code_metadata.GUIDE_EDITIONS,
            "code_display_names": code_metadata.CODE_DISPLAY_NAMES,
            "pdf_download_links": code_metadata.PDF_DOWNLOAD_LINKS,
            "province_to_code": code_metadata.PROVINCE_TO_CODE,
            "national_codes": code_metadata.NATIONAL_CODES,
        }
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.stdout.write(f"Exported metadata to {output_path}")
