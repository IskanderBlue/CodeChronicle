from datetime import date

import pytest
from django.test import Client

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionVersionTable,
    Regulation,
    RegulationClause,
)


@pytest.fixture
def regulation_fixtures(db):
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="1997", year=1997,
        effective_date=date(1998, 4, 6),
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


@pytest.fixture
def redline_reg(db):
    """A regulation with two clauses: one single strike-sub directive (a clean
    redline) and one multi-directive clause (whose collapsed strike_text/
    sub_text would render a misleading one-sided redline)."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012, effective_date=date(2014, 1, 1),
    )
    reg = Regulation.objects.create(
        reg_id="88/19", edition=edition, role="amendment",
        effective_date=date(2020, 1, 1),
    )
    # Single directive: strike "X" and substitute "Y" — a faithful redline.
    RegulationClause.objects.create(
        regulation=reg, clause_id="10(1)", action="amend_strike_sub",
        target_level="sentence", target_id="1.1.1.1.(1)",
        strike_text="X", sub_text="Y",
        directives=[{"action": "amend_strike_sub", "strike_text": "X",
                     "sub_text": "Y", "target_id": "1.1.1.1.(1)"}],
        clause_text="strike X substitute Y",
    )
    # Multiple directives: top-level columns collapse to the primary directive
    # (strike "and", empty substitution) — the case that read as a bug.
    RegulationClause.objects.create(
        regulation=reg, clause_id="92(2)", action="amend_strike_sub",
        target_level="sentence", target_id="3.6.4.3.(2)",
        strike_text="and", sub_text="",
        directives=[
            {"action": "amend_strike_sub", "strike_text": "and", "sub_text": ""},
            {"action": "amend_add", "add_text": "and", "target_id": "3.6.4.3.(2)(c)"},
            {"action": "amend_add", "target_id": "3.6.4.3.(2)"},
        ],
        clause_text="amended by striking out and adding clauses",
    )
    return reg


@pytest.mark.django_db
class TestChangeRedline:
    """The margin 'Change' redline: faithful for a single directive, replaced
    by 'Multiple' when a clause collapses several directives (so we don't show
    one strike with an empty substitution — more heat than light)."""

    def test_single_directive_shows_redline(self, client: Client, redline_reg):
        content = client.get(f"/regulation/{redline_reg.pk}/").content.decode()
        # The clean strike->sub redline is present and not labelled "Multiple".
        assert "line-through decoration-strike" in content

    def test_multiple_directives_show_multiple(self, client: Client, redline_reg):
        content = client.get(f"/regulation/{redline_reg.pk}/").content.decode()
        assert ">Multiple<" in content

    def test_multiple_directives_suppress_empty_substitution(
        self, client: Client, redline_reg,
    ) -> None:
        """The 92(2) clause must NOT render its collapsed strike 'and' with an
        empty substitution — that was the reported bug."""
        content = client.get(f"/regulation/{redline_reg.pk}/").content.decode()
        # Exactly one redline (the single-directive clause), not two.
        assert content.count("line-through decoration-strike") == 1


@pytest.fixture
def staggered_reg(db):
    """A regulation with staggered commencement: a default in-force date plus
    a deferred record, and one on-time + one deferred clause."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012,
        effective_date=date(2014, 1, 1),
    )
    reg = Regulation.objects.create(
        reg_id="332/12", edition=edition, role="base",
        effective_date=date(2014, 1, 1),
        commencement=[
            {
                "clause": "4.4.1.1(1)", "is_default": True,
                "effective_date": "2014-01-01", "resolved_provisions": [],
                "commencement_clause": "This Regulation comes into force on "
                                       "January 1, 2014.",
            },
            {
                "clause": "4.4.1.1(2)", "is_default": False,
                "effective_date": "2016-01-01",
                # Two sentences + a table on the same article all collapse to
                # 4.2.1.1. and dedupe to one entry; the appendix table has no
                # article address, so it stays an unlinked label.
                "resolved_provisions": [
                    "4.2.1.1.(1).|C", "4.2.1.1.(4).|C",
                    "Table-4.2.1.1.C.|C", "Table-A-10|B",
                ],
                "commencement_clause": "Sentences 4.2.1.1.(1) and (4) come into "
                                       "force on January 1, 2016.",
            },
        ],
    )
    # The provision the deferred record points at, so its schedule entry
    # resolves to a real dated permalink (v0 from 2014, v1 the deferral
    # brings in on 2016-01-01 — the schedule should link v1).
    deferred_prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id="4.2.1.1.", level="article", division="C",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=deferred_prov, version=0,
        effective_date=date(2014, 1, 1), ineffective_date=date(2016, 1, 1),
    )
    CodeEditionProvisionVersion.objects.create(
        provision=deferred_prov, version=1, effective_date=date(2016, 1, 1),
    )
    # An appendix table (Table-A-10) has no article address of its own — the
    # link lives on the provision side: a Division B article owns it via a
    # ProvisionVersionTable.  The schedule should link the table to that owner.
    table_owner = CodeEditionProvision.objects.create(
        edition=edition, provision_id="9.23.4.2.", level="article", division="B",
    )
    owner_v0 = CodeEditionProvisionVersion.objects.create(
        provision=table_owner, version=0, effective_date=date(2014, 1, 1),
    )
    ProvisionVersionTable.objects.create(version=owner_v0, table_id="Table-A-10")
    RegulationClause.objects.create(
        regulation=reg, clause_id="0_on_time", target_id="1.1.1.1.",
        effective_date=date(2014, 1, 1), clause_text="on-time clause",
        commencement={
            "regulation": "332/12", "clause": "4.4.1.1(1)", "is_default": True,
            "effective_date": "2014-01-01", "source": "parsed",
            "commencement_clause": "This Regulation comes into force on "
                                   "January 1, 2014.",
        },
    )
    RegulationClause.objects.create(
        regulation=reg, clause_id="1_deferred", target_id="4.2.1.1.",
        effective_date=date(2016, 1, 1), clause_text="deferred clause",
        add_text="(FT1 Rating)", add_anchor="after:CSA",
        directives=[{"action": "amend_add", "target_id": "1.10.2.3.(2)"}],
        commencement={
            "regulation": "332/12", "clause": "4.4.1.1(2)", "is_default": False,
            "effective_date": "2016-01-01", "source": "commencement-input",
            "commencement_clause": "Sentences 4.2.1.1.(1) and (4) come into "
                                   "force on January 1, 2016.",
            "depends_on": {
                "legislation": "Lake Simcoe Protection Act, 2008",
                "provision": "Section 2", "date_type": "proclamation",
                "date": "2016-01-01",
            },
            "computation": "later of filing and proclamation",
        },
    )
    return reg


@pytest.mark.django_db
class TestCommencementDisplay:
    """The regulation's staggered commencement schedule and each clause's
    own in-force date surface on the detail page."""

    def test_schedule_renders_when_staggered(self, client: Client, staggered_reg):
        response = client.get(f"/regulation/{staggered_reg.pk}/")
        content = response.content.decode()
        assert "Commencement schedule" in content
        assert "1 January 2016" in content          # the deferred in-force date
        assert "Deferred" in content
        # Refs are reduced to their containing provision and deduped: the two
        # sentence refs and the table on 4.2.1.1. collapse to a single entry,
        # so the verbatim sentence ref no longer appears as a label.
        assert "4.2.1.1.(1)." not in content
        assert "4.2.1.1." in content
        # Provisions are grouped by Division · Part (so the division shows in
        # the group heading, not on every chip).
        assert "Div C · Part 4" in content
        # The list is default-collapsed behind a count toggle (88/19 lists
        # dozens) and each ref links to the provision as it reads on the
        # deferral's date — v1, the version the deferral brings into force.
        # Count is the article plus the appendix table = 2.
        assert "2 provisions" in content
        assert "showProvs" in content
        assert "/provision/OBC_2012/C/4.2.1.1./v1/" in content
        # The appendix table is shown as "Table A-10" and linked to its owning
        # provision (resolved on the provision side via ProvisionVersionTable),
        # at the version in force on the deferral date — owner v0.
        assert "Table A-10" in content
        assert "/provision/OBC_2012/B/9.23.4.2./v0/" in content
        assert "Div&nbsp;B" in content              # owner's division, on the table line

    def test_clause_shows_own_in_force_date(self, client: Client, staggered_reg):
        response = client.get(f"/regulation/{staggered_reg.pk}/")
        content = response.content.decode()
        assert "In force" in content
        assert "2016-01-01" in content              # deferred clause's date
        # The deferred clause is flagged in highlight; the on-time one is not.
        assert "text-highlight" in content

    def test_no_schedule_when_only_default(self, client: Client, db):
        code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
        edition = CodeEdition.objects.create(
            code=code, edition_id="2012", year=2012,
            effective_date=date(2014, 1, 1),
        )
        reg = Regulation.objects.create(
            reg_id="999/12", edition=edition, role="base",
            effective_date=date(2014, 1, 1),
            commencement=[
                {
                    "clause": "x(1)", "is_default": True,
                    "effective_date": "2014-01-01", "resolved_provisions": [],
                    "commencement_clause": "Comes into force on January 1, 2014.",
                },
            ],
        )
        RegulationClause.objects.create(
            regulation=reg, clause_id="1", target_id="1.1.1.1.",
            effective_date=date(2014, 1, 1), clause_text="c",
        )
        response = client.get(f"/regulation/{reg.pk}/")
        content = response.content.decode()
        # No deferred record → the header's EFFECTIVE date is the whole story.
        assert "Commencement schedule" not in content


@pytest.mark.django_db
class TestCommencementPopup:
    """Clicking a clause's Deferred/Default marker opens a popup showing the
    CommencementProvenance (the *why* behind the in-force date)."""

    def test_marker_opens_popup_with_provenance(self, client: Client, staggered_reg):
        content = client.get(f"/regulation/{staggered_reg.pk}/").content.decode()
        # Trigger wiring + teleported modal.
        assert "cmOpen" in content
        assert "x-teleport" in content
        assert 'title="Why this date? — commencement provenance"' in content
        # Provenance detail body.
        assert "How this date was set" in content
        assert "come into force on January 1, 2016" in content   # verbatim text
        # Statute dependency surfaced.
        assert "Lake Simcoe Protection Act, 2008" in content
        assert "later of filing and proclamation" in content     # computation


@pytest.mark.django_db
class TestClauseIndexAndOverflow:
    """The detail page carries a sticky scroll-spy clause index (jump
    navigation) and caps long clause text behind an expand toggle."""

    def test_index_lists_each_clause(self, client: Client, staggered_reg):
        response = client.get(f"/regulation/{staggered_reg.pk}/")
        content = response.content.decode()
        assert 'aria-label="Clauses"' in content
        # One jump link in the index per clause card.
        assert content.count('href="#clause-') == 2
        for clause in staggered_reg.clauses.all():
            assert f'href="#clause-{clause.pk}"' in content
        # Cards are observable, and the scroll-spy is wired.
        assert "data-clause-anchor" in content
        assert "IntersectionObserver" in content

    def test_long_content_is_collapsible_and_scrollable(
        self, client: Client, staggered_reg,
    ):
        response = client.get(f"/regulation/{staggered_reg.pk}/")
        content = response.content.decode()
        # Expand toggle + horizontal-scroll containment for wide e-Laws tables.
        assert "Show full text" in content
        assert "overflow-x-auto" in content

    def test_clauses_ordered_numerically(self, client: Client, db):
        """clause_id is a CharField, so a DB sort is lexicographic (1, 10, 11,
        2, …).  The page must order clauses numerically (1, 2, …, 10, 11)."""
        code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
        edition = CodeEdition.objects.create(
            code=code, edition_id="2012", year=2012, effective_date=date(2014, 1, 1),
        )
        reg = Regulation.objects.create(
            reg_id="1/19", edition=edition, role="amendment",
            effective_date=date(2019, 1, 1),
        )
        for cid in ["1", "2", "10", "11", "3"]:
            RegulationClause.objects.create(
                regulation=reg, clause_id=cid, target_id="1.1.1.1.",
                clause_text=f"clause {cid}",
            )
        content = client.get(f"/regulation/{reg.pk}/").content.decode()
        # Index labels appear in numeric order, not lexicographic.
        positions = [content.index(f"cl. {cid}</span>") for cid in ["1", "2", "3", "10", "11"]]
        assert positions == sorted(positions)
        # Guard against the lexicographic bug specifically: 2 must precede 10.
        assert content.index("cl. 2</span>") < content.index("cl. 10</span>")


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


@pytest.mark.django_db
class TestProvisionPermalinkUrl:
    """``_provision_permalink_url`` must route division-less editions (OBC 1997,
    division="") to the no-division route — a ``<str:division>`` segment can't
    be empty, so the normal route raises ``NoReverseMatch``."""

    def test_with_division_uses_full_route(self):
        from core.views.regulation import _provision_permalink_url

        url = _provision_permalink_url("OBC_2024", "B", "3.1.1.1", 2)
        assert url == "/provision/OBC_2024/B/3.1.1.1/v2/"

    def test_empty_division_uses_no_division_route(self):
        from core.views.regulation import _provision_permalink_url

        # Must not raise NoReverseMatch, and must omit the division segment.
        url = _provision_permalink_url("OBC_1997", "", "3.1.1.1", 1)
        assert url == "/provision/OBC_1997/3.1.1.1/v1/"


class TestReduceProvisionRef:
    """``_reduce_provision_ref`` collapses a commencement ref to its
    containing article so the schedule lists one linked entry per provision.
    Cases drawn from real OBC 2012 ``resolved_provisions`` (O. Reg. 88/19)."""

    @pytest.mark.parametrize(("ref", "expected"), [
        # Sentence / clause / subclause → drop everything from the first "(".
        ("4.2.1.1.(1).", "4.2.1.1."),
        ("1.4.1.2.(1)(b)(ii)", "1.4.1.2."),
        ("3.1.4.2.(1)", "3.1.4.2."),
        # Whole-article ref → unchanged.
        ("3.1.4.2.", "3.1.4.2."),
        ("3.3.2.", "3.3.2."),                       # a section-level ref
        # Table → strip "Table-", keep the first four dotted segments; the
        # trailing table-letter (5th segment) is dropped.
        ("Table-1.3.1.2.", "1.3.1.2."),
        ("Table-11.2.1.1.B.", "11.2.1.1."),
        ("Table-11.5.1.1.D/E.", "11.5.1.1."),
        ("Table-9.20.5.2.C.", "9.20.5.2."),
        # A 4th segment may itself carry a letter — that stays.
        ("Table-3.3.2.8A.", "3.3.2.8A."),
        ("Table-8.7.3.1A.", "8.7.3.1A."),
        # Appendix table (Table-A-<n>) has no article address → unchanged.
        ("Table-A-10", "Table-A-10"),
        ("Table-A-13", "Table-A-13"),
    ])
    def test_reduces_to_containing_article(self, ref: str, expected: str):
        from core.views.regulation import _reduce_provision_ref

        assert _reduce_provision_ref(ref) == expected


class TestGroupProvisions:
    """``_group_provisions`` buckets provisions by Division then Part so a
    large deferral reads as labelled blocks, and fixes cross-division
    interleaving that a flat provision_id sort would cause."""

    def _provs(self, *refs):
        # refs as (provision_id, division)
        return [{"provision_id": pid, "division": div, "url": None} for pid, div in refs]

    def test_groups_by_division_then_part_in_order(self):
        from core.views.regulation import _group_provisions

        groups = _group_provisions(self._provs(
            ("11.2.1.1.", "B"), ("3.1.3.1.", "B"), ("1.1.2.1.", "A"),
            ("3.2.2.6.", "B"),
        ))
        # Division A before B; within B, Part 3 before Part 11 (numeric, not
        # lexicographic — "11" must not sort before "3").
        assert [g["label"] for g in groups] == [
            "Div A · Part 1", "Div B · Part 3", "Div B · Part 11",
        ]
        # Within a part, natural-sorted.
        part3 = next(g for g in groups if g["label"] == "Div B · Part 3")
        assert [p["provision_id"] for p in part3["provisions"]] == ["3.1.3.1.", "3.2.2.6."]

    def test_division_less_edition_labels_part_only(self):
        from core.views.regulation import _group_provisions

        groups = _group_provisions(self._provs(("3.1.1.1.", ""), ("3.2.1.1.", "")))
        assert [g["label"] for g in groups] == ["Part 3"]
