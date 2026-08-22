"""The part that governs the reader's building ranks above the one that does not.

The fixture reproduces the shape of the real failure this work exists to fix:
searching for guards returns a Part 3 provision (exit stairs in a large
building) above the Part 9 provision that governs a house, because ``Guards``
is a short title and the BM25F title field rewards a match that fills the
field.  Nothing in the score knows which part applies.

The boost is a multiplier, never a filter, so every assertion here also checks
that the demoted provision is still on the page.  A house is routinely
governed by a Part 3 provision through a cross-reference.
"""

from datetime import date

import pytest

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvinceCode,
)
from search.engine.orchestration import execute_search

PART_9 = "9.8.8.1."
PART_3 = "3.4.6.5."


@pytest.fixture
def guards(db):
    """One Part 9 guard provision and one Part 3 guard provision, in OBC 2012.

    The Part 3 title is one word and scores higher, which is the state of the
    product before this boost.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)
    edition = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012, effective_date=date(2014, 1, 1)
    )

    def _provision(provision_id, title, counts, title_counts):
        provision = CodeEditionProvision.objects.create(
            edition=edition,
            provision_id=provision_id,
            level=CodeEditionProvision.Level.ARTICLE,
            division="B",
        )
        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=0,
            effective_date=date(2014, 1, 1),
            title=title,
            html=f"<p>{title}.</p>",
            keyword_counts=counts,
            title_keyword_counts=title_counts,
        )
        return provision

    _provision(PART_3, "Guards", {"guards": 2}, {"guards": 1})
    _provision(
        PART_9,
        "Required Guards",
        {"guards": 3, "stair": 4, "dwelling": 2},
        {"guards": 1, "required": 1},
    )
    return edition


def _ranks(response) -> dict[str, int]:
    return {r["id"]: i for i, r in enumerate(response["results"])}


def _search(**building):
    params = {"date": "2015-06-01", "keywords": ["guards"], "province": "ON"}
    params.update(building)
    return execute_search(params)


@pytest.mark.django_db
class TestTheBoostChangesTheOrder:
    def test_without_a_building_the_short_title_still_wins(self, guards):
        """The state this card set out to change.  If this ever fails the
        fixture has stopped reproducing the problem, and the tests below are
        proving nothing."""
        ranks = _ranks(_search())

        assert ranks[PART_3] < ranks[PART_9]

    def test_a_house_ranks_the_part_9_provision_first(self, guards):
        ranks = _ranks(
            _search(occupancy="residential", storeys=2, area_m2=140)
        )

        assert ranks[PART_9] < ranks[PART_3]

    def test_a_four_storey_house_ranks_the_part_3_provision_first(self, guards):
        """The townhouse.  Part 9 needs three storeys or fewer *and* 600 m² or
        less, so the storey count decides it whatever the area — and a model
        guessing "house means two storeys" would have answered the opposite."""
        ranks = _ranks(
            _search(occupancy="residential", storeys=4, area_m2=140)
        )

        assert ranks[PART_3] < ranks[PART_9]

    def test_an_assembly_building_needs_no_measurement(self, guards):
        """Division A 1.1.2.2.(1)(a) states no size test for Group A."""
        ranks = _ranks(_search(occupancy="assembly"))

        assert ranks[PART_3] < ranks[PART_9]

    def test_an_unmeasured_house_is_left_alone(self, guards):
        """Two storeys and no area decides nothing: the unstated area may be
        the measurement that breaches.  The order must be the untouched one."""
        assert _ranks(_search(occupancy="residential", storeys=2)) == _ranks(_search())


@pytest.mark.django_db
class TestNothingBecomesUnreachable:
    @pytest.mark.parametrize(
        "building",
        [
            {"occupancy": "residential", "storeys": 2, "area_m2": 140},
            {"occupancy": "residential", "storeys": 4, "area_m2": 140},
            {"occupancy": "assembly"},
        ],
    )
    def test_both_provisions_are_still_returned(self, guards, building):
        ids = {r["id"] for r in _search(**building)["results"]}

        assert ids == {PART_3, PART_9}

    def test_a_demoted_provision_keeps_a_score_above_zero(self, guards):
        results = {
            r["id"]: r for r in _search(occupancy="assembly")["results"]
        }

        assert results[PART_9]["score"] > 0


@pytest.mark.django_db
class TestTheVerdictIsReported:
    """A page that reorders itself without saying why is a page the reader
    cannot check."""

    def test_each_result_carries_its_verdict(self, guards):
        results = {
            r["id"]: r
            for r in _search(occupancy="residential", storeys=4, area_m2=140)["results"]
        }

        assert results[PART_3]["part_verdict"] == "applies"
        assert results[PART_9]["part_verdict"] == "excluded"

    def test_no_building_reports_no_verdict(self, guards):
        for result in _search()["results"]:
            assert "part_verdict" not in result
