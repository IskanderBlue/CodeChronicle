"""
Search execution logic combining applicability resolution and building-code-mcp.
"""

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import boto3
from building_code_mcp import BuildingCodeMCP
from coloured_logger import Logger
from django.conf import settings

from config.code_metadata import get_applicable_codes, get_map_codes

logger = Logger(__name__)


def _get_maps_dir() -> str:
    """
    Get the maps directory path.
    Uses MAPS_DIR setting if set, otherwise downloads maps from S3.
    """
    # Local maps dir takes precedence (development)
    if settings.MAPS_DIR:
        return settings.MAPS_DIR

    # Production: download from S3 to temp directory
    if not settings.AWS_ACCESS_KEY_ID:
        raise RuntimeError(
            "MAPS_DIR not set and AWS credentials not configured. "
            "Set MAPS_DIR for local development or configure AWS for production."
        )

    temp_dir = os.path.join(tempfile.gettempdir(), "mcp_maps")
    os.makedirs(temp_dir, exist_ok=True)

    s3 = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )

    # List and download all map files
    try:
        response = s3.list_objects_v2(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Prefix="",  # All files in bucket root
        )

        for obj in response.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json"):
                local_path = os.path.join(temp_dir, key)
                if not os.path.exists(local_path):
                    logger.info("Downloading map: %s", key)
                    s3.download_file(settings.AWS_STORAGE_BUCKET_NAME, key, local_path)
    except Exception as e:
        logger.error("Error downloading maps from S3: %s", e)
        raise

    return temp_dir


def _rekey_maps_by_stem(server: BuildingCodeMCP, directory: str) -> None:
    """
    Re-key maps that share a 'code' field by filename stem.

    BuildingCodeMCP._load_maps() keys by the JSON 'code' field, so CCM maps
    that all have "code": "OBC" overwrite each other. This reloads them
    keyed by filename stem (e.g. OBC_1997_v01) so each is individually
    searchable, while preserving the original key for non-CCM maps.
    """
    maps_path = Path(directory)
    if not maps_path.exists():
        return
    for json_file in maps_path.glob("*.json"):
        stem = json_file.stem
        if stem in server.maps or stem == "regulations":
            continue
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            code_field = data.get("code", stem)
            if code_field != stem:
                server.maps[stem] = data
        except Exception:
            pass


# Initialize MCP server with resolved maps directory
maps_dir = _get_maps_dir()
mcp_server = BuildingCodeMCP(maps_dir=maps_dir)

# Re-key maps by filename stem so CCM maps (which all share "code": "OBC")
# are individually addressable as OBC_1997_v01, OBC_2006_v03, etc.
_rekey_maps_by_stem(mcp_server, maps_dir)

SEARCH_RESULT_LIMIT = 10  # Unified limit for search results


def execute_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute search based on parsed parameters.
    """
    search_date_str = params.get("date")
    keywords = params.get("keywords", [])
    province = params.get("province", "ON")

    try:
        search_date = date.fromisoformat(search_date_str)
    except (ValueError, TypeError):
        search_date = date.today()

    # Step 1: Resolve applicable codes
    applicable_codes = get_applicable_codes(province, search_date)

    if not applicable_codes:
        return {"error": f"No building codes found for {province} on {search_date}", "results": []}

    all_results = []

    # Step 2: Search each code using MCP map identifiers
    for code_name in applicable_codes:
        map_codes = get_map_codes(code_name)
        if not map_codes:
            logger.warning("No map codes configured for %s, skipping", code_name)
            continue

        for map_code in map_codes:
            try:
                search_response = mcp_server.search_code(
                    query=" ".join(keywords),
                    code=map_code,
                    limit=SEARCH_RESULT_LIMIT,
                    verbose=True,
                )

                results = search_response.get("results", [])

                # Build lookups from map data (search_code doesn't return these)
                bbox_lookup: Dict[str, Any] = {}
                html_lookup: Dict[str, str] = {}
                map_data = mcp_server.maps.get(map_code, {})
                for section in map_data.get("sections", []):
                    sid = section["id"]
                    if section.get("bbox"):
                        bbox_lookup[sid] = section["bbox"]
                    if section.get("text") and not section.get("bbox"):
                        html_lookup[sid] = section["text"]

                # Tag each result with edition info and the specific map it came from
                for result in results:
                    result["code_edition"] = code_name
                    result["map_code"] = map_code
                    result["source_date"] = search_date.isoformat()
                    result["bbox"] = bbox_lookup.get(result.get("id"))
                    result["html_content"] = html_lookup.get(result.get("id"))

                all_results.extend(results)
            except Exception as e:
                logger.error("Error searching %s (map=%s): %s", code_name, map_code, e)

    # Step 3: Deduplicate and format
    unique_results = deduplicate_results(all_results)

    # Extract minimal metadata for history (top N)
    top_results_metadata = []
    for r in unique_results[:SEARCH_RESULT_LIMIT]:
        top_results_metadata.append(
            {
                "code": r.get("code_edition", "Unknown"),
                # Extract year from code string if possible, or source date
                "year": r.get("source_date", "")[:4],
                "section_id": r.get("id", ""),
                "title": r.get("title", "Untitled Section"),
            }
        )

    return {
        "applicable_codes": applicable_codes,
        "results": unique_results,
        "result_count": len(unique_results),
        "search_params": params,
        "top_results_metadata": top_results_metadata,
    }


def deduplicate_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate results based on section ID and code edition.
    """
    seen = set()
    unique = []

    for r in results:
        key = f"{r.get('code_edition')}:{r.get('id')}"
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique
