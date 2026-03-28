import json
from pathlib import Path
from typing import Optional

from coloured_logger import Logger
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from config.transitions import load_transitions
from core.models import CodeEdition, CodeMap, CodeMapNode, KeywordIDF

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


def _coerce_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_span_bounds(entry: dict) -> tuple[Optional[float], Optional[float]]:
    initial_page_top = _coerce_float(entry.get("initial_page_top"))
    final_page_bottom = _coerce_float(entry.get("final_page_bottom"))

    legacy_bbox = entry.get("bbox")
    if isinstance(legacy_bbox, dict):
        if initial_page_top is None:
            initial_page_top = _coerce_float(legacy_bbox.get("t"))
        if final_page_bottom is None:
            final_page_bottom = _coerce_float(legacy_bbox.get("b"))

    return initial_page_top, final_page_bottom


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


def _normalize_node_id(node_id: str) -> str:
    """Normalize a node ID by stripping a trailing dot for comparison."""
    return node_id.rstrip(".")


def _populate_provision_transitions() -> int:
    """Stamp provision_transitions onto matching CodeMapNodes.

    Returns the number of nodes updated.
    """
    try:
        records = load_transitions()
    except Exception as exc:
        logger.warning("Could not load transitions for provision stamping: %s", exc)
        return 0

    provision_records = [r for r in records if r.get("scope") == "provisions"]
    if not provision_records:
        return 0

    updated_count = 0
    for record in provision_records:
        new_edition = record["new_edition"]
        edition = (
            CodeEdition.objects.filter(edition_id=new_edition.split("_", 1)[-1])
            .select_related("system")
            .first()
        )
        if not edition:
            # Try matching by code_name property
            edition = None
            for candidate in CodeEdition.objects.select_related("system").all():
                if candidate.code_name == new_edition:
                    edition = candidate
                    break
        if not edition:
            logger.warning("No CodeEdition found for %s, skipping provision transitions", new_edition)
            continue

        map_codes = edition.map_codes or []
        if not map_codes:
            continue

        for provision in record.get("provisions", []):
            section_id = provision["new_section_id"]
            division = provision.get("new_division", "")
            normalized = _normalize_node_id(section_id)

            div_filter: dict[str, str] = {}
            if division:
                div_filter["division"] = division

            # Try exact match and trailing-dot-normalized match
            node = CodeMapNode.objects.filter(
                code_map__map_code__in=map_codes,
                node_id=section_id,
                **div_filter,
            ).first()
            if not node:
                node = CodeMapNode.objects.filter(
                    code_map__map_code__in=map_codes,
                    node_id=normalized,
                    **div_filter,
                ).first()
            if not node and not section_id.endswith("."):
                node = CodeMapNode.objects.filter(
                    code_map__map_code__in=map_codes,
                    node_id=section_id + ".",
                    **div_filter,
                ).first()

            if not node:
                logger.info(
                    "No CodeMapNode found for %s in map_codes=%s, skipping",
                    section_id, map_codes,
                )
                continue

            annotation = {
                "old_provision_ref": provision["old_provision_ref"],
                "as_read_on": provision["as_read_on"],
                "old_edition": record["old_edition"],
                "citation_text": record["citation_text"],
                "applicability_text": record["applicability_text"],
                "overlap_end": record["overlap_end"],
                "transition_type": record["transition_type"],
            }

            existing = node.provision_transitions or []
            # Avoid duplicate annotations
            if annotation not in existing:
                existing.append(annotation)
                node.provision_transitions = existing
                node.save(update_fields=["provision_transitions"])
                updated_count += 1

    return updated_count


class Command(BaseCommand):
    help = "Load building code maps from a directory into CodeMap and CodeMapNode tables."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            default=Path("..") / "CodeChronicleMapping" / "maps",
            help="Directory containing map JSON files.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Bulk insert batch size for nodes.",
        )
        parser.add_argument(
            "--elaws",
            action="store_true",
            help="Only load e-Laws OBC maps (OBC_*_v*.json).",
        )

    def handle(self, *args, **options) -> None:
        source_dir = Path(options["source"]).expanduser().resolve()
        batch_size = options["batch_size"]
        elaws_only = options["elaws"]

        if not source_dir.exists() or not source_dir.is_dir():
            raise CommandError(f"Source directory not found: {source_dir}")

        if elaws_only:
            json_files = sorted(source_dir.glob("OBC_*_v*.json"))
        else:
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

                node_cache: dict[tuple[str, str], CodeMapNode] = {}
                combined_entries = list(data.get("provisions", [])) + list(data.get("tables", []))
                for section in combined_entries:
                    node_id = section.get("id")
                    if not node_id:
                        continue
                    division = section.get("division", "")

                    initial_page_top, final_page_bottom = _extract_span_bounds(section)
                    keyword_counts = section.get("keyword_counts")
                    if not isinstance(keyword_counts, dict):
                        keyword_counts = None
                    if section.get("markdown"):
                        markdown_count += 1
                    if section.get("html"):
                        html_count += 1
                    rendered_html = section.get("html") or _render_markdown(section.get("markdown"))
                    cache_key = (node_id, division)
                    if cache_key not in node_cache:
                        node_cache[cache_key] = CodeMapNode(
                            code_map=code_map,
                            node_id=node_id,
                            title=section.get("title", ""),
                            page=section.get("page"),
                            page_end=section.get("page_end"),
                            initial_page_top=initial_page_top,
                            final_page_bottom=final_page_bottom,
                            html=rendered_html,
                            notes_html=section.get("notes_html"),
                            keyword_counts=keyword_counts,
                            parent_id=section.get("parent_id"),
                            division=division,
                        )
                        continue

                    existing = node_cache[cache_key]
                    if not existing.title and section.get("title"):
                        existing.title = section.get("title")
                    if existing.page is None and section.get("page") is not None:
                        existing.page = section.get("page")
                    if existing.page_end is None and section.get("page_end") is not None:
                        existing.page_end = section.get("page_end")
                    if existing.initial_page_top is None and initial_page_top is not None:
                        existing.initial_page_top = initial_page_top
                    if existing.final_page_bottom is None and final_page_bottom is not None:
                        existing.final_page_bottom = final_page_bottom
                    if not existing.html and rendered_html:
                        existing.html = rendered_html
                    if not existing.notes_html and section.get("notes_html"):
                        existing.notes_html = section.get("notes_html")
                    if not existing.parent_id and section.get("parent_id"):
                        existing.parent_id = section.get("parent_id")
                    if keyword_counts:
                        existing_kc = existing.keyword_counts or {}
                        for kw, ct in keyword_counts.items():
                            existing_kc[kw] = existing_kc.get(kw, 0) + ct
                        existing.keyword_counts = existing_kc

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

        # Post-load: stamp provision-scoped transitions onto matching nodes
        provision_count = _populate_provision_transitions()
        if provision_count:
            logger.info("Stamped provision_transitions on %d node(s)", provision_count)

        # Refresh keyword IDF materialized view
        try:
            KeywordIDF.refresh()
            logger.info("Refreshed keyword_idf materialized view")
        except Exception as exc:
            logger.warning("Could not refresh keyword_idf materialized view: %s", exc)
