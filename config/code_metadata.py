"""
Configuration for available building code editions and their metadata.
"""
from datetime import date
from typing import List, Optional, TypedDict


class Amendment(TypedDict):
    reg: str
    date: str  # ISO date string
    desc: str


class CodeEdition(TypedDict):
    year: int
    map_codes: List[str]  # MCP map identifiers (keys in BuildingCodeMCP.maps)
    pdf_files: dict[str, str]  # map_code -> PDF filename as downloaded from publisher
    effective_date: str  # ISO date string
    superseded_date: Optional[str]  # ISO date string or None
    amendments: List[Amendment]


# Master dictionary of code editions
# map_codes must match the filename stem of the JSON maps loaded by BuildingCodeMCP.
# pdf_files maps each map_code to the actual PDF filename from the publisher.
CODE_EDITIONS: dict[str, List[CodeEdition]] = {
    # ── Ontario ──────────────────────────────────────────────────────────────
    'OBC': [
        {
            'year': 2024,
            'map_codes': ['OBC_Vol1', 'OBC_Vol2'],
            'pdf_files': {
                'OBC_Vol1': '301880.pdf',
                'OBC_Vol2': '301881.pdf',
            },
            'effective_date': '2024-01-01',
            'superseded_date': None,
            'amendments': [
                {'reg': 'O. Reg. 163/24', 'date': '2024-01-01',
                 'desc': 'Base regulation'},
                {'reg': 'O. Reg. 447/24', 'date': '2024-11-04',
                 'desc': '2024 Compendium November update'},
                {'reg': 'O. Reg. 5/25', 'date': '2025-01-16',
                 'desc': '2024 Compendium January 2025 update'},
            ]
        },
        {
            'year': 2012,
            'map_codes': ['OBC_Vol1', 'OBC_Vol2'],
            'pdf_files': {
                'OBC_Vol1': 'OBC2012v1.pdf',
                'OBC_Vol2': 'OBC2012v2.pdf',
            },
            'effective_date': '2014-01-01',
            'superseded_date': '2024-01-01',
            'amendments': [
                {'reg': 'O. Reg. 332/12', 'date': '2014-01-01',
                 'desc': 'Base regulation'},
            ]
        },
        {
            'year': 2006,
            'map_codes': ['OBC_Vol1', 'OBC_Vol2'],
            'pdf_files': {
                'OBC_Vol1': 'OBC2006v1.pdf',
                'OBC_Vol2': 'OBC2006v2.pdf',
            },
            'effective_date': '2006-12-31',
            'superseded_date': '2014-01-01',
            'amendments': []
        },
    ],
    # ── National ─────────────────────────────────────────────────────────────
    'NBC': [
        {
            'year': 2025,
            'map_codes': ['NBC'],
            'pdf_files': {'NBC': 'NBC2025p1.pdf'},
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': []
        },
        {
            'year': 2020,
            'map_codes': ['NBC'],
            'pdf_files': {'NBC': 'NBC2020p1.pdf'},
            'effective_date': '2020-01-01',
            'superseded_date': '2025-01-01',
            'amendments': []
        },
        {
            'year': 2015,
            'map_codes': ['NBC'],
            'pdf_files': {'NBC': 'NBC2015p1.pdf'},
            'effective_date': '2015-01-01',
            'superseded_date': '2020-01-01',
            'amendments': []
        },
    ],
    'NFC': [
        {
            'year': 2025,
            'map_codes': ['NFC2025'],
            'pdf_files': {'NFC2025': 'NFC2025p1.pdf'},
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': []
        },
    ],
    'NPC': [
        {
            'year': 2025,
            'map_codes': ['NPC2025'],
            'pdf_files': {
                'NPC2025': 'National Plumbing Code of Canada 2020 2nd Print NPC2020p2.pdf',
            },
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': []
        },
    ],
    'NECB': [
        {
            'year': 2025,
            'map_codes': ['NECB2025'],
            'pdf_files': {'NECB2025': 'NECB2025p1.pdf'},
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': []
        },
    ],
    # ── British Columbia ─────────────────────────────────────────────────────
    'BCBC': [
        {
            'year': 2024,
            'map_codes': ['BCBC2024'],
            'pdf_files': {'BCBC2024': 'bcbc_2024_web_version_20240409.pdf'},
            'effective_date': '2024-03-08',
            'superseded_date': None,
            'amendments': []
        },
    ],
    # ── Alberta ──────────────────────────────────────────────────────────────
    'ABC': [
        {
            'year': 2023,
            'map_codes': ['ABC2023'],
            'pdf_files': {
                'ABC2023': '2023NBCAE-V1_National_Building_Code2023_Alberta_Edition.pdf',
            },
            'effective_date': '2024-05-01',
            'superseded_date': None,
            'amendments': []
        },
    ],
    # ── Quebec ───────────────────────────────────────────────────────────────
    'QCC': [
        {
            'year': 2020,
            'map_codes': ['QCC2020'],
            'pdf_files': {'QCC2020': 'QCC_2020p1.pdf'},
            'effective_date': '2025-04-17',
            'superseded_date': None,
            'amendments': []
        },
    ],
    'QECB': [
        {
            'year': 2020,
            'map_codes': ['QECB2020'],
            'pdf_files': {'QECB2020': 'QECB_2020p1.pdf'},
            'effective_date': '2024-07-13',
            'superseded_date': None,
            'amendments': []
        },
    ],
    'QPC': [
        {
            'year': 2020,
            'map_codes': ['QPC2020'],
            'pdf_files': {'QPC2020': 'QPC_2020p2 20250926.pdf'},
            'effective_date': '2024-07-11',
            'superseded_date': None,
            'amendments': []
        },
    ],
    'QSC': [
        {
            'year': 2020,
            'map_codes': ['QSC2020'],
            'pdf_files': {'QSC2020': 'QSC_2020p1.pdf'},
            'effective_date': '2025-04-17',
            'superseded_date': None,
            'amendments': []
        },
    ],
}


# User guides — searchable via MCP but not enforceable code editions.
# Same structure as CodeEdition for consistency; effective_date is publication date.
GUIDE_EDITIONS: dict[str, List[CodeEdition]] = {
    'IUGP9': [
        {
            'year': 2020,
            'map_codes': ['IUGP9_2020'],
            'pdf_files': {'IUGP9_2020': 'IUGP9_2020p1.2025-01-30.pdf'},
            'effective_date': '2020-01-01',
            'superseded_date': None,
            'amendments': []
        },
    ],
    'UGP4': [
        {
            'year': 2020,
            'map_codes': ['UGP4_2020'],
            'pdf_files': {'UGP4_2020': 'UGP4_2020p1.pdf'},
            'effective_date': '2020-01-01',
            'superseded_date': None,
            'amendments': []
        },
    ],
    'UGNECB': [
        {
            'year': 2020,
            'map_codes': ['UGNECB_2020'],
            'pdf_files': {'UGNECB_2020': 'UGNECB_2020p1.2024-10-29.pdf'},
            'effective_date': '2020-01-01',
            'superseded_date': None,
            'amendments': []
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


PDF_EXPECTATIONS: list[dict[str, str | int]] = []
for _system, _editions in {**CODE_EDITIONS, **GUIDE_EDITIONS}.items():
    for _edition in _editions:
        _year = _edition["year"]
        _effective_date = _edition["effective_date"]
        for _map_code, _filename in _edition.get("pdf_files", {}).items():
            PDF_EXPECTATIONS.append(
                {
                    "system": _system,
                    "year": _year,
                    "effective_date": _effective_date,
                    "map_code": _map_code,
                    "filename": _filename,
                }
            )
PDF_EXPECTATIONS.sort(key=lambda row: (row["system"], row["year"], row["map_code"]))


# Map province abbreviations to provincial code systems
PROVINCE_TO_CODE: dict[str, str] = {
    'ON': 'OBC',
    'BC': 'BCBC',
    'AB': 'ABC',
    'QC': 'QCC',
}

# National code systems — searched for all provinces alongside provincial codes.
NATIONAL_CODES: list[str] = ['NBC', 'NFC', 'NPC', 'NECB']


def _find_edition(code_name: str) -> Optional[CodeEdition]:
    """Look up a CodeEdition dict by code_name like 'OBC_2024'."""
    parts = code_name.split('_', 1)
    if len(parts) != 2:
        return None
    system, year_str = parts
    try:
        year = int(year_str)
    except ValueError:
        return None
    for edition in CODE_EDITIONS.get(system, []):
        if edition['year'] == year:
            return edition
    # Also check guides
    for edition in GUIDE_EDITIONS.get(system, []):
        if edition['year'] == year:
            return edition
    return None


def get_map_codes(code_name: str) -> List[str]:
    """
    Get MCP map identifiers for a code edition name.

    e.g., 'OBC_2024' -> ['OBC_Vol1', 'OBC_Vol2']
          'NBC_2025' -> ['NBC']
    """
    edition = _find_edition(code_name)
    return edition['map_codes'] if edition else []


def get_pdf_filename(code_name: str, map_code: str) -> Optional[str]:
    """
    Get the publisher PDF filename for a given code edition and map code.

    e.g., ('NBC_2025', 'NBC') -> 'NBC2025p1.pdf'
          ('OBC_2024', 'OBC_Vol1') -> '301880.pdf'
    """
    edition = _find_edition(code_name)
    if not edition:
        return None
    return edition.get('pdf_files', {}).get(map_code)


def get_applicable_codes(province: str, search_date: date) -> List[str]:
    """
    Find which code editions were in effect at a given date.

    Returns a list of code names (e.g., ['OBC_2012', 'NBC_2015'])
    """
    codes = []

    # Check provincial code
    code_system = PROVINCE_TO_CODE.get(province)
    prov_editions = CODE_EDITIONS.get(code_system, []) if code_system else []
    for edition in prov_editions:
        effective = date.fromisoformat(edition['effective_date'])
        superseded = (
            date.fromisoformat(edition['superseded_date'])
            if edition['superseded_date']
            else date.max
        )

        if effective <= search_date < superseded:
            codes.append(f"{code_system}_{edition['year']}")
            break

    # Check federal code (NBC)
    nbc_editions = CODE_EDITIONS.get('NBC', [])
    for edition in nbc_editions:
        effective = date.fromisoformat(edition['effective_date'])
        superseded = (
            date.fromisoformat(edition['superseded_date'])
            if edition['superseded_date']
            else date.max
        )

        if effective <= search_date < superseded:
            codes.append(f"NBC_{edition['year']}")
            break

    return codes
