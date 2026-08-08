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
    EditionTransition,
    ProvisionCrossReference,
    ProvisionCrossReferenceAlternate,
    ProvisionDisposition,
    ProvisionMapping,
    ProvisionVersionTable,
    Regulation,
    RegulationClause,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "test_edition.json"


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
        assert edition.verified is True

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
        assert cl.target_division == "B"

        cl2 = RegulationClause.objects.get(clause_id="15.(1)")
        assert cl2.strike_text == "institutional occupancies"
        assert cl2.sub_text == "care or detention occupancies"

    def test_loads_commencement_and_clause_dates(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """The new commencement fields round-trip: the regulation's
        ``commencement`` record list, and each clause's own
        ``effective_date`` / ``add_text`` / ``add_anchor`` / ``directives``."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        for reg in data["regulations"]:
            if reg["reg_id"] == "22/98":
                reg["commencement"] = [
                    {
                        "clause": "5(1)", "is_default": True,
                        "effective_date": "1998-04-06", "resolved_provisions": [],
                        "commencement_clause": "Comes into force on April 6, 1998.",
                    },
                    {
                        "clause": "5(2)", "is_default": False,
                        "effective_date": "1999-01-01",
                        "resolved_provisions": ["1.1.3.2.|B"],
                        "commencement_clause": "Article 1.1.3.2. comes into force "
                                               "on January 1, 1999.",
                    },
                ]
                for cl in reg["clauses"]:
                    if cl["clause_id"] == "1.(1)":
                        cl["effective_date"] = "1999-01-01"  # deferred / staggered
                        cl["add_text"] = "(FT1 Rating)"
                        cl["add_anchor"] = "after:CSA C22.2 No. 0.3"
                        cl["directives"] = [
                            {
                                "action": "amend_add", "target_level": "sentence",
                                "target_id": "1.1.3.2.(2)", "target_division": "B",
                            },
                        ]
        out = tmp_path / "OBC_1997_commencement.json"
        out.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(out))

        reg = Regulation.objects.get(reg_id="22/98")
        assert reg.commencement is not None
        assert len(reg.commencement) == 2
        assert reg.commencement[1]["is_default"] is False
        assert reg.commencement[1]["effective_date"] == "1999-01-01"
        assert reg.commencement[1]["resolved_provisions"] == ["1.1.3.2.|B"]

        cl = RegulationClause.objects.get(regulation=reg, clause_id="1.(1)")
        assert cl.effective_date == date(1999, 1, 1)
        assert cl.add_text == "(FT1 Rating)"
        assert cl.add_anchor == "after:CSA C22.2 No. 0.3"
        assert cl.directives == [
            {
                "action": "amend_add", "target_level": "sentence",
                "target_id": "1.1.3.2.(2)", "target_division": "B",
            },
        ]

    def test_resolves_clause_commencement_provenance(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """Each clause is linked to the commencement entry that set its date
        (CCM normalises ``resolved_clauses`` to the ``clause_id`` form, so the
        ids match directly), with the default entry covering clauses no
        deferred entry claims."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        for reg in data["regulations"]:
            if reg["reg_id"] == "22/98":
                reg["commencement"] = [
                    {
                        "clause": "5(1)", "is_default": True,
                        "effective_date": "1998-04-06", "resolved_clauses": [],
                        "source": "parsed",
                        "commencement_clause": "In force on April 6, 1998.",
                    },
                    {
                        "clause": "5(2)", "is_default": False,
                        "effective_date": "1999-01-01",
                        # Normalised to the clause_id form CCM now emits.
                        "resolved_clauses": ["1.(1)"],
                        "source": "parsed",
                        "commencement_clause": "Clause 1 in force on Jan 1, 1999.",
                    },
                ]
                for cl in reg["clauses"]:
                    if cl["clause_id"] == "1.(1)":
                        cl["effective_date"] = "1999-01-01"
        out = tmp_path / "OBC_1997_clause_commencement.json"
        out.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(out))

        reg = Regulation.objects.get(reg_id="22/98")
        # Deferred clause linked to the non-default entry by its resolved id.
        deferred = RegulationClause.objects.get(regulation=reg, clause_id="1.(1)")
        assert deferred.commencement is not None
        assert deferred.commencement["is_default"] is False
        assert deferred.commencement["effective_date"] == "1999-01-01"
        # A clause no deferred entry claims falls under the default entry.
        other = RegulationClause.objects.get(regulation=reg, clause_id="15.(1)")
        assert other.commencement is not None
        assert other.commencement["is_default"] is True

    def test_clause_commencement_none_without_schedule(
        self, edition_json: Path,
    ) -> None:
        """Clauses of a regulation with no commencement schedule link to None."""
        call_command("load_edition", "--source", str(edition_json))
        cl = RegulationClause.objects.get(clause_id="1.(1)")
        assert cl.commencement is None

    def test_commencement_fields_default_when_absent(
        self, edition_json: Path,
    ) -> None:
        """Regulations/clauses without the new keys ingest with safe
        defaults (None / "") — the fields are optional in the contract."""
        call_command("load_edition", "--source", str(edition_json))

        base = Regulation.objects.get(reg_id="403/97")
        assert base.commencement is None

        cl = RegulationClause.objects.get(clause_id="15.(1)")
        assert cl.effective_date is None
        assert cl.add_text == ""
        assert cl.add_anchor == ""
        assert cl.directives is None

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

    def test_ingests_revoked_flag(self, tmp_path: Path) -> None:
        """The CCM-derived per-version ``revoked`` boolean round-trips into
        the model; versions without the key default to False."""
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        # Flip the flag on one real version in the fixture.
        target = None
        for prov in data["provisions"]:
            versions = prov.get("versions") or []
            if versions:
                versions[-1]["revoked"] = True
                target = (prov["provision_id"], prov.get("division", ""),
                          versions[-1]["version"])
                break
        assert target is not None
        out = tmp_path / "OBC_1997.json"
        out.write_text(json.dumps(data), encoding="utf-8")

        call_command("load_edition", "--source", str(out))

        pid, division, vnum = target
        revoked_version = CodeEditionProvisionVersion.objects.get(
            provision__provision_id=pid, provision__division=division, version=vnum,
        )
        assert revoked_version.revoked is True
        # Every other version stays False (key absent in the source JSON).
        assert CodeEditionProvisionVersion.objects.exclude(
            pk=revoked_version.pk
        ).filter(revoked=True).count() == 0

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

    def test_version_notes_stored_on_ingest(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """Producer-tagged ``{kind, text}`` notes are validated and stored."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        injected = False
        for prov in data["provisions"]:
            if prov["provision_id"] == "3.1.4.7.":
                prov["versions"][0]["notes"] = [
                    {"kind": "elaws-note", "text": "Note: a legal annotation."},
                    {"kind": "elaws-html-substitution", "text": "html replaced with snapshot."},
                    {"kind": "elaws-html-substitution", "text": "   "},  # blank text — dropped
                    {"kind": "pdf-rejoin", "text": "hyphenation rejoined."},  # noise — dropped
                ]
                injected = True
        assert injected, "fixture missing expected provision"

        with_notes = tmp_path / "OBC_1997_with_notes.json"
        with_notes.write_text(json.dumps(data), encoding="utf-8")

        call_command("load_edition", "--source", str(with_notes))

        version = CodeEditionProvision.objects.get(
            provision_id="3.1.4.7.", division="Division B",
        ).versions.get(version=0)
        assert version.notes == [
            {"kind": "elaws-note", "text": "Note: a legal annotation."},
            {"kind": "elaws-html-substitution", "text": "html replaced with snapshot."},
        ]
        # The model property buckets them for rendering.
        grouped = version.grouped_notes
        assert len(grouped["annotation"]) == 1
        assert grouped["sourced"] is True

    def test_legacy_string_notes_rejected_on_ingest(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """A pre-classification ``list[str]`` artifact fails the load loudly."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        for prov in data["provisions"]:
            if prov["provision_id"] == "3.1.4.7.":
                prov["versions"][0]["notes"] = ["elaws-note: legacy string"]
        legacy = tmp_path / "OBC_1997_legacy_notes.json"
        legacy.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="tagged"):
            call_command("load_edition", "--source", str(legacy))

    def test_version_notes_default_empty(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """Versions without a ``notes`` key ingest with ``notes == []``."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        for prov in data["provisions"]:
            for ver in prov.get("versions", []):
                ver.pop("notes", None)
        stripped = tmp_path / "OBC_1997_no_notes.json"
        stripped.write_text(json.dumps(data), encoding="utf-8")

        call_command("load_edition", "--source", str(stripped))

        version = CodeEditionProvision.objects.get(
            provision_id="3.1.4.7.", division="Division B",
        ).versions.get(version=0)
        assert version.notes == []
        assert version.grouped_notes["has_any"] is False

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

    @staticmethod
    def _as_ccm_ships_it(edition_json: Path, tmp_path: Path) -> Path:
        """The fixture with the three keys CCM does not send removed.

        Every other test here loads a payload richer than the real one, which
        is why the two defects below went unseen for as long as they did.
        """
        stripped = json.loads(edition_json.read_text(encoding="utf-8"))
        for key in ("display_name", "is_national", "province"):
            stripped.pop(key, None)
        out = tmp_path / "OBC_1997_as_ccm_ships_it.json"
        out.write_text(json.dumps(stripped), encoding="utf-8")
        return out

    def test_a_reload_does_not_blank_a_field_the_payload_never_carried(
        self, edition_json: Path, tmp_path: Path
    ) -> None:
        """A value seeded by other means must survive a reload.

        The loader used to write ``""`` and ``False`` over whatever the row
        held, on every reload, because it read them out of a payload that
        carries neither.  That is not a default — it is an overwrite, and it
        is why the one code the product serves had an empty display name while
        every code it does not serve kept theirs: the unserved ones are never
        reloaded.  ``is_national`` would have un-flagged a national code the
        same way, and nothing would have reported it.
        """
        call_command("load_edition", "--source", str(edition_json))
        Code.objects.filter(code="OBC").update(is_national=True)

        call_command(
            "load_edition",
            "--source",
            str(self._as_ccm_ships_it(edition_json, tmp_path)),
        )

        assert Code.objects.get(code="OBC").is_national is True

    def test_the_loader_names_a_code_the_payload_does_not_name(
        self, edition_json: Path, tmp_path: Path
    ) -> None:
        """``DISPLAY_NAMES`` is the home for the reader-facing name.

        Without it a fresh load leaves ``display_name`` empty, and every page
        title, meta description and JSON-LD ``isPartOf`` says "OBC 1997" where
        it means "Ontario Building Code 1997".  The map lives in the
        repository rather than in the payload because the name is a
        presentation choice, not a mapping result: CCM writes one file per
        edition, so a code-system fact would repeat in every one of them.
        """
        call_command(
            "load_edition",
            "--source",
            str(self._as_ccm_ships_it(edition_json, tmp_path)),
        )

        assert Code.objects.get(code="OBC").display_name == "Ontario Building Code"

    def test_the_map_outranks_a_name_already_on_the_row(
        self, edition_json: Path, tmp_path: Path
    ) -> None:
        """Version control wins, and that is the point of the map.

        The stored name has no traceable origin — the named codes in a dev
        database come from a loader that no longer exists — so a reload must
        be able to correct it.  This is the one field the previous test's rule
        does not cover, and the two must not be merged.
        """
        call_command("load_edition", "--source", str(edition_json))
        Code.objects.filter(code="OBC").update(display_name="Whatever seeded it")

        call_command(
            "load_edition",
            "--source",
            str(self._as_ccm_ships_it(edition_json, tmp_path)),
        )

        assert Code.objects.get(code="OBC").display_name == "Ontario Building Code"

    def test_a_code_outside_the_map_keeps_its_stored_name(
        self, edition_json: Path, tmp_path: Path
    ) -> None:
        """The map names what it knows and touches nothing else."""
        payload = json.loads(edition_json.read_text(encoding="utf-8"))
        for key in ("display_name", "is_national", "province"):
            payload.pop(key, None)
        payload["code"] = "ZZZ"
        unmapped = tmp_path / "ZZZ_1997.json"
        unmapped.write_text(json.dumps(payload), encoding="utf-8")

        call_command("load_edition", "--source", str(unmapped))
        Code.objects.filter(code="ZZZ").update(display_name="Some Other Code")
        call_command("load_edition", "--source", str(unmapped))

        assert Code.objects.get(code="ZZZ").display_name == "Some Other Code"

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

    def test_refuses_unverified(self, edition_json: Path, tmp_path: Path) -> None:
        # An absent key counts as unverified, same as an explicit false.
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        del data["verified"]
        unverified = tmp_path / "OBC_1997_unverified.json"
        unverified.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(CommandError, match="verified"):
            call_command("load_edition", "--source", str(unverified))

    def test_allow_unverified_flag(self, edition_json: Path, tmp_path: Path) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        data["verified"] = False
        unverified = tmp_path / "OBC_1997_unverified.json"
        unverified.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(unverified), "--allow-unverified")
        assert CodeEdition.objects.get(edition_id="1997").verified is False

    def test_refuses_triple_in_force_overlap(
        self, edition_json: Path, tmp_path: Path
    ) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        # Give provision 1.1. three versions whose in-force ranges all cover
        # 2000-01-01.  The pairwise transition model can't represent a 3-way
        # overlap, so the load must fail loudly rather than silently drop the
        # third version at query time.
        for prov in data["provisions"]:
            if prov["provision_id"] == "1.1." and prov["division"] == "Division A":
                base = prov["versions"][0]
                prov["versions"] = [
                    {**base, "version": 0, "effective_date": "1998-04-06",
                     "ineffective_date": None},
                    {**base, "version": 1, "effective_date": "1999-01-01",
                     "ineffective_date": None},
                    {**base, "version": 2, "effective_date": "2000-01-01",
                     "ineffective_date": None},
                ]
                break
        bad = tmp_path / "OBC_1997_triple.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(CommandError, match="in force simultaneously"):
            call_command("load_edition", "--source", str(bad))

    def test_allows_pairwise_in_force_overlap(
        self, edition_json: Path, tmp_path: Path
    ) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        # Two overlapping versions (a normal commencement-window transition)
        # must still load — only a 3-way overlap is rejected.
        for prov in data["provisions"]:
            if prov["provision_id"] == "1.1." and prov["division"] == "Division A":
                base = prov["versions"][0]
                prov["versions"] = [
                    {**base, "version": 0, "effective_date": "1998-04-06",
                     "ineffective_date": None},
                    {**base, "version": 1, "effective_date": "1999-01-01",
                     "ineffective_date": None},
                ]
                break
        ok = tmp_path / "OBC_1997_pair.json"
        ok.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(ok))
        assert (
            CodeEditionProvisionVersion.objects.filter(
                provision__provision_id="1.1."
            ).count()
            == 2
        )

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

    def test_loads_version_assets(self, edition_json: Path, tmp_path: Path) -> None:
        """The version scope is the set the served HTML names.

        A body-only reference has no row under ``regulations[].assets[]``, so
        before this the corpus could not tell a published asset from a 404.
        """
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        version = data["provisions"][0]["versions"][0]
        version["assets"] = [
            {
                "path": "laws/images/en/120332_eV005_files/image001.gif",
                "original_url": (
                    "https://www.ontario.ca/laws/images/en/"
                    "120332_eV005_files/image001.gif"
                ),
                "sha256": "b" * 64,
                "bytes": 1387,
                "content_type": "image/gif",
            },
            {"original_url": "no path, so nothing to publish or check"},
        ]
        with_assets = tmp_path / "OBC_1997_version_assets.json"
        with_assets.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(with_assets))

        loaded = CodeEditionProvisionVersion.objects.get(
            provision__provision_id=data["provisions"][0]["provision_id"],
            version=version["version"],
        )
        assets = list(loaded.assets.all())
        assert len(assets) == 1
        assert assets[0].path == "laws/images/en/120332_eV005_files/image001.gif"
        assert assets[0].sha256 == "b" * 64
        assert assets[0].byte_size == 1387
        assert assets[0].content_type == "image/gif"

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


@pytest.mark.django_db
class TestMappingCoverage:
    """``mapping_coverage`` → ``EditionTransition`` rows (the lineage
    resolver's covered-transition record)."""

    def _load_with_coverage(self, edition_json: Path, tmp_path: Path) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        data["mapping_coverage"] = [
            {"old_edition": "1997", "new_edition": "2006"},
        ]
        out = tmp_path / "OBC_1997_coverage.json"
        out.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(out))

    def test_creates_transition_rows(self, edition_json: Path, tmp_path: Path) -> None:
        # The declaration names 2006, which must already exist (a coverage
        # claim over an unloaded edition is meaningless).
        code = Code.objects.create(code="OBC")
        CodeEdition.objects.create(
            code=code, edition_id="2006", year=2006,
            effective_date=date(2006, 12, 31),
        )
        self._load_with_coverage(edition_json, tmp_path)

        transition = EditionTransition.objects.get()
        assert transition.old_edition.edition_id == "1997"
        assert transition.new_edition.edition_id == "2006"

    def test_skips_declaration_naming_unloaded_edition(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        # No 2006 edition exists: skip with a warning, don't fail the load.
        self._load_with_coverage(edition_json, tmp_path)
        assert EditionTransition.objects.count() == 0

    def test_reload_without_coverage_clears_stale_claim(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """Reloading an edition CASCADE-deletes its cross-edition mapping
        rows, so a coverage claim left standing would make the resolver mint
        false "discontinued" verdicts — the wipe must be symmetric."""
        code = Code.objects.create(code="OBC")
        CodeEdition.objects.create(
            code=code, edition_id="2006", year=2006,
            effective_date=date(2006, 12, 31),
        )
        self._load_with_coverage(edition_json, tmp_path)
        assert EditionTransition.objects.count() == 1

        call_command("load_edition", "--source", str(edition_json))
        assert EditionTransition.objects.count() == 0


@pytest.mark.django_db
class TestProvisionDispositions:
    """``provision_discontinuations`` + ``not_processed`` sentinel mapping
    rows → ``ProvisionDisposition`` records (the lineage resolver's
    per-provision override of the covered-transition default)."""

    def _load(self, edition_json: Path, tmp_path: Path, **extra) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        data.update(extra)
        out = tmp_path / "OBC_1997_dispositions.json"
        out.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(out))

    def test_creates_from_discontinuations(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        code = Code.objects.create(code="OBC")
        CodeEdition.objects.create(
            code=code, edition_id="2006", year=2006,
            effective_date=date(2006, 12, 31),
        )
        self._load(edition_json, tmp_path, provision_discontinuations=[{
            "old_provision_id": "1.1.3.2.", "old_division": "Division A",
            "old_edition": "1997", "new_edition": "2006",
            "status": "discontinued", "source": "agent-adjudicated",
            "reasoning": "No successor content anywhere in the new edition.",
        }])

        disp = ProvisionDisposition.objects.get()
        assert disp.provision.provision_id == "1.1.3.2."
        assert disp.new_edition.edition_id == "2006"
        assert disp.status == ProvisionDisposition.Status.DISCONTINUED
        assert disp.source == "agent-adjudicated"
        assert "successor content" in disp.reasoning
        assert disp.target_reference == ""  # optional key, absent here

    def test_creates_from_not_processed_sentinel_rows(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        """A sentinel mapping row becomes a disposition, never a mapping."""
        code = Code.objects.create(code="OBC")
        CodeEdition.objects.create(
            code=code, edition_id="2006", year=2006,
            effective_date=date(2006, 12, 31),
        )
        self._load(edition_json, tmp_path, provision_mappings=[{
            "old_provision_id": "1.1.3.2.", "old_division": "Division A",
            "old_edition": "1997",
            "new_provision_id": "not_processed", "new_division": "SB-12",
            "new_edition": "2006", "mapping_type": "renumbered",
            "notes": "Content delegated to Supplementary Standard SB-12.",
        }])

        assert ProvisionMapping.objects.count() == 0
        disp = ProvisionDisposition.objects.get()
        assert disp.status == ProvisionDisposition.Status.NOT_PROCESSED
        assert "SB-12" in disp.reasoning
        # The sentinel's new_division names the target document (it is
        # never a real division) — captured so markers can say where.
        assert disp.target_reference == "SB-12"

    def test_skips_unknown_provision(
        self, edition_json: Path, tmp_path: Path,
    ) -> None:
        code = Code.objects.create(code="OBC")
        CodeEdition.objects.create(
            code=code, edition_id="2006", year=2006,
            effective_date=date(2006, 12, 31),
        )
        self._load(edition_json, tmp_path, provision_discontinuations=[{
            "old_provision_id": "9.9.9.9.", "old_division": "Division B",
            "old_edition": "1997", "new_edition": "2006",
            "status": "discontinued",
        }])
        assert ProvisionDisposition.objects.count() == 0

    def test_reload_clears_dispositions_targeting_the_edition(
        self, edition_json: Path,
    ) -> None:
        """Rows targeting the reloaded edition were declared by its payload;
        the old-side CASCADE can't reach them, so the wipe must — a stale
        override must not outlive the load that asserted it."""
        call_command("load_edition", "--source", str(edition_json))
        code = Code.objects.get(code="OBC")
        e1997 = CodeEdition.objects.get(code=code, edition_id="1997")
        e2006 = CodeEdition.objects.create(
            code=code, edition_id="2006", year=2006,
            effective_date=date(2006, 12, 31),
        )
        old_prov = CodeEditionProvision.objects.create(
            edition=e2006, provision_id="1.2.3.4.", level="article",
        )
        ProvisionDisposition.objects.create(
            provision=old_prov, new_edition=e1997,
            status=ProvisionDisposition.Status.DISCONTINUED,
        )

        call_command("load_edition", "--source", str(edition_json))
        assert ProvisionDisposition.objects.count() == 0


@pytest.mark.django_db
class TestCrossReferences:
    """The top-level ``cross_references[]`` array (CCM ``e77daa68``)."""

    #: v1 of 1.1.3.2. reads "…of this Code, other than Part 8, that will…" —
    #: a citation whose surface text is nothing like its target's id, which is
    #: exactly why the producer ships the text and we anchor on it.
    SURFACE = "Part 8"

    def _load(self, edition_json: Path, refs: list[dict]) -> None:
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        data["cross_references"] = refs
        edition_json.write_text(json.dumps(data), encoding="utf-8")
        call_command("load_edition", "--source", str(edition_json))

    def _ref(self, **overrides) -> dict:
        ref = {
            "from_provision_id": "1.1.3.2.",
            "from_division": "Division A",
            "from_version": 1,
            "surface_text": self.SURFACE,
            "to_provision_id": "1.1.3.",
            "to_division": "Division A",
            "targets": [
                {"version": 0, "effective_date": "1998-04-06",
                 "ineffective_date": ""},
            ],
            "note": "",
        }
        ref.update(overrides)
        return ref

    def test_record_is_stored_and_anchored(self, edition_json: Path) -> None:
        self._load(edition_json, [self._ref()])

        record = ProvisionCrossReference.objects.get()
        assert record.from_version.provision.provision_id == "1.1.3.2."
        assert record.from_version.version == 1
        assert record.to_provision is not None
        assert record.to_provision.provision_id == "1.1.3."
        assert record.surface_text == self.SURFACE
        # Position is derived at load; the producer ships none.
        assert record.occurrence == 0

    def test_targets_are_stored_verbatim(self, edition_json: Path) -> None:
        """CCM resolved the slice with the whole edition in hand — we store it,
        we don't re-derive it (the ``pair_key`` discipline)."""
        targets = [
            {"version": 0, "effective_date": "1998-04-06",
             "ineffective_date": "2000-01-01"},
            {"version": 1, "effective_date": "2000-01-01", "ineffective_date": ""},
        ]
        self._load(edition_json, [self._ref(targets=targets)])
        assert ProvisionCrossReference.objects.get().targets == targets

    def test_no_link_correction_keeps_the_citation(self, edition_json: Path) -> None:
        """The printed id was never enacted: null FK, note preserved."""
        self._load(edition_json, [self._ref(
            to_provision_id="", to_division="", targets=[],
            note="As filed, this points to a Sentence never enacted.",
        )])

        record = ProvisionCrossReference.objects.get()
        assert record.to_provision is None
        assert record.targets == []
        assert "never enacted" in record.note

    def test_unlocatable_surface_loads_unanchored(self, edition_json: Path) -> None:
        """The block-straddle case — stored, listed, but not linked inline."""
        self._load(edition_json, [self._ref(surface_text="Section 9.41.")])
        assert ProvisionCrossReference.objects.get().occurrence is None

    def test_repeated_surface_anchors_in_emission_order(
        self, edition_json: Path
    ) -> None:
        """v1 says "provision" several times; two records, two occurrences."""
        self._load(edition_json, [
            self._ref(surface_text="provision of this Code"),
            self._ref(surface_text="provision for which"),
        ])
        occurrences = {
            r.surface_text: r.occurrence
            for r in ProvisionCrossReference.objects.all()
        }
        assert occurrences == {
            "provision of this Code": 0, "provision for which": 0,
        }

    def test_producer_span_is_stored_and_suppresses_derivation(
        self, edition_json: Path
    ) -> None:
        """The shipped shape: container + offsets, taken as given.

        The span here deliberately points at a *different* occurrence than
        surface matching would pick, so a stored ``start`` proves the load
        didn't re-derive one.
        """
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        html = next(
            v["html"]
            for p in data["provisions"] if p["provision_id"] == "1.1.3.2."
            for v in p["versions"] if v["version"] == 1
        )
        start = html.rindex("provision")
        self._load(edition_json, [self._ref(
            surface_text="provision", container="body",
            start=start, end=start + len("provision"),
        )])

        record = ProvisionCrossReference.objects.get()
        assert record.container == "body"
        assert (record.start, record.end) == (start, start + len("provision"))
        assert record.occurrence is None

    def test_table_record_anchors_against_the_table_string(
        self, edition_json: Path
    ) -> None:
        """A ``table`` record's offsets index the table's own html, not the body."""
        data = json.loads(edition_json.read_text(encoding="utf-8"))
        for p in data["provisions"]:
            if p["provision_id"] != "1.1.3.2.":
                continue
            for v in p["versions"]:
                if v["version"] == 1:
                    v["tables"] = [{
                        "table_id": "Table-1.1.3.2.",
                        "caption": "Definitions",
                        "images": [], "notes": "",
                        "html": "<td>per Article 1.1.3.1.</td>",
                        "order": 0,
                    }]
        edition_json.write_text(json.dumps(data), encoding="utf-8")

        self._load(edition_json, [self._ref(
            surface_text="Article 1.1.3.1.", container="table",
            table_id="Table-1.1.3.2.", start=8, end=8 + len("Article 1.1.3.1."),
        )])

        record = ProvisionCrossReference.objects.get()
        assert record.container == "table"
        assert record.table_id == "Table-1.1.3.2."
        assert record.start == 8

    def test_unknown_target_is_dropped(self, edition_json: Path) -> None:
        """The producer raises on unresolved citations, so a target absent from
        the payload is an ingest mismatch — dropped, not stored half-resolved."""
        self._load(edition_json, [self._ref(to_provision_id="99.99.99.99.")])
        assert ProvisionCrossReference.objects.count() == 0

    def test_absent_array_is_not_an_error(self, edition_json: Path) -> None:
        """Editions built before CCM e77daa68 simply carry no citations."""
        call_command("load_edition", "--source", str(edition_json))
        assert ProvisionCrossReference.objects.count() == 0

    def test_alternate_is_stored_as_a_child_row(self, edition_json: Path) -> None:
        """The printed id leads; the curator's intended reading rides in
        ``alternates[]`` and lands as a child row, its targets verbatim."""
        alt_targets = [
            {"version": 0, "effective_date": "1998-04-06", "ineffective_date": ""},
        ]
        self._load(edition_json, [self._ref(
            to_provision_id="1.1.3.",  # what the Code printed
            note="Prints 1.1.3.; the row appears to mean 1.1.",
            alternates=[{
                "to_provision_id": "1.1.",  # what we believe was meant
                "to_division": "Division A",
                "targets": alt_targets,
            }],
        )])

        record = ProvisionCrossReference.objects.get()
        assert record.to_provision is not None
        assert record.to_provision.provision_id == "1.1.3."  # primary = printed
        alt = record.alternates.get()
        assert alt.to_provision is not None
        assert alt.to_provision.provision_id == "1.1."  # alternate = intended
        assert alt.targets == alt_targets  # stored verbatim, never re-derived

    def test_absent_alternates_key_yields_no_child_rows(
        self, edition_json: Path
    ) -> None:
        """``alternates`` is omitted when empty — the common case."""
        self._load(edition_json, [self._ref()])
        assert ProvisionCrossReferenceAlternate.objects.count() == 0

    def test_unknown_alternate_dropped_primary_survives(
        self, edition_json: Path
    ) -> None:
        """An intended id absent from the payload drops only the alternate; the
        printed link still stands (unlike a missing *primary*, which drops the
        whole record)."""
        self._load(edition_json, [self._ref(
            alternates=[{"to_provision_id": "99.99.99.", "to_division": "",
                         "targets": []}],
        )])
        assert ProvisionCrossReference.objects.count() == 1
        assert ProvisionCrossReferenceAlternate.objects.count() == 0


@pytest.mark.django_db
class TestFirstEditionDateSeed:
    def test_load_seeds_known_first_edition_date(self, edition_json: Path) -> None:
        """Seeded on every load (not only by migration): Code rows can be
        wiped and recreated, which would lose a one-time migration seed."""
        call_command("load_edition", "--source", str(edition_json))
        code = Code.objects.get(code="OBC")
        assert code.first_edition_date == date(1975, 12, 31)
