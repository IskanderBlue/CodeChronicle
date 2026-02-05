"""
Configuration for available building code editions and their metadata.
This file is a stub that will be populated with actual metadata later.
"""
from datetime import date
from typing import TypedDict, List, Optional


class Amendment(TypedDict):
    reg: str
    date: str  # ISO date string
    desc: str


class CodeEdition(TypedDict):
    year: int
    map_file: str
    effective_date: str  # ISO date string
    superseded_date: Optional[str]  # ISO date string or None
    amendments: List[Amendment]


# Master dictionary of code editions
# In a real scenario, this might come from a DB or a more complex JSON file
CODE_EDITIONS: dict[str, List[CodeEdition]] = {
    'OBC': [
        {
            'year': 2024,
            'map_file': 'OBC_2024.json',
            'effective_date': '2024-01-01',
            'superseded_date': None,
            'amendments': [
                {'reg': 'O. Reg. 163/24', 'date': '2024-01-01', 'desc': 'Base regulation'}
            ]
        },
        {
            'year': 2012,
            'map_file': 'OBC_2012.json',
            'effective_date': '2014-01-01',
            'superseded_date': '2024-01-01',
            'amendments': [
                {'reg': 'O. Reg. 332/12', 'date': '2014-01-01', 'desc': 'Base regulation'},
            ]
        },
        {
            'year': 2006,
            'map_file': 'OBC_2006.json',
            'effective_date': '2006-12-31',
            'superseded_date': '2014-01-01',
            'amendments': []
        },
    ],
    'NBC': [
        {
            'year': 2025,
            'map_file': 'NBC_2025.json',
            'effective_date': '2025-01-01',
            'superseded_date': None,
            'amendments': []
        },
        {
            'year': 2020,
            'map_file': 'NBC_2020.json',
            'effective_date': '2020-01-01',
            'superseded_date': '2025-01-01',
            'amendments': []
        },
        {
            'year': 2015,
            'map_file': 'NBC_2015.json',
            'effective_date': '2015-01-01',
            'superseded_date': '2020-01-01',
            'amendments': []
        },
    ]
}


def get_applicable_codes(province: str, search_date: date) -> List[str]:
    """
    Find which code editions were in effect at a given date.
    
    Returns a list of code names (e.g., ['OBC_2012', 'NBC_2015'])
    """
    codes = []
    
    # Check provincial code
    prov_editions = CODE_EDITIONS.get(province, [])
    for edition in prov_editions:
        effective = date.fromisoformat(edition['effective_date'])
        superseded = date.fromisoformat(edition['superseded_date']) if edition['superseded_date'] else date.max
        
        if effective <= search_date < superseded:
            codes.append(f"{province}_{edition['year']}")
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
