import logging
from datetime import date
from typing import Any

import pytest

from api import formatters
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EditionTransition,
    ProvisionMapping,
)


def a_match(
    code_edition: str, provision_id: str, division: str = "B"
) -> dict[str, Any]:
    """The two keys every search result carries, saved and real.

    ``api.search.engine`` builds a result by walking versions, and sets
    ``version`` and ``provision`` in one dict literal; a version's provision is
    a non-null FK; and ``load_edition`` refuses a payload where a provision
    carries no version.  So a result missing either key is not a shape the
    formatter can meet, and a test that builds one tests nothing.
    """
    code_name, edition_id = code_edition.split("_", 1)
    system, _ = Code.objects.get_or_create(
        code=code_name, defaults={"display_name": code_name}
    )
    edition, _ = CodeEdition.objects.get_or_create(
        code=system,
        edition_id=edition_id,
        defaults={"year": 2024, "effective_date": date(2024, 1, 1)},
    )
    provision, _ = CodeEditionProvision.objects.get_or_create(
        edition=edition,
        provision_id=provision_id,
        division=division,
        defaults={"level": "article"},
    )
    version = CodeEditionProvisionVersion.objects.create(
        provision=provision, version=0, effective_date=edition.effective_date,
    )
    return {"version": version, "provision": provision}


@pytest.mark.django_db
def test_format_search_results_emits_span_fields_without_bbox(monkeypatch):
    monkeypatch.setattr(
        formatters, "_build_code_display_name", lambda code_edition: "National Building Code 2025"
    )
    monkeypatch.setattr(formatters, "_load_group_hierarchy", lambda formatted_results, query_date=None: {})

    formatted = formatters.format_search_results(
        [
            {
                "id": "3.2.9.",
                "title": "Fire Separations",
                "code_edition": "NBC_2025",
                "page": 120,
                "page_end": 122,
                "initial_page_top": 640.0,
                "final_page_bottom": 88.0,
                "score": 1.0,
                "division": "B",
                **a_match("NBC_2025", "3.2.9."),
            }
        ]
    )

    item = formatted[0]
    assert "page" not in item  # page fields removed from formatted results
    assert "bbox" not in item


def test_group_results_collapses_when_more_than_80_percent_of_direct_children_match():
    formatted_results = [
        {
            "id": "3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.91,
            "page": 10,
            "page_end": 10,
        },
        {
            "id": "3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.96,
            "page": 11,
            "page_end": 11,
        },
        {
            "id": "3.2.9.3",
            "title": "Child 3",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.89,
            "page": 12,
            "page_end": 12,
        },
        {
            "id": "3.2.9.4",
            "title": "Child 4",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.88,
            "page": 13,
            "page_end": 13,
        },
        {
            "id": "3.2.9.5",
            "title": "Child 5",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.87,
            "page": 14,
            "page_end": 14,
        },
    ]
    hierarchy = {
        ("NBC_2025", "3.2.9", "B"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": f"3.2.9.{i}", "title": f"Child {i}", "page": 9 + i, "page_end": 9 + i}
                for i in range(1, 6)
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert len(grouped_results) == 1
    assert grouped_results[0]["group_type"] == "parent_children"
    assert grouped_results[0]["parent_id"] == "3.2.9"
    assert len(grouped_results[0]["children"]) == 5
    assert grouped_results[0]["top_scoring_child_id"] == "3.2.9.2"
    # Each matched child carries its full formatted result so the template can
    # accordion it open to its own content (grouping is a UI aide, not a drop).
    children = grouped_results[0]["children"]
    assert all(c["is_match"] for c in children)
    assert all(c["result"] is not None for c in children)
    assert {c["result"]["id"] for c in children} == {f"3.2.9.{i}" for i in range(1, 6)}


def test_group_absorbs_parent_that_also_matched():
    # The subsection itself matched (parent_id 3.2.9 → its own parent 3.2) AND
    # 4/4 of its children matched.  The parent must not appear as a second
    # standalone row alongside the group card — both share one accordion key.
    formatted_results = [
        {"id": "3.2.9", "title": "Parent", "code": "NBC_2025",
         "parent_id": "3.2", "division": "B", "score": 0.99},
    ] + [
        {"id": f"3.2.9.{i}", "title": f"Child {i}", "code": "NBC_2025",
         "parent_id": "3.2.9", "division": "B", "score": 0.9 - 0.01 * i}
        for i in range(1, 5)
    ]
    hierarchy = {
        ("NBC_2025", "3.2.9", "B"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": f"3.2.9.{i}", "title": f"Child {i}", "page": i, "page_end": i}
                for i in range(1, 5)
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    rows_for_parent = [r for r in grouped_results if r.get("id") == "3.2.9"]
    assert len(rows_for_parent) == 1
    assert rows_for_parent[0]["group_type"] == "parent_children"
    # The parent's own match is absorbed onto the group (not dropped) so the
    # template can still surface the parent provision.
    assert rows_for_parent[0]["parent_result"]["id"] == "3.2.9"
    # The group header shows the parent's score (0.99), not the top child's.
    assert rows_for_parent[0]["score"] == 0.99


def test_nest_child_results_children_are_expandable_and_keep_parent():
    # Phase-3 nesting (parent matched + a child matched, below the Phase-2
    # threshold): children must carry their full result so they accordion open,
    # and the parent provision must be preserved as parent_result.
    parent = {"id": "3.2.9", "title": "Parent", "code": "OBC_2012",
              "parent_id": "3.2", "division": "B", "score": 0.95}
    child = {"id": "3.2.9.1", "title": "Child", "code": "OBC_2012",
             "parent_id": "3.2.9", "division": "B", "score": 0.8,
             "html_content": "<p>body</p>"}

    out = formatters._nest_child_results([parent, child])

    groups = [r for r in out if r.get("group_type") == "parent_children"]
    assert len(groups) == 1
    assert all("result" in c for c in groups[0]["children"])
    assert groups[0]["parent_result"]["id"] == "3.2.9"
    # The child was absorbed — it is not also a standalone row.
    assert [r["id"] for r in out] == ["3.2.9"]


def test_group_results_does_not_group_at_or_below_80_percent():
    formatted_results = [
        {
            "id": "3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.91,
        },
        {
            "id": "3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.88,
        },
        {
            "id": "3.2.9.3",
            "title": "Child 3",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.84,
        },
    ]
    hierarchy = {
        ("NBC_2025", "3.2.9", "B"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": f"3.2.9.{i}", "title": f"Child {i}", "page": i, "page_end": i}
                for i in range(1, 5)
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert all(item.get("group_type") != "parent_children" for item in grouped_results)
    assert len(grouped_results) == 3


def test_group_results_uses_children_not_pages():
    formatted_results = [
        {
            "id": "3.2.9.1",
            "title": "Child 1",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.91,
            "page": 10,
            "page_end": 12,
        },
        {
            "id": "3.2.9.2",
            "title": "Child 2",
            "code": "NBC_2025",
            "parent_id": "3.2.9",
            "division": "B",
            "score": 0.88,
            "page": 13,
            "page_end": 13,
        },
    ]
    hierarchy = {
        ("NBC_2025", "3.2.9", "B"): {
            "parent_title": "Parent Section",
            "children": [
                {"node_id": "3.2.9.1", "title": "Child 1", "page": 10, "page_end": 12},
                {"node_id": "3.2.9.2", "title": "Child 2", "page": 13, "page_end": 13},
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert grouped_results[0]["child_match_count"] == 2
    assert grouped_results[0]["child_total_count"] == 2


def test_group_results_keeps_single_child_match_standalone():
    formatted_results = [
        {
            "id": "Table-9.10.3.1.-A",
            "title": "Standalone Table",
            "code": "NBC_2025",
            "parent_id": "Table-9.10.3.1",
            "division": "",
            "score": 0.91,
        }
    ]
    hierarchy = {
        ("NBC_2025", "Table-9.10.3.1", ""): {
            "parent_title": "Standalone Parent",
            "children": [
                {
                    "node_id": "Table-9.10.3.1.-A",
                    "title": "Standalone Table",
                    "page": 18,
                    "page_end": 18,
                },
                {
                    "node_id": "Table-9.10.3.1.-B",
                    "title": "Context Table",
                    "page": 19,
                    "page_end": 19,
                },
            ],
        }
    }

    grouped_results = formatters.group_formatted_results(formatted_results, hierarchy)

    assert len(grouped_results) == 1
    assert grouped_results[0].get("group_type") is None
    assert grouped_results[0]["id"] == "Table-9.10.3.1.-A"


def test_container_levels_cover_structural_headings():
    # Guards the level set the document block keys "Content not yet available"
    # suppression off — headings never carry body text; leaves do.
    from core.models import CodeEditionProvision as P

    assert P.Level.DIVISION in formatters.CONTAINER_LEVELS
    assert P.Level.PART in formatters.CONTAINER_LEVELS
    assert P.Level.SECTION in formatters.CONTAINER_LEVELS
    assert P.Level.SUBSECTION in formatters.CONTAINER_LEVELS
    assert P.Level.ARTICLE not in formatters.CONTAINER_LEVELS


@pytest.mark.django_db
def test_format_single_result_marks_structural_headings(monkeypatch):
    from core.models import (
        Code,
        CodeEdition,
        CodeEditionProvision,
        CodeEditionProvisionVersion,
    )

    monkeypatch.setattr(formatters, "_build_code_display_name", lambda code_edition: code_edition)
    system = Code.objects.create(code="OBC", display_name="OBC", is_national=False)
    edition = CodeEdition.objects.create(
        code=system, edition_id="2024", year=2024,
        effective_date=date(2024, 1, 1), source="e-Laws",
    )
    subsection = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.3.7.", level="subsection", division="C",
    )
    article = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.3.7.1.", level="article", division="C",
        parent=subsection,
    )
    # Every provision has a version — the loader refuses a payload where one
    # does not (see Command._check_every_provision_has_a_version), so a
    # versionless provision is not a case this function can meet.
    sub_v0 = CodeEditionProvisionVersion.objects.create(
        provision=subsection, version=0, title="Application",
        effective_date=date(2024, 1, 1),
    )
    art_v0 = CodeEditionProvisionVersion.objects.create(
        provision=article, version=0, title="Smoke Alarms",
        effective_date=date(2024, 1, 1),
    )

    sub_fmt = formatters._format_single_result(
        {"code_edition": "OBC_2024", "provision": subsection, "version": sub_v0}
    )
    art_fmt = formatters._format_single_result(
        {"code_edition": "OBC_2024", "provision": article, "version": art_v0}
    )

    assert sub_fmt["is_structural"] is True
    assert art_fmt["is_structural"] is False


@pytest.mark.django_db
def test_format_single_result_exposes_until_commencement(monkeypatch):
    """The band's 'Until' proof: a version's result carries the NEXT version's
    CommencementProvenance (its contributing clause's resolved entry), since
    the version ends the day the next one comes into force."""
    from core.models import (
        Code,
        CodeEdition,
        CodeEditionProvision,
        CodeEditionProvisionVersion,
        CodeEditionProvisionVersionClause,
        Regulation,
        RegulationClause,
    )

    monkeypatch.setattr(formatters, "_build_code_display_name", lambda c: c)
    system = Code.objects.create(code="OBC", display_name="OBC")
    edition = CodeEdition.objects.create(
        code=system, edition_id="2012", year=2012,
        effective_date=date(2012, 1, 1), source="e-Laws",
    )
    article = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.1.1.1.", level="article", division="A",
    )
    v0 = CodeEditionProvisionVersion.objects.create(
        provision=article, version=0,
        effective_date=date(2014, 1, 1), ineffective_date=date(2016, 1, 1),
    )
    v1 = CodeEditionProvisionVersion.objects.create(
        provision=article, version=1, effective_date=date(2016, 1, 1),
    )
    reg = Regulation.objects.create(
        reg_id="332/12", edition=edition, role="amendment",
        effective_date=date(2014, 1, 1),
    )
    entry = {
        "regulation": "332/12", "clause": "4.4.1.1(2)", "is_default": False,
        "effective_date": "2016-01-01", "source": "parsed",
        "commencement_clause": "Comes into force on January 1, 2016.",
    }
    clause = RegulationClause.objects.create(
        regulation=reg, clause_id="c1",
        effective_date=date(2016, 1, 1), commencement=entry,
    )
    CodeEditionProvisionVersionClause.objects.create(
        version=v1, clause=clause, apply_order=0,
    )

    res = formatters._format_single_result(
        {"code_edition": "OBC_2012", "provision": article, "version": v0}
    )
    # v0 ends when v1 (produced by `clause`) commences — its provenance rides along.
    assert res["until_commencement"] == entry
    assert res["until_commencement_date"] == date(2016, 1, 1)


@pytest.mark.django_db
def test_added_provision_attributes_its_introducing_reg(monkeypatch):
    """An amend-add-created provision (v0 produced by an ``amend_add`` clause)
    attributes its *introducing* reg as the base — not the edition base — and is
    flagged ``is_added`` so the band reads "added" and the copy text "Added by".
    Mirrors OBC 1997 3.7.6.3., introduced by O. Reg. 593/99, not base 403/97."""
    from core.models import (
        Code,
        CodeEdition,
        CodeEditionProvision,
        CodeEditionProvisionVersion,
        CodeEditionProvisionVersionClause,
        Regulation,
        RegulationClause,
    )

    monkeypatch.setattr(formatters, "_build_code_display_name", lambda c: c)
    system = Code.objects.create(code="OBC", display_name="OBC")
    edition = CodeEdition.objects.create(
        code=system, edition_id="1997", year=1997,
        effective_date=date(1998, 4, 6), source="e-Laws",
    )
    # Edition base — must NOT be the attributed reg for this added provision.
    Regulation.objects.create(
        reg_id="403/97", edition=edition, role="base",
        effective_date=date(1998, 4, 6),
    )
    introducing = Regulation.objects.create(
        reg_id="593/99", edition=edition, role="amendment",
        effective_date=date(2000, 3, 5),
    )
    article = CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.7.6.3.", level="article",
    )
    v0 = CodeEditionProvisionVersion.objects.create(
        provision=article, version=0, effective_date=date(2000, 3, 5),
        ineffective_date=date(2006, 12, 31), title="Location of Plumbing Fixtures",
    )
    clause = RegulationClause.objects.create(
        regulation=introducing, clause_id="3",
        action=RegulationClause.Action.AMEND_ADD,
        target_level="section", target_id="3.7.",
    )
    CodeEditionProvisionVersionClause.objects.create(
        version=v0, clause=clause, apply_order=0,
    )

    res = formatters._format_single_result(
        {"code_edition": "OBC_1997", "provision": article, "version": v0,
         "id": "3.7.6.3.", "division": ""}
    )

    # Base reg is the introducing amendment, not the edition base 403/97.
    assert res["base_regulation"].reg_id == "593/99"
    assert res["is_added"] is True

    # Provenance chain: one dated "Added by" line, no "Base:" duplicate of the
    # same reg.  Asserted on the lines themselves rather than on a joined
    # string, so a label that stops starting its own line fails here.
    lines = formatters.provenance_lines(
        version=v0,
        most_recent_clause=v0.last_contributing_clause,
        base_regulation=res["base_regulation"],
        next_version=None,
        is_added=res["is_added"],
    )
    assert "Added by: O. Reg. 593/99, cl. 3 (2000-03-05)" in lines
    assert not any(line.startswith("Base: O. Reg.") for line in lines)


@pytest.mark.django_db
def test_base_original_still_attributes_edition_base_reg(monkeypatch):
    """A genuine base original (v0 with no producing clause) keeps the edition
    base reg and is not flagged ``is_added`` — the unchanged-path regression."""
    from core.models import (
        Code,
        CodeEdition,
        CodeEditionProvision,
        CodeEditionProvisionVersion,
        Regulation,
    )

    monkeypatch.setattr(formatters, "_build_code_display_name", lambda c: c)
    system = Code.objects.create(code="OBC", display_name="OBC")
    edition = CodeEdition.objects.create(
        code=system, edition_id="1997", year=1997,
        effective_date=date(1998, 4, 6), source="e-Laws",
    )
    Regulation.objects.create(
        reg_id="403/97", edition=edition, role="base",
        effective_date=date(1998, 4, 6),
    )
    article = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.1.1.1.", level="article",
    )
    v0 = CodeEditionProvisionVersion.objects.create(
        provision=article, version=0, effective_date=date(1998, 4, 6),
    )

    res = formatters._format_single_result(
        {"code_edition": "OBC_1997", "provision": article, "version": v0,
         "id": "1.1.1.1.", "division": ""}
    )
    assert res["base_regulation"].reg_id == "403/97"
    assert res["is_added"] is False


def _commencement_fixture():
    """An edition pair for the base-regulation commencement fallbacks.

    OBC 2012-shaped: the old edition's base reg has a staggered schedule
    (default 2014-01-01 plus a deferred 2016-01-01 record naming one
    provision), and an EditionTransition points at a replacing edition whose
    base reg commences 2025-01-01.
    """
    from core.models import Code, CodeEdition, EditionTransition, Regulation

    system = Code.objects.create(code="OBC", display_name="OBC")
    edition = CodeEdition.objects.create(
        code=system, edition_id="2012", year=2012,
        effective_date=date(2014, 1, 1), ineffective_date=date(2025, 1, 1),
        source="e-Laws",
    )
    base = Regulation.objects.create(
        reg_id="332/12", edition=edition, role="base",
        effective_date=date(2014, 1, 1),
        commencement=[
            {
                "regulation": "332/12", "clause": "4.4.1.1(1)", "is_default": True,
                "effective_date": "2014-01-01", "source": "parsed",
                "commencement_clause": "Comes into force on January 1, 2014.",
                "resolved_provisions": [],
            },
            {
                "regulation": "332/12", "clause": "4.4.1.1(2)", "is_default": False,
                "effective_date": "2016-01-01", "source": "parsed",
                "commencement_clause": "Sentence 4.2.1.1.(5) comes into force on January 1, 2016.",
                # Trailing-dot inconsistency is real data — see 332/12 vs 315/10.
                "resolved_provisions": ["4.2.1.1.(5).|C"],
            },
        ],
    )
    next_edition = CodeEdition.objects.create(
        code=system, edition_id="2024", year=2024,
        effective_date=date(2025, 1, 1), source="e-Laws",
    )
    Regulation.objects.create(
        reg_id="163/24", edition=next_edition, role="base",
        effective_date=date(2025, 1, 1),
        commencement=[
            {
                "regulation": "163/24", "clause": "1(1)", "is_default": True,
                "effective_date": "2025-01-01", "source": "parsed",
                "commencement_clause": "Comes into force on January 1, 2025.",
                "resolved_provisions": [],
            },
        ],
    )
    EditionTransition.objects.create(old_edition=edition, new_edition=next_edition)
    return edition, base


@pytest.mark.django_db
def test_from_commencement_falls_back_to_base_regulation(monkeypatch):
    """A base version (no producing clause) proves its From edge with the base
    regulation's own commencement record — the default record when its date
    matches, the provision-naming record for a staggered provision, and
    nothing when the schedule doesn't set the version's date."""
    from core.models import CodeEditionProvision, CodeEditionProvisionVersion

    monkeypatch.setattr(formatters, "_build_code_display_name", lambda c: c)
    edition, base = _commencement_fixture()
    article = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.1.1.1.", level="article", division="C",
    )
    v0 = CodeEditionProvisionVersion.objects.create(
        provision=article, version=0, effective_date=date(2014, 1, 1),
    )
    res = formatters._format_single_result(
        {"code_edition": "OBC_2012", "provision": article, "version": v0,
         "id": "1.1.1.1.", "division": "C"}
    )
    assert res["from_commencement"] == base.commencement[0]

    # Staggered: the deferred record names 4.2.1.1.(5) — a version of that
    # article commencing 2016-01-01 gets the deferred record, not the default.
    staggered = CodeEditionProvision.objects.create(
        edition=edition, provision_id="4.2.1.1.", level="article", division="C",
    )
    sv = CodeEditionProvisionVersion.objects.create(
        provision=staggered, version=0, effective_date=date(2016, 1, 1),
    )
    res = formatters._format_single_result(
        {"code_edition": "OBC_2012", "provision": staggered, "version": sv,
         "id": "4.2.1.1.", "division": "C"}
    )
    assert res["from_commencement"] == base.commencement[1]

    # Date guard: a version whose date no schedule record sets gets no record
    # rather than a plausible-but-wrong one.
    odd = CodeEditionProvisionVersion.objects.create(
        provision=article, version=1, effective_date=date(2018, 1, 1),
    )
    res = formatters._format_single_result(
        {"code_edition": "OBC_2012", "provision": article, "version": odd,
         "id": "1.1.1.1.", "division": "C"}
    )
    assert res["from_commencement"] is None


@pytest.mark.django_db
def test_until_commencement_falls_back_to_replacing_edition(monkeypatch):
    """An edition-final version (no next version) proves its Until edge with
    the replacing edition's base-regulation record, found via
    EditionTransition; a mismatched ineffective date yields nothing."""
    from core.models import CodeEditionProvision, CodeEditionProvisionVersion

    monkeypatch.setattr(formatters, "_build_code_display_name", lambda c: c)
    edition, _base = _commencement_fixture()
    article = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.1.1.1.", level="article", division="C",
    )
    last = CodeEditionProvisionVersion.objects.create(
        provision=article, version=0,
        effective_date=date(2014, 1, 1), ineffective_date=date(2025, 1, 1),
    )
    res = formatters._format_single_result(
        {"code_edition": "OBC_2012", "provision": article, "version": last,
         "id": "1.1.1.1.", "division": "C"}
    )
    assert res["until_commencement"] is not None
    assert res["until_commencement"]["regulation"] == "163/24"
    assert res["until_commencement_date"] == date(2025, 1, 1)

    # Date guard: an ineffective date the replacing schedule doesn't set
    # (e.g. a staggered 2016 ending inside a 2025 replacement) gets nothing.
    stray = CodeEditionProvision.objects.create(
        edition=edition, provision_id="2.2.2.2.", level="article", division="C",
    )
    sv = CodeEditionProvisionVersion.objects.create(
        provision=stray, version=0,
        effective_date=date(2014, 1, 1), ineffective_date=date(2016, 1, 1),
    )
    res = formatters._format_single_result(
        {"code_edition": "OBC_2012", "provision": stray, "version": sv,
         "id": "2.2.2.2.", "division": "C"}
    )
    assert res["until_commencement"] is None
    assert res["until_commencement_date"] is None


def _version(version: int, title: str, eff: date, ineff: date | None) -> CodeEditionProvisionVersion:
    """An unsaved version row carrying only the fields _in_force_title reads."""
    return CodeEditionProvisionVersion(
        version=version, title=title, effective_date=eff, ineffective_date=ineff,
    )


def test_in_force_title_uses_version_in_force_not_latest():
    # v0 is in force 2022-04-26 → 2025-03-31, then the provision is revoked
    # (v1).  A query inside v0's window must read v0's real title, not the
    # newest ("Revoked: …") version's sentinel title.
    versions = [
        _version(0, "Temporary Health or Residential Facilities", date(2022, 4, 26), date(2025, 3, 31)),
        _version(1, "Revoked: O. Reg. 434/22, s. 1 (2).", date(2025, 3, 31), None),
    ]
    title = formatters._in_force_title(
        versions, date(2022, 6, 1), "1.3.7.", log_label="OBC_2012 C 1.3.7."
    )
    assert title == "Temporary Health or Residential Facilities"


def test_in_force_title_without_query_date_uses_latest():
    versions = [
        _version(0, "Application", date(2022, 4, 26), date(2024, 3, 28)),
        _version(1, "Revoked", date(2024, 3, 28), None),
    ]
    assert formatters._in_force_title(versions, None, "1.3.7.1.", log_label="x") == "Revoked"


def test_in_force_title_logs_error_when_nothing_in_force(caplog):
    versions = [
        _version(0, "Application", date(2022, 4, 26), date(2024, 3, 28)),
        _version(1, "Revoked", date(2024, 3, 28), None),
    ]
    # A date before the provision existed → nothing in force → error + latest.
    with caplog.at_level(logging.ERROR, logger="api.formatters"):
        title = formatters._in_force_title(
            versions, date(2000, 1, 1), "1.3.7.1.", log_label="OBC_2012 C 1.3.7.1."
        )
    assert title == "Revoked"
    assert any(
        "no version of OBC_2012 C 1.3.7.1. in force on 2000-01-01" in r.getMessage()
        for r in caplog.records
    )


def test_in_force_title_skips_zero_width_version():
    # A zero-width "as-filed but superseded same day" version is never in
    # force and must not be chosen as the label.
    versions = [
        _version(0, "Zero width", date(2022, 4, 26), date(2022, 4, 26)),
        _version(1, "Real", date(2022, 4, 26), None),
    ]
    assert formatters._in_force_title(versions, date(2022, 6, 1), "x", log_label="x") == "Real"


@pytest.mark.django_db
def test_formatter_merges_transition_pair_into_single_compare_result(monkeypatch):
    monkeypatch.setattr(formatters, "_build_code_display_name", lambda code_edition: code_edition)
    monkeypatch.setattr(formatters, "_load_group_hierarchy", lambda formatted_results, query_date=None: {})

    formatted_results = formatters.format_search_results(
        [
            {
                "id": "3.2.9.",
                "title": "Fire Separations",
                "code_edition": "BCBC_2024",
                "page": 120,
                "page_end": 122,
                "score": 1.0,
                "division": "B",
                "transition_context": {
                    "pair_key": "bcbc-3.2.9",
                    "query_date": "2024-06-01",
                    "new_version_effective_date": "2024-03-08",
                    "old_version_last_date": "2025-03-09",
                    "transition_type": "grace_period",
                    "transition_type_display": "grace period",
                    "applicability_text": "Applies during overlap.",
                    "citation_text": "Transition regulation",
                    "is_primary": True,
                },
                **a_match("BCBC_2024", "3.2.9."),
            },
            {
                "id": "3.2.9.",
                "title": "Fire Separations",
                "code_edition": "BCBC_2018",
                "page": 98,
                "page_end": 101,
                "score": 0.94,
                "division": "B",
                "transition_context": {
                    "pair_key": "bcbc-3.2.9",
                    "query_date": "2024-06-01",
                    "new_version_effective_date": "2024-03-08",
                    "old_version_last_date": "2025-03-09",
                    "transition_type": "grace_period",
                    "transition_type_display": "grace period",
                    "applicability_text": "Applies during overlap.",
                    "citation_text": "Transition regulation",
                    "is_primary": False,
                },
                **a_match("BCBC_2018", "3.2.9."),
            },
        ]
    )

    assert len(formatted_results) == 1
    assert formatted_results[0]["result_type"] == "transition_compare"
    assert formatted_results[0]["code"], "merged transition-compare must have a code field"
    assert len(formatted_results[0]["versions"]) == 2
    # R1: old edition first, new edition second
    assert formatted_results[0]["versions"][0]["code"] == "BCBC_2018"
    assert formatted_results[0]["versions"][1]["code"] == "BCBC_2024"


def test_diff_html_content_marks_unchanged_and_changed():
    old_html = "<p>The fire safety requirements apply to all buildings.</p>"
    new_html = "<p>The fire safety standards apply to most buildings.</p>"
    old_diff, new_diff = formatters.diff_html_content(old_html, new_html)
    assert old_diff is not None
    assert new_diff is not None
    # Both panes: unchanged text is lowlighted
    assert 'class="diff-old-unchanged"' in old_diff
    assert 'class="diff-new-unchanged"' in new_diff
    # And changed text is MARKED, not merely left un-dimmed. Bare changed
    # words made the only signal a 30% opacity step on the words the reader
    # is not looking for, and two real changes in OBC 2012 B 9.8.8.4. could
    # not be found on the page.
    assert '<span class="diff-old-changed">requirements</span>' in old_diff
    assert '<span class="diff-new-changed">standards</span>' in new_diff


def test_diff_html_content_coalesces_a_changed_run():
    # Adjacent changed words and the space between them are ONE mark, so a
    # struck phrase reads as a phrase. Marked per word it came out striped.
    old_html = "<p>designed for a concentrated horizontal load of 22 kN today</p>"
    new_html = "<p>designed and constructed to withstand the values today</p>"
    old_diff, new_diff = formatters.diff_html_content(old_html, new_html)
    assert old_diff is not None
    assert new_diff is not None
    assert (
        '<span class="diff-old-changed">for a concentrated horizontal load of 22 kN</span>'
        in old_diff
    )
    assert (
        '<span class="diff-new-changed">and constructed to withstand the values</span>'
        in new_diff
    )
    # The run stops at the edge of the change: the space before an unchanged
    # word stays outside the mark, or the band would run past the last word
    # that actually differs.
    assert '<span class="diff-old-changed">for' in old_diff
    assert 'kN</span> <span class="diff-old-unchanged">today</span>' in old_diff


def test_diff_html_content_never_spans_a_run_across_a_tag():
    # A span straddling `</p><p>` is invalid HTML, so a tag always ends a run.
    old_html = "<p>alpha bravo</p><p>charlie delta</p>"
    new_html = "<p>alpha xray</p><p>yankee delta</p>"
    old_diff, _ = formatters.diff_html_content(old_html, new_html)
    assert old_diff is not None
    assert "</p><p>" in old_diff
    for fragment in old_diff.split("<span"):
        assert "</p>" not in fragment.split("</span>")[0]


def test_diff_html_content_keeps_a_search_highlight_intact():
    # On the search transition panes the diff is built from HTML that
    # highlight_terms has already marked up. The redline must not eat that
    # mark — and this is why the changed-run band is a neutral ink wash
    # rather than the paper-yellow that <mark> already owns.
    old_html = "<p>a continuous curb not less than 150 mm</p>"
    new_html = "<p>a continuous curb not less than 140 mm</p>"
    old_diff, new_diff = formatters.diff_html_content(
        formatters.highlight_terms(old_html, ["curb"]),
        formatters.highlight_terms(new_html, ["curb"]),
    )
    assert old_diff is not None
    assert new_diff is not None
    assert '<mark class="match-highlight">' in old_diff
    assert '<span class="diff-old-changed">150</span>' in old_diff
    assert '<span class="diff-new-changed">140</span>' in new_diff


def test_diff_html_content_preserves_html_tags():
    old_html = "<p><strong>Fire</strong> safety requirements apply.</p>"
    new_html = "<p><strong>Fire</strong> safety standards apply.</p>"
    old_diff, new_diff = formatters.diff_html_content(old_html, new_html)
    assert old_diff is not None
    assert new_diff is not None
    # Original HTML tags should be preserved in the diff output
    assert "<p>" in old_diff
    assert "<strong>" in old_diff
    assert "</strong>" in old_diff
    assert "</p>" in old_diff
    assert "<p>" in new_diff
    assert "<strong>" in new_diff


def test_diff_html_content_preserves_original_whitespace():
    # "Act, 1997," should NOT get a space before the comma
    old_html = "<p>the Fire Protection and Prevention Act, 1997,</p>"
    new_html = "<p>the Fire Protection and Prevention Act, 1997,</p>"
    old_diff, new_diff = formatters.diff_html_content(old_html, new_html)
    assert old_diff is not None
    assert "1997 ," not in old_diff  # no spurious space before comma
    assert "1997," in old_diff
    # "onlydwelling" should stay unseparated if that's the original
    old_html2 = "<p>onlydwelling units</p>"
    new_html2 = "<p>onlydwelling units</p>"
    old_diff2, _ = formatters.diff_html_content(old_html2, new_html2)
    assert old_diff2 is not None
    assert "onlydwelling" in old_diff2  # no space inserted


def test_diff_is_empty_ignores_markup_and_whitespace():
    """The redline compares words, so the notice must compare words too.

    A reload can re-wrap a paragraph or change a class without a regulation
    touching the text.  Calling that "changed" would be a false alarm on the
    one surface whose whole job is to say what changed.
    """
    assert formatters.diff_is_empty(
        "<p>A fire separation shall be provided.</p>",
        "<p class='x'>A fire separation\n   shall be provided.</p>",
    )


def test_diff_is_empty_is_false_when_one_word_changed():
    assert not formatters.diff_is_empty(
        "<p>A fire separation shall be provided.</p>",
        "<p>A fire separation shall be installed.</p>",
    )


def test_diff_is_empty_is_false_when_a_side_is_empty():
    """Nothing was compared, so nothing can be reported as unchanged."""
    assert not formatters.diff_is_empty(None, "<p>text</p>")
    assert not formatters.diff_is_empty("<p>text</p>", "")


def test_transition_pair_states_that_the_text_did_not_change():
    """A renumber carries text forward verbatim — the common transition pair."""
    body = "<p>Smoke alarms shall be installed in each dwelling unit.</p>"
    pair = _transition_pair(
        old_id="9.10.18.6.",
        new_id="9.10.18.7.",
        old_clause=_StubClause("350/06"),
        new_clause=_StubClause("332/12"),
    )
    for version in pair:
        version["html_content"] = body
    merged = [
        r
        for r in formatters.merge_transition_compare_results(pair)
        if r.get("result_type") == "transition_compare"
    ]
    assert merged[0]["text_unchanged"] is True


def test_transition_pair_does_not_claim_no_change_when_a_word_moved():
    pair = _transition_pair(
        old_id="9.10.18.6.",
        new_id="9.10.18.7.",
        old_clause=_StubClause("350/06"),
        new_clause=_StubClause("332/12"),
    )
    pair[0]["html_content"] = "<p>Smoke alarms shall be installed in every unit.</p>"
    pair[1]["html_content"] = "<p>Smoke alarms shall be installed in each unit.</p>"
    merged = [
        r
        for r in formatters.merge_transition_compare_results(pair)
        if r.get("result_type") == "transition_compare"
    ]
    assert merged[0]["text_unchanged"] is False


@pytest.mark.django_db
def test_transition_pair_links_to_the_comparison_page(db):
    """The card's link is its own two versions, with no ladder in between.

    The prepared-pair ladder takes the local comparison first, so on a
    transition card it would open something other than the pair the card is
    about.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    editions = {
        year: CodeEdition.objects.create(
            code=code, edition_id=str(year), year=year,
            effective_date=date(year, 1, 1),
        )
        for year in (2006, 2012)
    }
    versions = {}
    for year, provision_id in ((2006, "9.10.18.6."), (2012, "9.10.18.7.")):
        provision = CodeEditionProvision.objects.create(
            edition=editions[year], provision_id=provision_id,
            level="article", division="B",
        )
        versions[year] = CodeEditionProvisionVersion.objects.create(
            provision=provision, version=0, title="Smoke Alarms",
            effective_date=date(year, 1, 1), html="<p>body</p>",
        )

    pair = _transition_pair(
        old_id="9.10.18.6.",
        new_id="9.10.18.7.",
        old_clause=_StubClause("350/06"),
        new_clause=_StubClause("332/12"),
    )
    pair[0]["version"] = versions[2012]
    pair[1]["version"] = versions[2006]
    merged = [
        r
        for r in formatters.merge_transition_compare_results(pair)
        if r.get("result_type") == "transition_compare"
    ]
    assert merged[0]["compare_url"] == (
        "/compare/?a=OBC_2006/B/9.10.18.6./v0&b=OBC_2012/B/9.10.18.7./v0"
    )


def test_transition_pair_omits_the_link_without_version_objects():
    """No dead anchor: the template tests the same empty string."""
    merged = [
        r
        for r in formatters.merge_transition_compare_results(
            _transition_pair(
                old_id="1.4.1.2.", new_id="1.4.1.2.",
                old_clause=_StubClause("350/06"),
                new_clause=_StubClause("332/12"),
            )
        )
        if r.get("result_type") == "transition_compare"
    ]
    assert merged[0]["compare_url"] == ""


def test_diff_html_content_returns_none_when_input_empty():
    assert formatters.diff_html_content(None, "<p>text</p>") == (None, None)
    assert formatters.diff_html_content("<p>text</p>", None) == (None, None)
    assert formatters.diff_html_content("", "<p>text</p>") == (None, None)
    assert formatters.diff_html_content(None, None) == (None, None)


class _StubRegulation:
    def __init__(self, reg_id: str) -> None:
        self.reg_id = reg_id


class _StubClause:
    def __init__(self, reg_id: str) -> None:
        self.regulation = _StubRegulation(reg_id)


def _transition_pair(*, old_id, new_id, old_clause, new_clause):
    """One pair_key'd old/new pair, in the order the formatter receives them."""
    return [
        {
            "id": new_id,
            "code": "OBC_1997",
            "score": 0.9,
            "clause": new_clause,
            "code_display_name": "OBC 1997",
            "transition_context": {"pair_key": "pair", "is_primary": True},
        },
        {
            "id": old_id,
            "code": "OBC_1997",
            "score": 0.8,
            "clause": old_clause,
            "code_display_name": "OBC 1997",
            "transition_context": {"pair_key": "pair", "is_primary": False},
        },
    ]


def _merged_versions(results):
    merged = [r for r in results if r.get("result_type") == "transition_compare"]
    assert len(merged) == 1
    return merged[0]["versions"]


def test_transition_pane_labels_name_each_introducing_regulation():
    old_version, new_version = _merged_versions(
        formatters.merge_transition_compare_results(
            _transition_pair(
                old_id="1.4.1.2.",
                new_id="1.4.1.2.",
                old_clause=_StubClause("350/06"),
                new_clause=_StubClause("332/12"),
            )
        )
    )
    assert old_version["pane_label"] == "350/06"
    assert new_version["pane_label"] == "332/12"


def test_transition_pane_labels_disambiguate_when_one_clause_made_both():
    """A cascading renumber amends a run of articles in a single directive, so
    both versions resolve to the same reg_id and the regulation alone stops
    telling the panes apart.  Each pane then leads with its own provision id."""
    shared_clause = _StubClause("22/98")
    old_version, new_version = _merged_versions(
        formatters.merge_transition_compare_results(
            _transition_pair(
                old_id="9.23.9.6.",
                new_id="9.23.9.7.",
                old_clause=shared_clause,
                new_clause=shared_clause,
            )
        )
    )
    assert old_version["pane_label"] == "9.23.9.6. · 22/98"
    assert new_version["pane_label"] == "9.23.9.7. · 22/98"


def test_transition_pane_labels_disambiguate_base_enactment_versions():
    """Neither version has a contributing clause, so both fall back to the same
    edition display name — the provision id is all that separates them."""
    old_version, new_version = _merged_versions(
        formatters.merge_transition_compare_results(
            _transition_pair(
                old_id="9.23.9.6.",
                new_id="9.23.9.7.",
                old_clause=None,
                new_clause=None,
            )
        )
    )
    assert old_version["pane_label"] == "9.23.9.6. · OBC 1997"
    assert new_version["pane_label"] == "9.23.9.7. · OBC 1997"


def test_has_renderable_content_false_when_no_content():
    result = formatters.merge_transition_compare_results(
        [
            {
                "id": "3.1",
                "code": "OBC_2024",
                "score": 0.9,
                "transition_context": {
                    "pair_key": "obc-3.1",
                    "is_primary": True,
                },
            },
            {
                "id": "3.1",
                "code": "OBC_2012",
                "score": 0.8,
                "transition_context": {
                    "pair_key": "obc-3.1",
                    "is_primary": False,
                },
            },
        ]
    )
    merged = [r for r in result if r.get("result_type") == "transition_compare"]
    assert len(merged) == 1
    assert merged[0]["has_renderable_content"] is False


def test_has_renderable_content_true_when_one_version_has_content():
    result = formatters.merge_transition_compare_results(
        [
            {
                "id": "3.1",
                "code": "OBC_2024",
                "score": 0.9,
                "html_content": "<p>Some text</p>",
                "transition_context": {
                    "pair_key": "obc-3.1",
                    "is_primary": True,
                },
            },
            {
                "id": "3.1",
                "code": "OBC_2012",
                "score": 0.8,
                "transition_context": {
                    "pair_key": "obc-3.1",
                    "is_primary": False,
                },
            },
        ]
    )
    merged = [r for r in result if r.get("result_type") == "transition_compare"]
    assert len(merged) == 1
    assert merged[0]["has_renderable_content"] is True


def _pair_member(provision_id, code, is_primary, pair_key, **extra):
    """A minimal formatted result carrying a transition_context pair member."""
    return {
        "id": provision_id,
        "code": code,
        "score": 0.9 if is_primary else 0.8,
        "transition_context": {
            "pair_key": pair_key,
            "is_primary": is_primary,
            "transition_text": "renumbered",
            **extra,
        },
    }


def test_same_edition_renumber_merges_into_one_compare_card():
    """Intra-edition renumber: members share an edition but have different ids.

    Regression for the degenerate self-compare — grouping on pair_key (not
    id+edition) must unite them into ONE card with the two distinct provisions,
    not two cards each comparing a provision to itself.
    """
    result = formatters.merge_transition_compare_results(
        [
            _pair_member("3.2.4.5.", "OBC_2024", True, "map:7", same_edition=True),
            _pair_member("3.1.2.1.", "OBC_2024", False, "map:7", same_edition=True),
        ]
    )
    merged = [r for r in result if r.get("result_type") == "transition_compare"]
    assert len(merged) == 1
    versions = merged[0]["versions"]
    assert [v["id"] for v in versions] == ["3.1.2.1.", "3.2.4.5."]  # [old, new]
    assert versions[0] is not versions[1]


def test_cross_edition_renumber_merges_into_one_compare_card():
    """Cross-edition renumber (different ids, different editions) — never
    grouped under the old id-based key; pair_key now unites it into one card."""
    result = formatters.merge_transition_compare_results(
        [
            _pair_member("3.2.4.5.", "OBC_2024", True, "map:9"),
            _pair_member("3.1.2.1.", "OBC_2012", False, "map:9"),
        ]
    )
    merged = [r for r in result if r.get("result_type") == "transition_compare"]
    assert len(merged) == 1
    assert [v["code"] for v in merged[0]["versions"]] == ["OBC_2012", "OBC_2024"]


def test_unpaired_member_renders_plain_not_self_compare():
    """A member whose partner didn't surface stays a plain result."""
    result = formatters.merge_transition_compare_results(
        [_pair_member("3.1", "OBC_2024", True, "map:11")]
    )
    assert len(result) == 1
    assert result[0].get("result_type") != "transition_compare"


@pytest.mark.django_db
def test_transition_context_passes_through_formatting(monkeypatch):
    monkeypatch.setattr(
        formatters, "_build_code_display_name",
        lambda code_edition: "Ontario Building Code 2012 v09",
    )
    monkeypatch.setattr(formatters, "_load_group_hierarchy", lambda formatted_results, query_date=None: {})

    # A single member whose pair partner didn't surface in results: the context
    # must survive formatting verbatim (and render plainly, not compare-to-self).
    transition_context = {
        "pair_key": "overlap:8.6.2.2:B",
        "is_primary": True,
        "transition_text": "Transition regulation text",
    }

    formatted = formatters.format_search_results(
        [
            {
                "id": "8.6.2.2",
                "title": "Fire Safety",
                "code_edition": "OBC_2012_v09",
                "score": 0.95,
                "transition_context": transition_context,
                **a_match("OBC_2012_v09", "8.6.2.2"),
            }
        ]
    )

    assert len(formatted) == 1
    item = formatted[0]
    assert item["transition_context"] is not None
    assert item["transition_context"]["is_primary"] is True
    assert item["transition_context"]["pair_key"] == "overlap:8.6.2.2:B"
    assert item["transition_context"]["transition_text"] == "Transition regulation text"
    # Unpaired -> plain result, never a degenerate self-compare.
    assert item.get("result_type") != "transition_compare"


def test_nest_child_results_under_parent():
    results: list[dict[str, Any]] = [
        {"id": "3.2", "parent_id": None, "score": 0.9, "code": "OBC_2024", "title": "Parent",
         "division": "B"},
        {"id": "3.2.1", "parent_id": "3.2", "score": 0.85, "code": "OBC_2024", "title": "Child A",
         "division": "B"},
        {"id": "3.2.2", "parent_id": "3.2", "score": 0.80, "code": "OBC_2024", "title": "Child B",
         "division": "B"},
    ]
    nested = formatters._nest_child_results(results)
    assert len(nested) == 1
    parent = nested[0]
    assert parent["id"] == "3.2"
    assert parent["group_type"] == "parent_children"
    assert len(parent["children"]) == 2
    assert parent["children"][0]["id"] == "3.2.1"
    assert parent["children"][1]["id"] == "3.2.2"
    assert all(c["is_match"] for c in parent["children"])
    assert parent["top_scoring_child_id"] == "3.2.1"
    assert parent["child_match_count"] == 2
    assert parent["child_total_count"] == 2


def test_nest_child_results_cross_edition_no_collision():
    """Same section IDs across editions must not collide or drop results."""
    results: list[dict[str, Any]] = [
        # OBC parent + children
        {"id": "3.2", "parent_id": None, "score": 0.9, "code": "OBC_2024",
         "division": "B", "title": "OBC Parent"},
        {"id": "3.2.1", "parent_id": "3.2", "score": 0.85, "code": "OBC_2024",
         "division": "B", "title": "OBC Child A"},
        {"id": "3.2.2", "parent_id": "3.2", "score": 0.80, "code": "OBC_2024",
         "division": "B", "title": "OBC Child B"},
        # NBC parent + children with identical node IDs
        {"id": "3.2", "parent_id": None, "score": 0.7, "code": "NBC_2020",
         "division": "B", "title": "NBC Parent"},
        {"id": "3.2.1", "parent_id": "3.2", "score": 0.65, "code": "NBC_2020",
         "division": "B", "title": "NBC Child A"},
        {"id": "3.2.2", "parent_id": "3.2", "score": 0.60, "code": "NBC_2020",
         "division": "B", "title": "NBC Child B"},
    ]
    nested = formatters._nest_child_results(results)
    # Both editions should produce their own grouped parent card
    assert len(nested) == 2
    obc = [r for r in nested if r.get("code") == "OBC_2024"][0]
    nbc = [r for r in nested if r.get("code") == "NBC_2020"][0]
    assert obc["group_type"] == "parent_children"
    assert nbc["group_type"] == "parent_children"
    assert len(obc["children"]) == 2
    assert len(nbc["children"]) == 2
    # Children titles should be edition-specific (not overwritten)
    assert obc["children"][0]["title"].startswith("OBC")
    assert nbc["children"][0]["title"].startswith("NBC")


class TestScoreExplanation:
    """Plain-English 'why this matched' phrasing driven by match_type."""

    def test_exact_id_names_the_provision(self):
        out = formatters._build_score_explanation("exact_id", ["9.10.14"])
        assert "9.10.14" in out
        assert "this is that provision" in out

    def test_table_ref_label_is_humanized(self):
        out = formatters._build_score_explanation("table_ref", ["table-3.1.4.7"])
        assert "Table 3.1.4.7" in out  # 'table-' prefix → 'Table ', trailing dot gone

    def test_ancestor_id_reads_as_sub_provision(self):
        out = formatters._build_score_explanation("ancestor_id", ["3.2"])
        assert out.startswith("A sub-provision of 3.2")

    def test_exact_keywords_listed(self):
        out = formatters._build_score_explanation("exact", ["fire", "sprinkler"])
        assert out == "Directly matched your search for fire and sprinkler."

    def test_direct_and_indirect_are_split(self):
        # The "defined terms" case: typed words are direct, LLM variants indirect.
        out = formatters._build_score_explanation(
            "exact", ["defined", "terms"], ["definition", "definitions"]
        )
        assert "Directly matched your search for defined and terms" in out
        assert "indirectly matched definition and definitions" in out

    def test_synonym_only_reads_as_indirect(self):
        # A synonym-only result carries its terms in the indirect list.
        out = formatters._build_score_explanation("synonym", [], ["egress"])
        assert out.startswith("Indirectly matched egress")
        assert "synonym" in out.lower()

    def test_fuzzy_is_labelled(self):
        out = formatters._build_score_explanation("fuzzy", ["sprinkler"])
        assert "approximate" in out.lower()

    def test_three_terms_use_oxford_join(self):
        out = formatters._build_score_explanation("exact", ["a", "b", "c"])
        assert "a, b, and c" in out


@pytest.mark.django_db
def test_format_single_result_surfaces_explanation_and_suppresses_ref_chips():
    """Reference matches get an explanation but no (redundant) term chips."""
    formatted = formatters._format_single_result(
        {
            "id": "3.1.4.7.",
            "title": "Cooling",
            "code_edition": "OBC_2024",
            "division": "B",
            "score": 3.0,
            "match_type": "exact_id",
            "matched_terms": ["3.1.4.7"],
            **a_match("OBC_2024", "3.1.4.7."),
        },
        query_date=None,
    )
    assert formatted["score_explanation"]
    assert "3.1.4.7" in formatted["score_explanation"]
    assert formatted["show_matched_terms"] is False  # reference → chips suppressed


@pytest.mark.django_db
def test_format_single_result_shows_chips_for_keyword_match():
    formatted = formatters._format_single_result(
        {
            "id": "3.1.8.5.",
            "title": "Fire Sprinkler Systems",
            "code_edition": "OBC_2024",
            "division": "B",
            "score": 0.9,
            "match_type": "exact",
            "matched_terms": ["fire", "sprinkler"],
            **a_match("OBC_2024", "3.1.8.5."),
        },
        query_date=None,
    )
    assert formatted["show_matched_terms"] is True
    assert formatted["matched_terms"] == ["fire", "sprinkler"]


@pytest.mark.django_db
def test_format_search_results_attaches_lineage(monkeypatch):
    """Every result carries lineage keys from one batched resolver call.

    Both directions are asserted on one provision: the mapping gives it a
    successor, and the absence of a mapping the other way gives it
    ``no_data_yet`` rather than a missing key.
    """
    monkeypatch.setattr(formatters, "_build_code_display_name", lambda c: c)
    monkeypatch.setattr(
        formatters, "_load_group_hierarchy", lambda formatted_results, query_date=None: {}
    )
    system = Code.objects.create(code="OBC", display_name="OBC")
    e2006 = CodeEdition.objects.create(
        code=system, edition_id="2006", year=2006,
        effective_date=date(2006, 12, 31), ineffective_date=date(2014, 1, 1),
    )
    e2012 = CodeEdition.objects.create(
        code=system, edition_id="2012", year=2012, effective_date=date(2014, 1, 1),
    )
    EditionTransition.objects.create(old_edition=e2006, new_edition=e2012)
    old = CodeEditionProvision.objects.create(
        edition=e2006, provision_id="9.10.18.6.", level="article", division="B",
    )
    new = CodeEditionProvision.objects.create(
        edition=e2012, provision_id="9.10.18.7.", level="article", division="B",
    )
    made = {
        prov: CodeEditionProvisionVersion.objects.create(
            provision=prov, version=0, effective_date=prov.edition.effective_date,
        )
        for prov in (old, new)
    }
    ProvisionMapping.objects.create(
        old_provision=old, new_provision=new, mapping_type="renumbered",
    )

    formatted = formatters.format_search_results(
        [
            {
                "id": "9.10.18.6.", "title": "Old", "code_edition": "OBC_2006",
                "division": "B", "score": 2.0, "provision": old,
                "version": made[old],
            },
        ]
    )

    with_prov = formatted[0]
    succ = with_prov["lineage_successors"]
    assert succ.state == "linked"
    assert succ.links[0].provision == new
    assert succ.links[0].verb == "renumbered to"
    assert succ.links[0].locked is False  # gating disabled → never locked
    assert with_prov["lineage_predecessors"].state == "no_data_yet"


class TestPartExplanation:
    """Why a result moved, in a sentence the reader can check.

    A re-ordering nobody can trace back to an article is a number we are
    asking them to trust, which is the opposite of what this product sells.
    """

    HOUSE = {"occupancy": "residential", "storeys": 2, "area": 140.0, "area_unit": "m2"}
    MOVED_UP = {
        "part_verdict": "applies", "part_number": 9, "part_factor": 1.35,
        "part_source": "Division A 1.1.2.4.",
    }
    MOVED_DOWN = {
        "part_verdict": "excluded", "part_number": 3, "part_factor": 0.8,
        "part_source": "Division A 1.1.2.2.",
    }

    def test_it_names_the_multiplier_the_part_and_the_article(self):
        out = formatters._build_part_explanation(self.MOVED_UP, self.HOUSE)

        assert "\u00d71.35" in out
        assert "Part 9 governs" in out
        assert "Division A 1.1.2.4." in out

    def test_a_demoted_result_says_so(self):
        out = formatters._build_part_explanation(self.MOVED_DOWN, self.HOUSE)

        assert out.startswith("Ranked down")
        assert "does not govern" in out

    def test_the_multiplier_always_carries_two_decimals(self):
        """"×0.8" beside "×1.35" reads as a different kind of number, and the
        two are meant to be compared."""
        assert "\u00d70.80" in formatters._build_part_explanation(
            self.MOVED_DOWN, self.HOUSE
        )

    def test_it_quotes_the_readers_own_figure_and_unit(self):
        """Not the converted ``area_m2``: the control, the address and this
        sentence must all show the number they typed."""
        sqft = {"occupancy": "residential", "storeys": 1, "area": 1500.0,
                "area_unit": "sqft", "area_m2": 139.35}
        out = formatters._build_part_explanation(self.MOVED_UP, sqft)

        assert "1500 ft\u00b2" in out
        assert "139" not in out

    def test_an_unsized_occupancy_states_no_measurement(self):
        """Division A 1.1.2.2.(1)(a) applies no size test to Group A, so the
        sentence must not imply one was used."""
        out = formatters._build_part_explanation(
            {"part_verdict": "applies", "part_number": 3, "part_factor": 1.35,
             "part_source": "Division A 1.1.2.2."},
            {"occupancy": "assembly"},
        )

        assert "an assembly building" in out
        assert "storey" not in out

    def test_an_unknown_verdict_explains_nothing(self):
        assert formatters._build_part_explanation({"part_verdict": "unknown"}, self.HOUSE) == ""

    def test_a_search_with_no_building_explains_nothing(self):
        assert formatters._build_part_explanation(self.MOVED_UP, {}) == ""

    def test_one_storey_is_not_pluralised(self):
        out = formatters._build_part_explanation(
            self.MOVED_UP, {"occupancy": "residential", "storeys": 1}
        )

        assert "1 storey " in out or "1 storey(" in out
        assert "1 storeys" not in out
