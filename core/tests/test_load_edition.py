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
    CodeEditionProvisionVersionClause,
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
        assert v0.contributing_clauses.count() == 0
        assert v0.effective_date == date(1998, 4, 6)
        assert v0.ineffective_date == date(1998, 4, 6)
        assert "Alternative measure" in v0.html

        v1 = versions[1]
        assert v1.version == 1
        assert v1.contributing_clauses.count() == 1
        first_clause = v1.contributing_clauses.first()
        assert first_clause is not None
        assert first_clause.clause_id == "1.(1)"
        assert v1.ineffective_date is None
        assert "other than Part 8" in v1.html

    def test_creates_tables(self, edition_json: Path) -> None:
        call_command("load_edition", "--source", str(edition_json))

        tables = ProvisionVersionTable.objects.all()
        assert tables.count() == 1

        tbl = tables.first()
        assert tbl is not None
        assert tbl.table_id == "Table-3.1.4.7."
        assert tbl.caption == "Minimum Fire-Resistance Rating for Fire Separations"
        assert isinstance(tbl.images, list)
        assert "Note (1)" in tbl.notes

    def test_table_html_ingests_when_present(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """CCM-emitted ``html`` on a table lands on ``ProvisionVersionTable.html``."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        markup = "<table><tbody><tr><td>Between suites</td><td>1 h</td></tr></tbody></table>"
        injected = 0
        for prov in data["provisions"]:
            for ver in prov.get("versions", []):
                for tbl in ver.get("tables", []):
                    tbl["html"] = markup
                    injected += 1
        assert injected >= 1, "fixture has no tables to test against"

        with_html = tmp_path / "OBC_1997_with_html.json"
        with_html.write_text(json.dumps(data), encoding="utf-8")

        call_command("load_edition", "--source", str(with_html))

        tbl = ProvisionVersionTable.objects.get(table_id="Table-3.1.4.7.")
        assert tbl.html == markup

    def test_table_html_defaults_empty(self, edition_json: Path, tmp_path: Path) -> None:
        """Tables without an ``html`` key ingest with ``html == ""``."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        for prov in data["provisions"]:
            for ver in prov.get("versions", []):
                for tbl in ver.get("tables", []):
                    tbl.pop("html", None)
        stripped = tmp_path / "OBC_1997_no_html.json"
        stripped.write_text(json.dumps(data), encoding="utf-8")

        call_command("load_edition", "--source", str(stripped))

        tbl = ProvisionVersionTable.objects.get(table_id="Table-3.1.4.7.")
        assert tbl.html == ""

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

    def test_refuses_snapshots_path(self, edition_json: Path, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        snap = snapshots_dir / "OBC_1997_elaws.json"
        snap.write_text(edition_json.read_text(encoding="utf-8"), encoding="utf-8")
        with pytest.raises(CommandError, match="snapshots"):
            call_command("load_edition", "--source", str(snap))

    def test_refuses_incomplete_chain(self, edition_json: Path, tmp_path: Path) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        data["amendment_chain_complete"] = False
        incomplete = tmp_path / "OBC_1997_incomplete.json"
        incomplete.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(CommandError, match="amendment_chain_complete"):
            call_command("load_edition", "--source", str(incomplete))

    def test_allow_incomplete_chain_flag(self, edition_json: Path, tmp_path: Path) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        data["amendment_chain_complete"] = False
        incomplete = tmp_path / "OBC_1997_incomplete.json"
        incomplete.write_text(json.dumps(data), encoding="utf-8")
        call_command(
            "load_edition", "--source", str(incomplete), "--allow-incomplete-chain",
        )
        assert CodeEdition.objects.get(edition_id="1997").amendment_chain_complete is False

    def test_loads_regulation_assets(self, edition_json: Path, tmp_path: Path) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        # Inject assets onto the amending regulation per the
        # inline-html-image-assets contract addendum.
        for reg in data["regulations"]:
            if reg["reg_id"] == "22/98":
                reg["assets"] = [
                    {
                        "path": "laws/images/en/R98022_e_files/image001.gif",
                        "original_url": "https://www.ontario.ca/laws/images/en/R98022_e_files/image001.gif",
                        "sha256": "a" * 64,
                        "bytes": 1234,
                        "content_type": "image/gif",
                    }
                ]
        with_assets = tmp_path / "OBC_1997_with_assets.json"
        with_assets.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(with_assets))

        amender = Regulation.objects.get(reg_id="22/98")
        assets = list(amender.assets.all())
        assert len(assets) == 1
        a = assets[0]
        assert a.path == "laws/images/en/R98022_e_files/image001.gif"
        assert a.sha256 == "a" * 64
        assert a.byte_size == 1234
        assert a.content_type == "image/gif"

    def test_merges_meta_amendment_stub_with_full_clause(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """A back-pointer stub and a full clause for the same
        ``(regulation, clause_id)`` collapse to one row."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        # Pick an existing clause and inject a duplicate stub carrying
        # only amended_by — exercises the loader's merge path.
        for reg in data["regulations"]:
            if reg["reg_id"] == "22/98":
                reg["clauses"].append({
                    "clause_id": "1.(1)",
                    "amended_by": [
                        {"reg_id": "999/99", "clause_id": "5", "action": "revoke"}
                    ],
                })
        with_stub = tmp_path / "OBC_1997_with_stub.json"
        with_stub.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(with_stub))

        # One row, not two — full clause's payload survives, stub's
        # amended_by is grafted on.
        rows = RegulationClause.objects.filter(
            regulation__reg_id="22/98", clause_id="1.(1)",
        )
        assert rows.count() == 1
        merged = rows.first()
        assert merged is not None
        assert merged.action == RegulationClause.Action.REVOKE_AND_SUBSTITUTE  # from full
        assert merged.amended_by  # from stub
        assert merged.amended_by[0]["reg_id"] == "999/99"

    def test_contributing_clause_order_by_filed_date(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """Two contributing clauses on the same version sort by
        (regulation.filed_date, clause_id) into ``apply_order``."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        # Add a second amending regulation filed AFTER 22/98 and have it
        # also contribute to the 1.1.3.2. v1 version.
        data["regulations"].append({
            "reg_id": "99/99",
            "role": "amendment",
            "amends": "403/97",
            "filed_date": "1999-06-01",
            "effective_date": "1998-04-06",
            "source_pdf": "ont_reg_1999.pdf",
            "source_pages": [1, 5],
            "clauses": [{
                "clause_id": "2",
                "parent_clause": "2",
                "action": "amend_add",
                "target_level": "article",
                "target_id": "1.1.3.2.",
                "clause_text": "Add nothing useful.",
            }],
        })
        for prov in data["provisions"]:
            if prov["provision_id"] == "1.1.3.2.":
                for ver in prov["versions"]:
                    if ver["version"] == 1:
                        ver["clauses"] = [
                            {"regulation": "99/99", "clause_id": "2"},
                            {"regulation": "22/98", "clause_id": "1.(1)"},
                        ]
        ordered = tmp_path / "OBC_1997_ordered.json"
        ordered.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(ordered))

        v1 = CodeEditionProvisionVersion.objects.get(
            provision__provision_id="1.1.3.2.", version=1,
        )
        links = list(
            CodeEditionProvisionVersionClause.objects
            .filter(version=v1)
            .order_by("apply_order")
        )
        assert len(links) == 2
        # 22/98 was filed 1998-01-27; 99/99 was filed 1999-06-01.
        # 22/98 must come first regardless of JSON emission order.
        assert links[0].clause.regulation.reg_id == "22/98"
        assert links[0].apply_order == 0
        assert links[1].clause.regulation.reg_id == "99/99"
        assert links[1].apply_order == 1
