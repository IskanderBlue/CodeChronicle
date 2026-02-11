"""
Format search results for frontend display.
"""

from typing import Any, Dict, List

from config.code_metadata import get_code_display_name, get_pdf_filename, get_source_url


def _build_code_display_name(code_edition: str) -> str:
    """Turn 'OBC_2024' into 'Ontario Building Code 2024'."""
    parts = code_edition.split("_", 1)
    prefix = parts[0]
    year = parts[1] if len(parts) > 1 else ""
    display = get_code_display_name(prefix)
    return f"{display} {year}".strip()


def format_search_results(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Transform raw search results into a format suitable for the frontend.
    """
    formatted = []

    for result in results:
        code_edition = result.get("code_edition", "Unknown")
        page = result.get("page")
        page_end = result.get("page_end", page)

        # PDF filename derived from map_code (e.g. OBC_Vol1, NBC)
        pdf_filename = ""
        map_code = result.get("map_code", "")
        if map_code:
            pdf_filename = get_pdf_filename(code_edition, map_code) or ""

        html_content = result.get("html_content")
        source_url = get_source_url(code_edition)

        section_data = {
            "id": result.get("id"),
            "title": result.get("title", "No title"),
            "code": code_edition,
            "code_display_name": _build_code_display_name(code_edition),
            "page": page,
            "page_end": page_end,
            "bbox": result.get("bbox"),
            "score": result.get("score", 0),
            "pdf_filename": pdf_filename,
            "html_content": html_content,
            "source_url": source_url,
        }

        # Amendment tracking (Placeholder for now)
        section_data["amendments"] = get_amendments_for_section(result.get("id"), code_edition)

        formatted.append(section_data)

    # Sort by relevance score (descending)
    formatted.sort(key=lambda x: x.get("score", 0), reverse=True)

    return formatted


def get_amendments_for_section(section_id: str, code_edition: str) -> List[Dict[str, Any]]:
    """
    Mock function to retrieve amendments for a specific section.
    Real data would come from the historical metadata or a DB.
    """
    return []

