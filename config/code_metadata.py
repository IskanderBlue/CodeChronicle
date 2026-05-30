"""
Helpers for looking up code metadata stored in the database.
"""
from datetime import date
from typing import List, Optional

from django.db import models


def _find_edition(code_name: str):
    """Look up a CodeEdition model by code_name like 'OBC_2024' or 'OBC_2012_v38'."""
    parts = code_name.split('_', 1)
    if len(parts) != 2:
        return None
    system, edition_id = parts
    try:
        from core.models import CodeEdition
    except Exception:
        return None
    return (
        CodeEdition.objects.select_related("code")
        .filter(code__code=system, edition_id=edition_id)
        .first()
    )


def get_code_display_name(system_code: str) -> str:
    """
    Get the display name for a code system (e.g., OBC -> Ontario Building Code).
    """
    try:
        from core.models import Code
    except Exception:
        return system_code

    system = Code.objects.filter(code=system_code).first()
    if system and system.display_name:
        return system.display_name
    return system_code


def get_map_codes(code_name: str) -> List[str]:
    """
    Get map identifiers for a code edition name.

    e.g., 'OBC_2024' -> ['OBC_Vol1', 'OBC_Vol2']
          'OBC_2012_v38' -> ['OBC_2012_v38']
          'NBC_2025' -> ['NBC']
    """
    edition = _find_edition(code_name)
    return list(edition.map_codes) if edition else []


def get_source_url(code_name: str) -> Optional[str]:
    """
    Get the e-Laws source URL for a CCM code edition.

    e.g., 'OBC_1997_v10' -> 'https://www.ontario.ca/laws/regulation/970403/v10'
    Returns None for non-CCM editions.
    """
    edition = _find_edition(code_name)
    if not edition:
        return None
    return edition.source_url or None


def get_pdf_filename(code_name: str, map_code: str) -> Optional[str]:
    """
    Get the publisher PDF filename for a given code edition and map code.

    e.g., ('NBC_2025', 'NBC') -> 'NBC2025p1.pdf'
          ('OBC_2024', 'OBC_Vol1') -> '301880.pdf'
    Returns None for CCM editions (no publisher PDFs).
    """
    edition = _find_edition(code_name)
    if not edition or not edition.pdf_files:
        return None
    return edition.pdf_files.get(map_code)


def get_download_url(code_name: str) -> Optional[str]:
    """
    Get the publisher download URL for a code edition.

    e.g., 'NBC_2025' -> 'https://nrc-publications...'
    Returns None when no download URL is configured.
    """
    edition = _find_edition(code_name)
    if not edition:
        return None
    return edition.download_url or None


def get_pdf_expectations() -> list[dict[str, str | int | None]]:
    """
    Build PDF expectations from CodeEdition rows.
    """
    try:
        from core.models import CodeEdition
    except Exception:
        return []

    expectations: list[dict[str, str | int | None]] = []
    editions = CodeEdition.objects.select_related("code").all()
    for edition in editions:
        if not edition.pdf_files:
            continue
        for map_code, filename in edition.pdf_files.items():
            expectations.append(
                {
                    "system": edition.code.code,
                    "year": edition.year,
                    "effective_date": edition.effective_date.isoformat(),
                    "map_code": map_code,
                    "filename": filename,
                    "download_url": edition.download_url or None,
                }
            )
    expectations.sort(key=lambda row: (row["system"], row["year"], row["map_code"]))
    return expectations


def get_applicable_codes(province: str, search_date: date) -> List[str]:
    """
    Find which code editions were in effect at a given date.

    Returns a list of code names (e.g., ['OBC_2012_v17', 'NBC_2015'])
    """
    codes: list[str] = []

    try:
        from core.models import Code, CodeEdition, ProvinceCode
    except Exception:
        return codes

    # Per CCM contract: in-force window is [effective_date, ineffective_date).
    # superseded_date is the legacy field — ineffective_date is the
    # authoritative source going forward.  Filter on whichever is populated
    # so this stays correct during the transitional period.
    in_force = models.Q(effective_date__lte=search_date) & (
        models.Q(ineffective_date__isnull=True)
        | models.Q(ineffective_date__gt=search_date)
    )

    province_map = (
        ProvinceCode.objects.select_related("code")
        .filter(province=province)
        .first()
    )
    if province_map:
        edition = (
            CodeEdition.objects.filter(code=province_map.code)
            .filter(in_force)
            .order_by("-effective_date")
            .first()
        )
        if edition:
            codes.append(edition.code_name)

    national_systems = Code.objects.filter(is_national=True)
    for system in national_systems:
        edition = (
            CodeEdition.objects.filter(code=system)
            .filter(in_force)
            .order_by("-effective_date")
            .first()
        )
        if edition:
            codes.append(edition.code_name)

    return codes
