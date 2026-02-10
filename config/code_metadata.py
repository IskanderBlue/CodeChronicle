"""
Configuration for available building code editions and their metadata.

Editions come from two sources:
- Hardcoded seed entries (OBC 2024, NBC, NFC, NPC, NECB, BCBC, ABC, QCC, etc.)
- CCM regulations.json (loaded into the database via management commands)
"""
from datetime import date
from typing import Any, List, Optional, TypedDict

from django.db import models
from typing_extensions import NotRequired


class Amendment(TypedDict):
    reg: str
    date: str  # ISO date string
    desc: str


class CodeEdition(TypedDict):
    edition_id: str  # unique within system: "2024", "1997_v01", "2012_v38"
    year: int  # for display/grouping
    map_codes: List[str]  # map identifiers (keys in BuildingCodeMCP.maps)
    effective_date: str  # ISO date string
    superseded_date: NotRequired[Optional[str]]  # ISO date string or None
    pdf_files: NotRequired[dict[str, str]]  # map_code -> PDF filename
    amendments: NotRequired[List[Amendment]]
    regulation: NotRequired[str]  # e.g. "O. Reg. 332/12"
    version_number: NotRequired[int]  # CCM version number
    source: NotRequired[str]  # "elaws", "pdf", "mcp"
    source_url: NotRequired[str]  # elaws URL or download link
    amendments_applied: NotRequired[List[dict[str, Any]]]  # CCM amendment list
    is_guide: NotRequired[bool]


# Master dictionary of code editions
# map_codes must match the filename stem of the JSON maps loaded by BuildingCodeMCP.
# pdf_files maps each map_code to the actual PDF filename from the publisher.
CODE_EDITIONS: dict[str, List[CodeEdition]] = {
    # ── Ontario ──────────────────────────────────────────────────────────────
    'OBC': [
        {
            'edition_id': '2024',
            'year': 2024,
            'map_codes': ['OBC_Vol1', 'OBC_Vol2'],
            'pdf_files': {
                'OBC_Vol1': '301880.pdf',
                'OBC_Vol2': '301881.pdf',
            },
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': [
                {'reg': 'O. Reg. 163/24', 'date': '2024-01-01',
                 'desc': 'Base regulation'},
                {'reg': 'O. Reg. 447/24', 'date': '2024-11-04',
                 'desc': '2024 Compendium November update'},
                {'reg': 'O. Reg. 5/25', 'date': '2025-01-16',
                 'desc': '2024 Compendium January 2025 update'},
            ],
            'source': 'mcp',
        },
    ],
    # ── National ─────────────────────────────────────────────────────────────
    'NBC': [
        {
            'edition_id': '2025',
            'year': 2025,
            'map_codes': ['NBC'],
            'pdf_files': {'NBC': 'NBC2025p1.pdf'},
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': [],
        },
        {
            'edition_id': '2020',
            'year': 2020,
            'map_codes': ['NBC'],
            'pdf_files': {'NBC': 'NBC2020p1.pdf'},
            'effective_date': '2020-01-01',
            'superseded_date': '2025-01-01',
            'amendments': [],
        },
        {
            'edition_id': '2015',
            'year': 2015,
            'map_codes': ['NBC'],
            'pdf_files': {'NBC': 'NBC2015p1.pdf'},
            'effective_date': '2015-01-01',
            'superseded_date': '2020-01-01',
            'amendments': [],
        },
    ],
    'NFC': [
        {
            'edition_id': '2025',
            'year': 2025,
            'map_codes': ['NFC2025'],
            'pdf_files': {'NFC2025': 'NFC2025p1.pdf'},
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    'NPC': [
        {
            'edition_id': '2025',
            'year': 2025,
            'map_codes': ['NPC2025'],
            'pdf_files': {
                'NPC2025': 'National Plumbing Code of Canada 2020 2nd Print NPC2020p2.pdf',
            },
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    'NECB': [
        {
            'edition_id': '2025',
            'year': 2025,
            'map_codes': ['NECB2025'],
            'pdf_files': {'NECB2025': 'NECB2025p1.pdf'},
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    # ── British Columbia ─────────────────────────────────────────────────────
    'BCBC': [
        {
            'edition_id': '2024',
            'year': 2024,
            'map_codes': ['BCBC2024'],
            'pdf_files': {'BCBC2024': 'bcbc_2024_web_version_20240409.pdf'},
            'effective_date': '2024-03-08',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    # ── Alberta ──────────────────────────────────────────────────────────────
    'ABC': [
        {
            'edition_id': '2023',
            'year': 2023,
            'map_codes': ['ABC2023'],
            'pdf_files': {
                'ABC2023': '2023NBCAE-V1_National_Building_Code2023_Alberta_Edition.pdf',
            },
            'effective_date': '2024-05-01',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    # ── Quebec ───────────────────────────────────────────────────────────────
    'QCC': [
        {
            'edition_id': '2020',
            'year': 2020,
            'map_codes': ['QCC2020'],
            'pdf_files': {'QCC2020': 'QCC_2020p1.pdf'},
            'effective_date': '2025-04-17',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    'QECB': [
        {
            'edition_id': '2020',
            'year': 2020,
            'map_codes': ['QECB2020'],
            'pdf_files': {'QECB2020': 'QECB_2020p1.pdf'},
            'effective_date': '2024-07-13',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    'QPC': [
        {
            'edition_id': '2020',
            'year': 2020,
            'map_codes': ['QPC2020'],
            'pdf_files': {'QPC2020': 'QPC_2020p2 20250926.pdf'},
            'effective_date': '2024-07-11',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    'QSC': [
        {
            'edition_id': '2020',
            'year': 2020,
            'map_codes': ['QSC2020'],
            'pdf_files': {'QSC2020': 'QSC_2020p1.pdf'},
            'effective_date': '2025-04-17',
            'superseded_date': None,
            'amendments': [],
        },
    ],
}


# User guides — searchable via MCP but not enforceable code editions.
# Same structure as CodeEdition for consistency; effective_date is publication date.
GUIDE_EDITIONS: dict[str, List[CodeEdition]] = {
    'IUGP9': [
        {
            'edition_id': '2020',
            'year': 2020,
            'map_codes': ['IUGP9_2020'],
            'pdf_files': {'IUGP9_2020': 'IUGP9_2020p1.2025-01-30.pdf'},
            'effective_date': '2020-01-01',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    'UGP4': [
        {
            'edition_id': '2020',
            'year': 2020,
            'map_codes': ['UGP4_2020'],
            'pdf_files': {'UGP4_2020': 'UGP4_2020p1.pdf'},
            'effective_date': '2020-01-01',
            'superseded_date': None,
            'amendments': [],
        },
    ],
    'UGNECB': [
        {
            'edition_id': '2020',
            'year': 2020,
            'map_codes': ['UGNECB_2020'],
            'pdf_files': {'UGNECB_2020': 'UGNECB_2020p1.2024-10-29.pdf'},
            'effective_date': '2020-01-01',
            'superseded_date': None,
            'amendments': [],
        },
    ],
}


# Human-readable names for code systems
CODE_DISPLAY_NAMES: dict[str, str] = {
    'OBC': 'Ontario Building Code',
    'NBC': 'National Building Code',
    'NFC': 'National Fire Code',
    'NPC': 'National Plumbing Code',
    'NECB': 'National Energy Code for Buildings',
    'BCBC': 'BC Building Code',
    'ABC': 'Alberta Building Code',
    'QCC': 'Quebec Construction Code (Building)',
    'QECB': 'Quebec Energy Code for Buildings',
    'QPC': 'Quebec Plumbing Code',
    'QSC': 'Quebec Safety Code (Fire)',
    'IUGP9': 'Illustrated User\'s Guide \u2013 NBC Part 9',
    'UGP4': 'User\'s Guide \u2013 NBC Part 4 Structural Commentaries',
    'UGNECB': 'User\'s Guide \u2013 NECB',
}

PDF_DOWNLOAD_LINKS: dict[str, str] = {
    'NBC_2025': 'https://nrc-publications.canada.ca/eng/view/object/?id=adf1ad94-7ea8-4b08-a19f-653ebb7f45f6',
    'NFC_2025': 'https://nrc-publications.canada.ca/eng/view/object/?id=e8a18373-a824-42d5-8823-bfad854c2ebd',
    'NPC_2025': 'https://nrc-publications.canada.ca/eng/view/object/?id=6e7cabf5-d83e-4efd-9a1c-6515fc7cdc71',
    'NECB_2025': 'https://nrc-publications.canada.ca/eng/view/object/?id=0d558a8e-28fe-4b5d-bb73-35b5a3703e8b',
    'OBC_2024': 'https://www.publications.gov.on.ca/browse-catalogues/building-code-and-guides/2024-ontarios-building-code-compendium-updated-to-january-16-2025-two-volume-pdf-set-kit/',
    'BCBC_2024': 'https://www2.gov.bc.ca/gov/content/industry/construction-industry/building-codes-standards/bc-codes/2024-bc-codes',
    'ABC_2023': 'https://nrc-publications.canada.ca/eng/view/object/?id=0316d953-0d55-4311-af69-cad55efec499',
    'QCC_2020': 'https://nrc-publications.canada.ca/eng/view/object/?id=fbb47c66-fcda-4d5b-a045-882dfa80ab0e',
    'QECB_2020': 'https://nrc-publications.canada.ca/eng/view/object/?id=ad5eaa41-7532-4cbb-9a1e-49c54b25371e',
    'QPC_2020': 'https://nrc-publications.canada.ca/eng/view/object/?id=4931b15f-9344-43b6-a0f3-446b7b25c410',
    'QSC_2020': 'https://nrc-publications.canada.ca/eng/view/object/?id=6a46f33c-2fc3-4d85-8ee7-34e6780e4bf5',
    'IUGP9_2020': 'https://nrc-publications.canada.ca/eng/view/object/?id=a7a505fa-519c-436b-a23b-6f418df87e6a',
    'UGP4_2020': 'https://nrc-publications.canada.ca/eng/view/object/?id=b9fddc27-86f2-496b-9aa4-b66c45164ba6',
    'UGNECB_2020': 'https://nrc-publications.canada.ca/eng/view/object/?id=c6504d98-2da4-43c5-a8f6-360d6e640f88',
}


# Map province abbreviations to provincial code systems
PROVINCE_TO_CODE: dict[str, str] = {
    'ON': 'OBC',
    'BC': 'BCBC',
    'AB': 'ABC',
    'QC': 'QCC',
}

# National code systems — searched for all provinces alongside provincial codes.
NATIONAL_CODES: list[str] = ['NBC', 'NFC', 'NPC', 'NECB']


# CCM editions are loaded into the database via management commands.


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
        CodeEdition.objects.select_related("system")
        .filter(system__code=system, edition_id=edition_id)
        .first()
    )


def get_code_display_name(system_code: str) -> str:
    """
    Get the display name for a code system (e.g., OBC -> Ontario Building Code).
    """
    try:
        from core.models import CodeSystem
    except Exception:
        return system_code

    system = CodeSystem.objects.filter(code=system_code).first()
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


def get_pdf_expectations() -> list[dict[str, str | int | None]]:
    """
    Build PDF expectations from CodeEdition rows.
    """
    try:
        from core.models import CodeEdition
    except Exception:
        return []

    expectations: list[dict[str, str | int | None]] = []
    editions = CodeEdition.objects.select_related("system").all()
    for edition in editions:
        if not edition.pdf_files:
            continue
        for map_code, filename in edition.pdf_files.items():
            expectations.append(
                {
                    "system": edition.system.code,
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
        from core.models import CodeEdition, CodeSystem, ProvinceCodeMap
    except Exception:
        return codes

    province_map = (
        ProvinceCodeMap.objects.select_related("code_system")
        .filter(province=province)
        .first()
    )
    if province_map:
        edition = (
            CodeEdition.objects.filter(system=province_map.code_system)
            .filter(effective_date__lte=search_date)
            .filter(models.Q(superseded_date__isnull=True) | models.Q(superseded_date__gt=search_date))
            .order_by("-effective_date")
            .first()
        )
        if edition:
            codes.append(edition.code_name)

    national_systems = CodeSystem.objects.filter(is_national=True)
    for system in national_systems:
        edition = (
            CodeEdition.objects.filter(system=system)
            .filter(effective_date__lte=search_date)
            .filter(models.Q(superseded_date__isnull=True) | models.Q(superseded_date__gt=search_date))
            .order_by("-effective_date")
            .first()
        )
        if edition:
            codes.append(edition.code_name)

    return codes
