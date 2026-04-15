"""Tests for the load_edition management command."""

import json
from datetime import date
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionVersionTable,
    Regulation,
    RegulationClause,
)

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / ".tmp" / "test_edition.json"


@pytest.fixture
def edition_json(tmp_path: Path) -> Path:
    """Copy the fixture to a tmp dir so tests are isolated."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    out = tmp_path / "OBC_1997.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


@pytest.mark.django_db
class TestLoadEdition:
    def test_creates_code_and_edition(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        code = Code.objects.get(code="OBC")
        assert code.display_name == "Ontario Building Code"
        assert code.is_national is False

        edition = CodeEdition.objects.get(code=code, edition_id="1997")
        assert edition.effective_date == date(1998, 4, 6)
        assert edition.ineffective_date == date(2006, 12, 31)
        assert edition.amendment_chain_complete is True

    def test_creates_regulations(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        assert Regulation.objects.count() == 2
        base = Regulation.objects.get(reg_id="403/97")
        assert base.role == Regulation.Role.BASE
        assert base.amends is None

        amendment = Regulation.objects.get(reg_id="22/98")
        assert amendment.role == Regulation.Role.AMENDMENT
        assert amendment.amends == base
        assert amendment.filed_date == date(1998, 1, 27)

    def test_creates_clauses(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        assert RegulationClause.objects.count() == 2
        cl = RegulationClause.objects.get(clause_id="1.(1)")
        assert cl.regulation.reg_id == "22/98"
        assert cl.action == RegulationClause.Action.REVOKE_AND_SUBSTITUTE
        assert cl.target_level == RegulationClause.TargetLevel.ARTICLE
        assert cl.target_id == "1.1.3.2."

        cl2 = RegulationClause.objects.get(clause_id="15.(1)")
        assert cl2.strike_text == "institutional occupancies"
        assert cl2.sub_text == "care or detention occupancies"

    def test_creates_provisions(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        assert CodeEditionProvision.objects.count() == 10

        subsection = CodeEditionProvision.objects.get(
            provision_id="1.1.3.", division="Division A"
        )
        assert subsection.level == CodeEditionProvision.Level.SUBSECTION

        section = CodeEditionProvision.objects.get(
            provision_id="1.1.", division="Division A"
        )
        assert subsection.parent == section

        article = CodeEditionProvision.objects.get(
            provision_id="1.1.3.2.", division="Division A"
        )
        assert article.level == CodeEditionProvision.Level.ARTICLE
        assert article.parent == subsection

    def test_appendix_of_fk(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        appendix = CodeEditionProvision.objects.get(provision_id="A-1.1.3.2.(1)")
        assert appendix.level == CodeEditionProvision.Level.SENTENCE
        assert appendix.appendix_of is not None
        assert appendix.appendix_of.provision_id == "1.1.3.2."

    def test_creates_versions(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        article = CodeEditionProvision.objects.get(
            provision_id="1.1.3.2.", division="Division A"
        )
        versions = list(article.versions.order_by("version"))
        assert len(versions) == 2

        v0 = versions[0]
        assert v0.version == 0
        assert v0.action == CodeEditionProvisionVersion.Action.ORIGINAL
        assert v0.clause is None
        assert v0.effective_date == date(1998, 4, 6)
        assert v0.ineffective_date == date(1998, 4, 6)
        assert "Alternative measure" in v0.html

        v1 = versions[1]
        assert v1.version == 1
        assert v1.action == CodeEditionProvisionVersion.Action.REVOKE_AND_SUBSTITUTE
        assert v1.clause is not None
        assert v1.clause.clause_id == "1.(1)"
        assert v1.ineffective_date is None
        assert "other than Part 8" in v1.html

    def test_creates_tables(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        tables = ProvisionVersionTable.objects.all()
        assert tables.count() == 1

        tbl = tables.first()
        assert tbl.table_id == "Table-3.1.4.7."
        assert tbl.caption == "Minimum Fire-Resistance Rating for Fire Separations"
        assert isinstance(tbl.images, list)
        assert "Note (1)" in tbl.notes

    def test_version_count_updated(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        article = CodeEditionProvision.objects.get(
            provision_id="1.1.3.2.", division="Division A"
        )
        assert article.version_count == 2

        single = CodeEditionProvision.objects.get(
            provision_id="3.1.4.7.", division="Division B"
        )
        assert single.version_count == 1

    def test_idempotent(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))
        call_command("load_edition", "--source", str(edition_json))

        assert Code.objects.count() == 1
        assert CodeEdition.objects.count() == 1
        assert Regulation.objects.count() == 2
        assert RegulationClause.objects.count() == 2
        assert CodeEditionProvision.objects.count() == 10
        assert CodeEditionProvisionVersion.objects.count() == 12
        assert ProvisionVersionTable.objects.count() == 1

    def test_missing_file_raises(self) -> None:
        with pytest.raises(CommandError, match="Source file not found"):
            call_command("load_edition", "--source", "/nonexistent/file.json")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json", encoding="utf-8")
        with pytest.raises(CommandError, match="Invalid JSON"):
            call_command("load_edition", "--source", str(bad_file))
