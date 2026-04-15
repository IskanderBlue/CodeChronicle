from datetime import date

import pytest

from api.search import execute_search
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvinceCode,
)


def _create_obc_fixtures():
    """Create OBC system with provisions for ON province."""
    obc = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=obc)

    obc_edition = CodeEdition.objects.create(
        system=obc,
        edition_id="2024",
        year=2024,
        map_codes=["OBC_Vol1", "OBC_Vol2"],
        effective_date=date(2024, 1, 1),
    )

    obc_provision = CodeEditionProvision.objects.create(
        edition=obc_edition,
        provision_id="3.1.1.1",
        level=CodeEditionProvision.Level.ARTICLE,
        division="B",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=obc_provision,
        version=0,
        effective_date=date(2024, 1, 1),
        title="Fire Safety",
        html="<p>OBC content</p>",
        keyword_counts={"fire": 1},
    )

    return obc, obc_edition


@pytest.mark.django_db
def test_execute_search_basic():
    """Test search resolution with real DB fixtures."""
    _create_obc_fixtures()

    params = {"date": "2024-01-01", "keywords": ["fire"], "province": "ON"}
    response = execute_search(params)

    assert "OBC_2024" in response["applicable_codes"]
    assert len(response["results"]) > 0
    assert response["results"][0]["id"] == "3.1.1.1"

    obc_result = next(r for r in response["results"] if r["code_edition"] == "OBC_2024")
    assert obc_result["html_content"] == "<p>OBC content</p>"


@pytest.mark.django_db
def test_execute_search_doors_fire_safety():
    """Test that a realistic query for doors/fire/safety in ON finds OBC results."""
    obc = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=obc)

    obc_edition = CodeEdition.objects.create(
        system=obc,
        edition_id="2024",
        year=2024,
        map_codes=["OBC_Vol1", "OBC_Vol2"],
        effective_date=date(2024, 1, 1),
    )

    # OBC provisions
    obc_p1 = CodeEditionProvision.objects.create(
        edition=obc_edition,
        provision_id="3.1.8.1",
        level=CodeEditionProvision.Level.ARTICLE,
        division="B",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=obc_p1,
        version=0,
        effective_date=date(2024, 1, 1),
        title="Fire Separations",
        keyword_counts={"fire": 1, "separations": 1},
    )
    obc_p2 = CodeEditionProvision.objects.create(
        edition=obc_edition,
        provision_id="3.1.8.5",
        level=CodeEditionProvision.Level.ARTICLE,
        division="B",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=obc_p2,
        version=0,
        effective_date=date(2024, 1, 1),
        title="Fire-Rated Doors",
        keyword_counts={"fire": 1, "doors": 1},
    )

    params = {
        "date": "2026-02-05",
        "keywords": ["doors", "fire", "safety"],
        "province": "ON",
    }
    response = execute_search(params)

    assert response["result_count"] > 0
    assert len(response["results"]) > 0
    assert "OBC_2024" in response["applicable_codes"]


@pytest.mark.django_db
def test_get_applicable_codes_ontario_2026():
    """Test that ON province correctly resolves to OBC and NBC codes."""
    from config.code_metadata import get_applicable_codes

    obc = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    nbc = Code.objects.create(
        code="NBC", display_name="National Building Code", is_national=True
    )
    ProvinceCode.objects.create(province="ON", code=obc)
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

    codes = get_applicable_codes("ON", date(2026, 2, 5))

    assert "OBC_2024" in codes
    assert "NBC_2025" in codes


@pytest.mark.django_db
def test_get_applicable_codes_ontario_2010():
    """Test that a 2010 date resolves to a CCM OBC edition if loaded."""
    from config.code_metadata import get_applicable_codes

    obc = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=obc)
    CodeEdition.objects.create(
        system=obc,
        edition_id="2006_v01",
        year=2006,
        map_codes=["OBC_2006_v01"],
        effective_date=date(2006, 1, 1),
        superseded_date=date(2012, 1, 1),
        source="elaws",
    )

    codes = get_applicable_codes("ON", date(2010, 6, 1))
    obc_codes = [c for c in codes if c.startswith("OBC_")]
    assert len(obc_codes) == 1
    assert obc_codes[0].startswith("OBC_2006_v")


@pytest.mark.django_db
def test_execute_search_no_codes():
    """Test when no codes are found — province has no ProvinceCode mapping."""
    params = {"date": "1950-01-01", "keywords": ["fire"], "province": "XX"}

    response = execute_search(params)

    assert response["results"] == []
    assert response["result_count"] == 0
