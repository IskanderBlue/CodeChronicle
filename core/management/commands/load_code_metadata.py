import json
from datetime import date
from pathlib import Path
from typing import Any

from coloured_logger import Logger
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import CodeEdition, CodeSystem, ProvinceCodeMap

logger = Logger(__name__)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


class Command(BaseCommand):
    help = "Load code metadata into the database from a metadata JSON/YAML file."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            default=Path("config") / "metadata.json",
            help="Path to JSON/YAML metadata file for code systems/editions.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear existing code metadata before loading.",
        )

    def handle(self, *args, **options) -> None:
        source_path = Path(options.get("source")).expanduser()
        reset = options.get("reset", False)

        metadata_payload = self._load_payload(source_path)

        with transaction.atomic():
            if reset:
                CodeEdition.objects.all().delete()
                ProvinceCodeMap.objects.all().delete()
                CodeSystem.objects.all().delete()

            self._load_from_payload(metadata_payload)

        logger.info("Code metadata load complete.")

    def _load_from_payload(self, payload: dict[str, Any]) -> None:
        code_editions = payload.get("code_editions", {})
        guide_editions = payload.get("guide_editions", {})
        display_names = payload.get("code_display_names", {})
        pdf_download_links = payload.get("pdf_download_links", {})
        province_map = payload.get("province_to_code", {})
        national_codes = set(payload.get("national_codes", []))

        systems = set(code_editions.keys()) | set(guide_editions.keys())
        for system_code in systems:
            document_type = "guide" if system_code in guide_editions else "code"
            CodeSystem.objects.update_or_create(
                code=system_code,
                defaults={
                    "display_name": display_names.get(system_code, ""),
                    "document_type": document_type,
                    "is_national": system_code in national_codes,
                },
            )

        for province, system_code in province_map.items():
            code_system = CodeSystem.objects.get(code=system_code)
            ProvinceCodeMap.objects.update_or_create(
                province=province,
                defaults={"code_system": code_system},
            )

        for system_code, editions in code_editions.items():
            code_system = CodeSystem.objects.get(code=system_code)
            for edition in editions:
                edition_id = edition["edition_id"]
                code_key = f"{system_code}_{edition_id}"
                download_url = pdf_download_links.get(code_key, "")
                CodeEdition.objects.update_or_create(
                    system=code_system,
                    edition_id=edition_id,
                    defaults={
                        "year": edition["year"],
                        "map_codes": edition.get("map_codes", []),
                        "effective_date": _parse_date(edition["effective_date"]),
                        "superseded_date": _parse_date(edition.get("superseded_date")),
                        "pdf_files": edition.get("pdf_files"),
                        "download_url": download_url,
                        "amendments": edition.get("amendments"),
                        "regulation": edition.get("regulation", ""),
                        "version_number": edition.get("version_number"),
                        "source": edition.get("source", ""),
                        "source_url": edition.get("source_url", ""),
                        "amendments_applied": edition.get("amendments_applied"),
                        "is_guide": False,
                    },
                )

        for system_code, editions in guide_editions.items():
            code_system = CodeSystem.objects.get(code=system_code)
            for edition in editions:
                edition_id = edition["edition_id"]
                code_key = f"{system_code}_{edition_id}"
                download_url = pdf_download_links.get(code_key, "")
                CodeEdition.objects.update_or_create(
                    system=code_system,
                    edition_id=edition_id,
                    defaults={
                        "year": edition["year"],
                        "map_codes": edition.get("map_codes", []),
                        "effective_date": _parse_date(edition["effective_date"]),
                        "superseded_date": _parse_date(edition.get("superseded_date")),
                        "pdf_files": edition.get("pdf_files"),
                        "download_url": download_url,
                        "amendments": edition.get("amendments"),
                        "regulation": edition.get("regulation", ""),
                        "version_number": edition.get("version_number"),
                        "source": edition.get("source", ""),
                        "source_url": edition.get("source_url", ""),
                        "amendments_applied": edition.get("amendments_applied"),
                        "is_guide": True,
                    },
                )

    def _load_payload(self, source_path: Path) -> dict[str, Any]:
        if not source_path.exists():
            raise CommandError(f"Metadata source not found: {source_path}")

        if source_path.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError as exc:
                raise CommandError("PyYAML is required to load YAML metadata.") from exc
            return yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}

        try:
            return json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Failed to parse metadata JSON: {exc}") from exc
