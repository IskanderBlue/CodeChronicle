"""
Format search results for frontend display.
"""
import os
from typing import Any, Dict, List, Optional

from config.code_metadata import CODE_DISPLAY_NAMES, get_pdf_filename


def _build_code_display_name(code_edition: str) -> str:
    """Turn 'OBC_2024' into 'Ontario Building Code 2024'."""
    parts = code_edition.split("_", 1)
    prefix = parts[0]
    year = parts[1] if len(parts) > 1 else ""
    display = CODE_DISPLAY_NAMES.get(prefix, prefix)
    return f"{display} {year}".strip()


def _resolve_pdf(pdf_dir: str, code_edition: str, map_code: str) -> tuple[str | None, str]:
    """
    Check if a PDF exists for the given code edition + map code.
    Returns (pdf_url, expected_filename). pdf_url is None if not found.
    """
    filename = get_pdf_filename(code_edition, map_code)
    if not filename:
        return None, f'{map_code}.pdf'
    path = os.path.join(pdf_dir, filename)
    if os.path.isfile(path):
        return f'/pdf/{code_edition}/{map_code}/', filename
    return None, filename


def format_search_results(
    results: List[Dict[str, Any]],
    pdf_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Transform raw search results into a format suitable for the frontend.
    """
    formatted = []

    for result in results:
        code_edition = result.get('code_edition', 'Unknown')
        is_obc = 'OBC' in code_edition
        page = result.get('page')
        page_end = result.get('page_end', page)

        # Resolve PDF URL using map_code (e.g. OBC_Vol1, NBC) for file lookup
        pdf_url = None
        pdf_not_found = False
        pdf_expected = ''
        map_code = result.get('map_code', '')
        if pdf_dir and map_code:
            pdf_url, pdf_expected = _resolve_pdf(pdf_dir, code_edition, map_code)
            if not pdf_url:
                pdf_not_found = True
                print(f"PDF not found: {os.path.join(pdf_dir, pdf_expected)}")

        section_data = {
            'id': result.get('id'),
            'title': result.get('title', 'No title'),
            'code': code_edition,
            'code_display_name': _build_code_display_name(code_edition),
            'page': page,
            'page_end': page_end,
            'text_available': is_obc,  # OBC allows full text storage
            'text': result.get('text') if is_obc else None,
            'bbox': result.get('bbox'),
            'score': result.get('score', 0),
            'pdf_url': pdf_url,
            'pdf_not_found': pdf_not_found,
            'pdf_expected': pdf_expected if pdf_not_found else '',
        }

        # Amendment tracking (Placeholder for now)
        section_data['amendments'] = get_amendments_for_section(
            result.get('id'),
            code_edition
        )

        formatted.append(section_data)

    # Sort by relevance score (descending)
    formatted.sort(key=lambda x: x.get('score', 0), reverse=True)

    return formatted


def get_amendments_for_section(section_id: str, code_edition: str) -> List[Dict[str, Any]]:
    """
    Mock function to retrieve amendments for a specific section.
    Real data would come from the historical metadata or a DB.
    """
    # Placeholder: In a real implementation, we'd check CODE_EDITIONS
    # and match amendment dates to the search date.
    return []
