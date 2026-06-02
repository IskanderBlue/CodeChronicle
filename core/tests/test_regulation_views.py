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
                "resolved_provisions": ["4.2.1.1.(1).|C", "4.2.1.1.(4).|C"],
                "commencement_clause": "Sentences 4.2.1.1.(1) and (4) come into "
                                       "force on January 1, 2016.",
            },
        ],
    )
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
        assert "4.2.1.1.(1)." in content            # a resolved provision
        assert "Div&nbsp;C" in content              # its division, split from the ref

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
