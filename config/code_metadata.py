"""
Configuration for available building code editions and their metadata.
This file is a stub that will be populated with actual metadata later.
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
# map_codes must match the 'code' field (or filename stem) of the JSON maps
# loaded by BuildingCodeMCP. OBC is split into two volumes.
# pdf_files maps each map_code to the actual PDF filename from the publisher.
CODE_EDITIONS: dict[str, List[CodeEdition]] = {
    'OBC': [
        {
            'year': 2024,
            'map_codes': ['OBC_Vol1', 'OBC_Vol2'],
            'pdf_files': {
                'OBC_Vol1': 'OBC2024v1.pdf',
                'OBC_Vol2': 'OBC2024v2.pdf',
            },
            'effective_date': '2024-01-01',
            'superseded_date': None,
            'amendments': [
                {'reg': 'O. Reg. 163/24', 'date': '2024-01-01', 'desc': 'Base regulation'}
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
                {'reg': 'O. Reg. 332/12', 'date': '2014-01-01', 'desc': 'Base regulation'},
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
    ]
}


# Human-readable names for code systems
CODE_DISPLAY_NAMES: dict[str, str] = {
    'OBC': 'Ontario Building Code',
    'NBC': 'National Building Code',
}


# Map province abbreviations to provincial code systems
PROVINCE_TO_CODE = {
    'ON': 'OBC',
}


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
          ('OBC_2024', 'OBC_Vol1') -> 'OBC2024v1.pdf'
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
        superseded = date.fromisoformat(edition['superseded_date']) if edition['superseded_date'] else date.max

        if effective <= search_date < superseded:
            codes.append(f"{code_system}_{edition['year']}")
            break

    # Check federal code (NBC)
    nbc_editions = CODE_EDITIONS.get('NBC', [])
    for edition in nbc_editions:
        effective = date.fromisoformat(edition['effective_date'])
        superseded = date.fromisoformat(edition['superseded_date']) if edition['superseded_date'] else date.max

        if effective <= search_date < superseded:
            codes.append(f"NBC_{edition['year']}")
            break

    return codes
