"""
Search execution logic combining applicability resolution and building-code-mcp.
"""

import os
import tempfile
from datetime import date
from typing import Any, Dict, List

import boto3
from building_code_mcp import BuildingCodeMCP
from django.conf import settings

from config.code_metadata import get_applicable_codes
from config.map_loader import map_cache


def _get_mcp_maps_dir() -> str:
    """
    Get the MCP maps directory path.
    Uses MCP_MAPS_DIR setting if set, otherwise downloads maps from S3.
    """
    # Local maps dir takes precedence (development)
    if settings.MCP_MAPS_DIR:
        return settings.MCP_MAPS_DIR

    # Production: download from S3 to temp directory
    if not settings.AWS_ACCESS_KEY_ID:
        raise RuntimeError(
            "MCP_MAPS_DIR not set and AWS credentials not configured. "
            "Set MCP_MAPS_DIR for local development or configure AWS for production."
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
                    print(f"Downloading map: {key}")
                    s3.download_file(settings.AWS_STORAGE_BUCKET_NAME, key, local_path)
    except Exception as e:
        print(f"Error downloading maps from S3: {e}")
        raise

    return temp_dir


# Initialize MCP server with resolved maps directory
maps_dir = _get_mcp_maps_dir()
mcp_server = BuildingCodeMCP(maps_dir=maps_dir)

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

    # Step 2: Search each code
    for code_name in applicable_codes:
        # Check if it's a "current" code supported by the package natively
        # or if we need to load a historical map.

        # For MVP, building-code-mcp search_code() might only support current codes.
        # If the code_name is in our historical metadata, we might need a custom search
        # through the cached map if the package doesn't support custom map injection.

        # Let's assume the package handles standard codes like NBC 2020, OBC 2024.

        # Prefix extraction (OBC_2024 -> OBC)
        base_code = code_name.split("_")[0]

        try:
            # Use building-code-mcp search
            # We use base_code to ensure we only search within the resolved jurisdiction
            # mcp_server is our singleton instance of BuildingCodeMCP

            # TODO: For custom historical maps (e.g., OBC 2006) not natively in the package,
            # we need to ensure they are loaded into the MCP server or handled here.
            # For now, we wrap in try/except to avoid crashing if the code isn't found.

            search_response = mcp_server.search_code(
                query=" ".join(keywords),
                code=base_code,
                limit=SEARCH_RESULT_LIMIT,
                verbose=True,
            )

            results = search_response.get("results", [])

            # If no results from package, check if we have a raw map cache for this edition
            # This is a fallback for stubs/historical data not yet fully integrated in MCP
            if not results:
                raw_map = map_cache.get_map(code_name)
                if raw_map:
                    # Simple keyword match on raw map for fallback
                    # This is very basic but ensures *something* returns for valid dates
                    # In a real impl, we'd have a better local search utility
                    print(f"Using fallback search for {code_name}")
                    # (Fallback logic omitted for brevity in MVP - just rely on MCP for now)

            # Add metadata to each result
            for result in results:
                result["code_edition"] = code_name
                result["source_date"] = search_date.isoformat()

            all_results.extend(results)
        except Exception as e:
            # If package fails (e.g., map not found), log it and continue
            print(f"Error searching {code_name}: {e}")

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
