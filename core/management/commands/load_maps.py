import json
from pathlib import Path
from typing import Optional

from coloured_logger import Logger
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import CodeEdition, CodeMap, CodeMapNode

logger = Logger(__name__)

try:
    import markdown as md
except ImportError:
    md = None


def _render_markdown(content: Optional[str]) -> Optional[str]:
    if not content:
        return None
    if not md:
        return None
    return md.markdown(content, extensions=["tables", "fenced_code"])


def _find_code_name_for_map_code(map_code: str) -> Optional[str]:
    edition = (
        CodeEdition.objects.filter(map_codes__contains=[map_code])
        .select_related("system")
        .order_by("-effective_date")
        .first()
    )
    return edition.code_name if edition else None


def _infer_code_name(map_code: str, data: dict) -> str:
    code_name = data.get("code_name")
    if code_name:
        return code_name

    code_name = _find_code_name_for_map_code(map_code)
    if code_name:
        return code_name

    code_field = data.get("code")
    version = data.get("version") or data.get("year")
    version_number = data.get("version_number")
    if code_field and version and version_number is not None:
        return f"{code_field}_{version}_v{int(version_number):02d}"
    if code_field and version:
        return f"{code_field}_{version}"
    if code_field:
        return code_field
    return map_code


class Command(BaseCommand):
    help = "Load building code maps from a directory into CodeMap and CodeMapNode tables."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            default=Path("..") / "CodeChronicle-Mapping" / "maps",
            help="Directory containing map JSON files.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Bulk insert batch size for nodes.",
        )

    def handle(self, *args, **options) -> None:
        source_dir = Path(options["source"]).expanduser().resolve()
        batch_size = options["batch_size"]

        if not source_dir.exists() or not source_dir.is_dir():
            raise CommandError(f"Source directory not found: {source_dir}")

        json_files = sorted(source_dir.glob("*.json"))
        if not json_files:
            raise CommandError(f"No JSON files found in {source_dir}")

        for json_file in json_files:
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as exc:
                logger.error("Skipping %s (invalid JSON): %s", json_file.name, exc)
                continue
            if md is None:
                logger.warning(
                    "python-markdown not installed; markdown content will be skipped for %s",
                    json_file.name,
                )

            map_code = json_file.stem
            code_name = _infer_code_name(map_code, data)

            markdown_count = 0
            html_count = 0
            with transaction.atomic():
                code_map, _created = CodeMap.objects.update_or_create(
                    map_code=map_code,
                    defaults={"code_name": code_name},
                )

                CodeMapNode.objects.filter(code_map=code_map).delete()

                node_cache: dict[str, CodeMapNode] = {}
                combined_entries = list(data.get("sections", [])) + list(data.get("tables", []))
                for section in combined_entries:
                    node_id = section.get("id")
                    if not node_id:
                        continue
                    keywords = section.get("keywords")
                    if not isinstance(keywords, list):
                        keywords = None
                    if section.get("markdown"):
                        markdown_count += 1
                    if section.get("html"):
                        html_count += 1
                    rendered_html = section.get("html") or _render_markdown(section.get("markdown"))
                    if node_id not in node_cache:
                        node_cache[node_id] = CodeMapNode(
                            code_map=code_map,
                            node_id=node_id,
                            title=section.get("title", ""),
                            page=section.get("page"),
                            page_end=section.get("page_end"),
                            html=rendered_html,
                            notes_html=section.get("notes_html"),
                            keywords=keywords,
                            bbox=section.get("bbox"),
                            parent_id=section.get("parent_id"),
                        )
                        continue

                    existing = node_cache[node_id]
                    if not existing.title and section.get("title"):
                        existing.title = section.get("title")
                    if existing.page is None and section.get("page") is not None:
                        existing.page = section.get("page")
                    if existing.page_end is None and section.get("page_end") is not None:
                        existing.page_end = section.get("page_end")
                    if not existing.html and rendered_html:
                        existing.html = rendered_html
                    if not existing.notes_html and section.get("notes_html"):
                        existing.notes_html = section.get("notes_html")
                    if existing.bbox is None and section.get("bbox") is not None:
                        existing.bbox = section.get("bbox")
                    if not existing.parent_id and section.get("parent_id"):
                        existing.parent_id = section.get("parent_id")
                    if keywords:
                        existing_keywords = set(existing.keywords or [])
                        existing.keywords = sorted(existing_keywords | set(keywords))

                nodes = list(node_cache.values())
                if nodes:
                    CodeMapNode.objects.bulk_create(nodes, batch_size=batch_size)

            logger.info(
                "Loaded %s: map_code=%s code_name=%s nodes=%d html=%d markdown=%d",
                json_file.name,
                map_code,
                code_name,
                len(nodes),
                html_count,
                markdown_count,
            )
