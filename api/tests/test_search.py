from datetime import date
from unittest.mock import patch

import pytest

from api.search import execute_search
from core.models import CodeEdition, CodeMap, CodeMapNode, CodeSystem, ProvinceCodeMap


@pytest.fixture
def mock_search_deps(db):
    with patch('api.search.get_applicable_codes') as mock_codes, \
         patch('api.search.get_map_codes') as mock_map_codes:
        mock_codes.return_value = ['NBC_2020', 'OBC_2024']
        mock_map_codes.side_effect = lambda code_name: {
            'NBC_2020': ['NBC'],
            'NBC_2025': ['NBC'],
            'OBC_2024': ['OBC_Vol1', 'OBC_Vol2'],
        }.get(code_name, [])
        yield mock_codes


@pytest.mark.django_db
def test_execute_search_basic(mock_search_deps):
    """Test search resolution with mocked dependencies."""
    params = {
        'date': '2024-01-01',
        'keywords': ['fire'],
        'province': 'ON'
    }

    nbc_map = CodeMap.objects.create(code_name='NBC_2020', map_code='NBC')
    CodeMapNode.objects.create(
        code_map=nbc_map,
        node_id='3.1.1.1',
        title='Fire Safety',
        page=50,
        page_end=52,
        keywords=['fire'],
        bbox={'l': 10, 't': 20, 'r': 30, 'b': 5},
    )
    obc_map = CodeMap.objects.create(code_name='OBC_2024', map_code='OBC_Vol1')
    CodeMapNode.objects.create(
        code_map=obc_map,
        node_id='3.1.1.1',
        title='Fire Safety',
        page=10,
        page_end=12,
        keywords=['fire'],
        html='<p>OBC content</p>',
    )

    response = execute_search(params)

    assert 'OBC_2024' in response['applicable_codes']
    assert len(response['results']) > 0
    assert response['results'][0]['id'] == '3.1.1.1'
    nbc_result = next(r for r in response['results'] if r['code_edition'] == 'NBC_2020')
    obc_result = next(r for r in response['results'] if r['code_edition'] == 'OBC_2024')
    assert nbc_result['bbox'] == {'l': 10, 't': 20, 'r': 30, 'b': 5}
    assert obc_result['html_content'] == '<p>OBC content</p>'


@pytest.mark.django_db
def test_execute_search_doors_fire_safety(mock_search_deps):
    """Test that a realistic query for doors/fire/safety in ON finds results."""
    mock_search_deps.return_value = ['OBC_2024', 'NBC_2025']

    obc_map = CodeMap.objects.create(code_name='OBC_2024', map_code='OBC_Vol1')
    CodeMapNode.objects.create(
        code_map=obc_map,
        node_id='3.1.8.1',
        title='Fire Separations',
        page=120,
        page_end=125,
        keywords=['fire', 'separations'],
    )
    CodeMapNode.objects.create(
        code_map=obc_map,
        node_id='3.1.8.5',
        title='Fire-Rated Doors',
        page=125,
        page_end=128,
        keywords=['fire', 'doors'],
    )
    nbc_map = CodeMap.objects.create(code_name='NBC_2025', map_code='NBC')
    CodeMapNode.objects.create(
        code_map=nbc_map,
        node_id='3.1.8.1',
        title='Fire Separations',
        page=220,
        page_end=225,
        keywords=['fire', 'separations'],
    )

    params = {
        'date': '2026-02-05',
        'keywords': ['doors', 'fire', 'safety'],
        'province': 'ON',
    }

    response = execute_search(params)

    assert response['result_count'] > 0
    assert len(response['results']) > 0
    assert 'OBC_2024' in response['applicable_codes']
    assert 'NBC_2025' in response['applicable_codes']


@pytest.mark.django_db
def test_get_applicable_codes_ontario_2026():
    """Test that ON province correctly resolves to OBC and NBC codes."""
    from config.code_metadata import get_applicable_codes

    obc = CodeSystem.objects.create(code="OBC", display_name="Ontario Building Code")
    nbc = CodeSystem.objects.create(code="NBC", display_name="National Building Code", is_national=True)
    ProvinceCodeMap.objects.create(province="ON", code_system=obc)
    CodeEdition.objects.create(
        system=obc,
        edition_id="2024",
        year=2024,
        map_codes=["OBC_Vol1", "OBC_Vol2"],
        effective_date=date(2025, 1, 1),
    )
    CodeEdition.objects.create(
        system=nbc,
        edition_id="2025",
        year=2025,
        map_codes=["NBC"],
        effective_date=date(2025, 1, 1),
    )

    codes = get_applicable_codes('ON', date(2026, 2, 5))

    assert 'OBC_2024' in codes
    assert 'NBC_2025' in codes


@pytest.mark.django_db
def test_get_applicable_codes_ontario_2010():
    """Test that a 2010 date resolves to a CCM OBC edition if loaded."""
    from config.code_metadata import get_applicable_codes

    obc = CodeSystem.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCodeMap.objects.create(province="ON", code_system=obc)
    CodeEdition.objects.create(
        system=obc,
        edition_id="2006_v01",
        year=2006,
        map_codes=["OBC_2006_v01"],
        effective_date=date(2006, 1, 1),
        superseded_date=date(2012, 1, 1),
        source="elaws",
    )

    codes = get_applicable_codes('ON', date(2010, 6, 1))
    obc_codes = [c for c in codes if c.startswith('OBC_')]
    assert len(obc_codes) == 1
    assert obc_codes[0].startswith('OBC_2006_v')


@pytest.mark.django_db
def test_execute_search_no_codes():
    """Test when no codes are found for the date."""
    with patch('api.search.get_applicable_codes') as mock_codes:
        mock_codes.return_value = []
        params = {
            'date': '1950-01-01',
            'keywords': ['fire'],
            'province': 'ON'
        }

        response = execute_search(params)
    assert 'error' in response
    assert response['results'] == []
