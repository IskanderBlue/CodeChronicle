from datetime import date

import pytest
from django.test import Client

from core.models import (
    Code,
    CodeEdition,
    Regulation,
    RegulationClause,
)


@pytest.fixture
def regulation_fixtures(db):
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="1997", year=1997,
        effective_date=date(1998, 4, 6), map_codes=[],
    )
    base_reg = Regulation.objects.create(
        reg_id="403/97", edition=edition, role="base",
        effective_date=date(1998, 4, 6),
    )
    amendment = Regulation.objects.create(
        reg_id="22/98", edition=edition, role="amendment",
        amends=base_reg, effective_date=date(1998, 4, 6),
        filed_date=date(1998, 1, 27),
    )
    RegulationClause.objects.create(
        regulation=amendment, clause_id="1.(1)",
        action="revoke_and_substitute", target_level="article",
        target_id="1.1.3.2.",
        clause_text="The definitions are revoked and substituted",
    )
    return {"code": code, "edition": edition, "base_reg": base_reg, "amendment": amendment}


@pytest.mark.django_db
class TestRegulationDetailView:
    def test_renders_regulation(self, client: Client, regulation_fixtures):
        reg = regulation_fixtures["amendment"]
        response = client.get(f"/regulation/{reg.pk}/")
        assert response.status_code == 200
        assert "22/98" in response.content.decode()
        assert "1.(1)" in response.content.decode()

    def test_shows_action_pill(self, client: Client, regulation_fixtures):
        reg = regulation_fixtures["amendment"]
        response = client.get(f"/regulation/{reg.pk}/")
        content = response.content.decode()
        assert "Revoke and substitute" in content

    def test_404_for_missing(self, client: Client, regulation_fixtures):
        response = client.get("/regulation/99999/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestEditionChainView:
    def test_renders_chain(self, client: Client, regulation_fixtures):
        edition = regulation_fixtures["edition"]
        response = client.get(f"/edition/{edition.pk}/chain/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "403/97" in content
        assert "22/98" in content

    def test_shows_completeness_badge(self, client: Client, regulation_fixtures):
        edition = regulation_fixtures["edition"]
        response = client.get(f"/edition/{edition.pk}/chain/")
        content = response.content.decode()
        # amendment_chain_complete defaults to False
        assert "incomplete" in content.lower() or "Incomplete" in content

    def test_404_for_missing(self, client: Client, regulation_fixtures):
        response = client.get("/edition/99999/chain/")
        assert response.status_code == 404
