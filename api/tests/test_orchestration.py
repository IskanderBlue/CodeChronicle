from datetime import date

import pytest

from api.search.orchestration import _limit_with_pairs, execute_search
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvinceCode,
)


@pytest.fixture
def obc_setup(db):
    """Create a minimal OBC code system with one edition and provisions."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)

    edition = CodeEdition.objects.create(
        code=code,
        edition_id="2024",
        year=2024,
        effective_date=date(2024, 1, 1),
    )

    parent_prov = CodeEditionProvision.objects.create(
        edition=edition,
        provision_id="3.2",
        level=CodeEditionProvision.Level.SECTION,
        division="B",
    )
    child_prov = CodeEditionProvision.objects.create(
        edition=edition,
        provision_id="3.2.9",
        level=CodeEditionProvision.Level.SUBSECTION,
        division="B",
        parent=parent_prov,
    )

    parent_version = CodeEditionProvisionVersion.objects.create(
        provision=parent_prov,
        version=0,
        effective_date=date(2024, 1, 1),
        title="Fire Safety",
        html="<p>Fire safety requirements.</p>",
        keyword_counts={"fire": 5, "safety": 3},
    )
    child_version = CodeEditionProvisionVersion.objects.create(
        provision=child_prov,
        version=0,
        effective_date=date(2024, 1, 1),
        title="Fire Separations",
        html="<p>Fire separation requirements for buildings.</p>",
        keyword_counts={"fire": 4, "separation": 6, "building": 2},
    )

    return {
        "code": code,
        "edition": edition,
        "parent_prov": parent_prov,
        "child_prov": child_prov,
        "parent_version": parent_version,
        "child_version": child_version,
    }


@pytest.mark.django_db
class TestExecuteSearchKeywords:
    def test_keyword_query_returns_matching_provisions(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        assert response["result_count"] > 0
        ids = [r["id"] for r in response["results"]]
        # Both provisions have "fire" in keyword_counts
        assert "3.2" in ids or "3.2.9" in ids

    def test_keyword_query_returns_scored_results(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["separation"],
            "province": "ON",
        })

        assert response["result_count"] >= 1
        # The child provision has "separation" as a keyword
        matching = [r for r in response["results"] if r["id"] == "3.2.9"]
        assert len(matching) == 1
        assert matching[0]["score"] > 0

    def test_no_results_when_keywords_dont_match(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["plumbing"],
            "province": "ON",
        })

        assert response["result_count"] == 0
        assert response["results"] == []

    def test_no_results_when_no_keywords_or_references(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": [],
            "province": "ON",
        })

        assert response["result_count"] == 0
        assert response["results"] == []

    def test_results_include_code_edition_field(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        for result in response["results"]:
            assert result["code_edition"] == "OBC_2024"

    def test_results_include_applicable_codes(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        assert "OBC_2024" in response["applicable_codes"]

    def test_results_include_top_results_metadata(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        assert len(response["top_results_metadata"]) > 0
        meta = response["top_results_metadata"][0]
        assert "code" in meta
        assert "section_id" in meta
        assert "title" in meta


@pytest.mark.django_db
class TestExecuteSearchProvisionReferences:
    def test_provision_reference_matches_by_id(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": [],
            "section_references": ["3.2.9"],
            "province": "ON",
        })

        assert response["result_count"] >= 1
        ids = [r["id"] for r in response["results"]]
        assert "3.2.9" in ids

    def test_provision_reference_partial_match(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": [],
            "section_references": ["3.2"],
            "province": "ON",
        })

        # "3.2" appears in both "3.2" and "3.2.9" provision_ids
        assert response["result_count"] >= 1


@pytest.mark.django_db
class TestExecuteSearchTransitions:
    def test_overlapping_versions_grouped_as_transition(self, db):
        """Two versions of the same provision with overlapping dates get transition_context."""
        code = Code.objects.create(code="BCBC", display_name="BC Building Code")
        ProvinceCode.objects.create(province="BC", code=code)

        edition = CodeEdition.objects.create(
            code=code,
            edition_id="2024",
            year=2024,
            effective_date=date(2024, 1, 1),
        )

        provision = CodeEditionProvision.objects.create(
            edition=edition,
            provision_id="3.2.9",
            level=CodeEditionProvision.Level.SUBSECTION,
            division="B",
            version_count=2,
        )

        # Version 0: old version, in force until mid-2025 (grace period)
        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=0,
            effective_date=date(2024, 1, 1),
            ineffective_date=date(2025, 6, 1),
            title="Fire Separations (old)",
            html="<p>Old fire separation requirements.</p>",
            keyword_counts={"fire": 4, "separation": 5},
        )

        # Version 1: new version, effective from mid-2024 (overlaps with v0)
        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=1,
            effective_date=date(2024, 6, 1),
            ineffective_date=None,
            title="Fire Separations (new)",
            html="<p>New fire separation standards.</p>",
            keyword_counts={"fire": 4, "separation": 5},
        )

        # Search during overlap period
        response = execute_search({
            "date": "2024-09-01",
            "keywords": ["fire"],
            "province": "BC",
        })

        fire_results = [r for r in response["results"] if r["id"] == "3.2.9"]
        assert len(fire_results) == 2

        # Both should have transition_context
        contexts = [r.get("transition_context") for r in fire_results]
        assert all(ctx is not None for ctx in contexts)
        primary_count = sum(1 for ctx in contexts if ctx.get("is_primary"))
        assert primary_count == 1

    def test_no_transition_when_single_version_in_force(self, obc_setup):
        """A single in-force version should not have transition_context."""
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        for result in response["results"]:
            assert result.get("transition_context") is None


@pytest.mark.django_db
class TestExecuteSearchDateFiltering:
    def test_version_not_yet_effective_excluded(self, db):
        """Versions with effective_date after search_date should not appear."""
        code = Code.objects.create(code="NBC", display_name="National Building Code")
        ProvinceCode.objects.create(province="AB", code=code)

        edition = CodeEdition.objects.create(
            code=code,
            edition_id="2025",
            year=2025,
            effective_date=date(2025, 1, 1),
        )

        provision = CodeEditionProvision.objects.create(
            edition=edition,
            provision_id="5.1",
            level=CodeEditionProvision.Level.SECTION,
            division="B",
        )

        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=0,
            effective_date=date(2025, 6, 1),
            title="Future provision",
            keyword_counts={"fire": 3},
        )

        response = execute_search({
            "date": "2025-01-15",
            "keywords": ["fire"],
            "province": "AB",
        })

        assert response["result_count"] == 0

    def test_ineffective_version_excluded(self, db):
        """Versions whose ineffective_date has passed should not appear."""
        code = Code.objects.create(code="NBC", display_name="National Building Code")
        ProvinceCode.objects.create(province="AB", code=code)

        edition = CodeEdition.objects.create(
            code=code,
            edition_id="2020",
            year=2020,
            effective_date=date(2020, 1, 1),
        )

        provision = CodeEditionProvision.objects.create(
            edition=edition,
            provision_id="5.1",
            level=CodeEditionProvision.Level.SECTION,
            division="B",
        )

        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=0,
            effective_date=date(2020, 1, 1),
            ineffective_date=date(2023, 1, 1),
            title="Old provision",
            keyword_counts={"fire": 3},
        )

        response = execute_search({
            "date": "2024-01-01",
            "keywords": ["fire"],
            "province": "AB",
        })

        assert response["result_count"] == 0


@pytest.fixture
def lopsided_editions(db):
    """Two editions in force at once, the locked one dominating the ranking.

    Mirrors the real OBC 2006 -> 2012 overlap at 2014-07-01, where only three
    2006 provisions were still in force against 3,182 in 2012: every top-ranked
    match belongs to the edition a free searcher can't open, and the one they
    can is buried below the display limit.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)

    def _edition(edition_id: str, year: int) -> CodeEdition:
        return CodeEdition.objects.create(
            code=code, edition_id=edition_id, year=year,
            effective_date=date(year, 1, 1),
        )

    free_edition = _edition("2006", 2006)
    locked_edition = _edition("2012", 2012)

    def _provision(edition: CodeEdition, pid: str, counts: dict[str, int]) -> None:
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id=pid,
            level=CodeEditionProvision.Level.ARTICLE, division="C",
        )
        CodeEditionProvisionVersion.objects.create(
            provision=provision, version=0, effective_date=date(2014, 1, 1),
            title=f"Inspection {pid}", keyword_counts=counts,
        )

    # 15 strong matches in the locked edition...
    for i in range(15):
        _provision(locked_edition, f"1.10.{i}.", {"inspection": 9})
    # ...and one weak match in the free edition: same term, but diluted by a
    # long document, so it scores below every locked row.
    _provision(free_edition, "1.10.99.", {"inspection": 1, "filler": 400})

    return {"free": free_edition, "locked": locked_edition}


@pytest.mark.django_db
class TestExecuteSearchTierScope:
    """The tier split runs before the display limit, not after it."""

    QUERY = {"date": "2014-07-01", "keywords": ["inspection"], "province": "ON"}

    def test_accessible_result_ranked_below_the_limit_still_shows(
        self, lopsided_editions
    ):
        # The regression this guards: trimming to 10 cards first handed the
        # gate an all-locked list, and the UI then told the user that nothing
        # in their plan matched — about a corpus where something had.
        response = execute_search(
            self.QUERY,
            allowed_editions=frozenset({"OBC_2006"}),
            result_cap=10,
        )

        assert [r["id"] for r in response["results"]] == ["1.10.99."]
        assert response["applicable_codes"] == ["OBC_2006"]

    def test_locked_count_is_the_true_total_not_the_pool_size(
        self, lopsided_editions
    ):
        # 15 locked matches exist; a pool- or display-bounded count would say
        # 10 and understate what a subscription actually unlocks.
        response = execute_search(
            self.QUERY,
            allowed_editions=frozenset({"OBC_2006"}),
            result_cap=10,
        )

        assert response["locked_editions"] == {"OBC_2012": 15}
        assert len(response["locked_preview"]) == 15
        assert all(row["title"] for row in response["locked_preview"])
        # Identity only — the preview must not carry provision text.
        assert set(response["locked_preview"][0]) == {
            "id", "division", "title", "code_edition",
        }

    def test_unrestricted_searcher_sees_the_locked_edition(self, lopsided_editions):
        response = execute_search(
            self.QUERY, allowed_editions=None, result_cap=10
        )

        assert response["result_count"] == 10
        assert response["locked_editions"] == {}
        assert response["locked_preview"] == []
        assert {r["code_edition"] for r in response["results"]} == {"OBC_2012"}

    # These are about the render cap, so they pin the relevance floor to 0 —
    # otherwise the default floor removes the deliberately-weak row and the
    # numbers under test move for an unrelated reason.
    def test_cap_above_the_match_count_shows_everything(self, lopsided_editions):
        response = execute_search(
            self.QUERY, allowed_editions=None, result_cap=25,
            match_threshold=0.0,
        )

        assert response["result_count"] == 16
        assert response["accessible_match_count"] == 16
        assert response["cap_binds"] is False

    def test_cap_binds_only_when_it_actually_trims(self, lopsided_editions):
        response = execute_search(
            self.QUERY, allowed_editions=None, result_cap=10,
            match_threshold=0.0,
        )

        # 16 matched, 10 rendered — this is the one case where the header may
        # say "N OF M" and owe the reader an explanation.
        assert response["accessible_match_count"] == 16
        assert response["result_count"] == 10
        assert response["cap_binds"] is True

    def test_cap_does_not_bind_when_grouping_alone_shortens_the_list(
        self, lopsided_editions
    ):
        # The regression: `cap_binds` was derived by comparing rendered rows to
        # the match count, so a transition group dropping a third in-force
        # version read as truncation and the header claimed a result was held
        # back that nothing had withheld.
        response = execute_search(
            self.QUERY, allowed_editions=None, result_cap=1000,
            match_threshold=0.0,
        )

        assert response["cap_binds"] is False


@pytest.mark.django_db
class TestMatchThreshold:
    """The relevance floor is applied to everything the search reports."""

    QUERY = {"date": "2014-07-01", "keywords": ["inspection"], "province": "ON"}

    def _scores(self, **kwargs) -> list[float]:
        response = execute_search(self.QUERY, **kwargs)
        return [r["score"] for r in response["results"]]

    def test_floor_excludes_weak_matches(self, lopsided_editions):
        strong = self._scores(
            allowed_editions=None, result_cap=50, match_threshold=0.8
        )
        everything = self._scores(
            allowed_editions=None, result_cap=50, match_threshold=0.0
        )

        assert min(strong) >= 0.8
        # The weak free-edition row (diluted by a long document) is the one
        # the floor removes.
        assert len(everything) > len(strong)
        assert min(everything) < 0.8

    def test_locked_count_uses_the_same_floor_as_the_shown_results(
        self, lopsided_editions
    ):
        # Two counts of one corpus on one screen must be measured the same
        # way, or the teaser and the header disagree in public.
        floored = execute_search(
            self.QUERY,
            allowed_editions=frozenset({"OBC_2006"}),
            result_cap=10,
            match_threshold=0.8,
        )
        unfloored = execute_search(
            self.QUERY,
            allowed_editions=frozenset({"OBC_2006"}),
            result_cap=10,
            match_threshold=0.0,
        )

        assert floored["locked_editions"] == {"OBC_2012": 15}
        assert floored["accessible_match_count"] == 0 or floored["weak_matches_only"]
        # Dropping the floor can only ever add, never remove.
        assert unfloored["locked_editions"]["OBC_2012"] >= 15

    def test_weak_matches_shown_rather_than_an_empty_page(self, lopsided_editions):
        # The guard on the floor: emptying an accessible list would recreate
        # the failure the access split was introduced to fix.
        response = execute_search(
            self.QUERY,
            allowed_editions=frozenset({"OBC_2006"}),
            result_cap=10,
            match_threshold=1.2,
        )

        assert response["weak_matches_only"] is True
        assert [r["id"] for r in response["results"]] == ["1.10.99."]

    def test_no_fallback_flag_when_the_floor_leaves_something(
        self, lopsided_editions
    ):
        response = execute_search(
            self.QUERY, allowed_editions=None, result_cap=10,
            match_threshold=0.8,
        )

        assert response["weak_matches_only"] is False
        assert response["result_count"] == 10

    def test_buckets_partition_the_accessible_matches(self, lopsided_editions):
        # The control draws these; if they didn't sum to the accessible total
        # its "kept + dropped" readout would not add up to the search.
        response = execute_search(
            self.QUERY, allowed_editions=None, match_threshold=0.8
        )

        everything = execute_search(
            self.QUERY, allowed_editions=None, match_threshold=0.0
        )
        assert sum(response["score_buckets"]) == everything["accessible_match_count"]
        # Buckets ignore the floor — the reader has to see what's below the
        # line to decide whether the line is in the right place.
        assert sum(response["score_buckets"]) > response["accessible_match_count"]

    def test_close_count_reports_the_line_not_the_fallback(self, lopsided_editions):
        # Under the fallback the shown list is every weak match, but nothing
        # cleared the line.  The control must say 0, or it claims a full list
        # was kept while drawing every bar below the line as dropped.
        response = execute_search(
            self.QUERY,
            allowed_editions=frozenset({"OBC_2006"}),
            match_threshold=1.2,
        )

        assert response["weak_matches_only"] is True
        assert response["close_match_count"] == 0
        assert response["accessible_match_count"] == 1

    def test_threshold_is_echoed_back(self, lopsided_editions):
        response = execute_search(
            self.QUERY, allowed_editions=None, match_threshold=0.4
        )

        assert response["match_threshold"] == 0.4


def _row(rid: str, pair_key: str | None = None, is_primary: bool = True) -> dict:
    """A minimal scored-result row for the pair-aware limiter."""
    row: dict = {"id": rid}
    if pair_key:
        row["transition_context"] = {"pair_key": pair_key, "is_primary": is_primary}
    return row


class TestLimitWithPairs:
    """``_limit_with_pairs`` trims to N *cards*, not N rows."""

    def test_plain_results_trim_to_the_limit(self):
        rows = [_row(str(i)) for i in range(20)]

        kept = _limit_with_pairs(rows, 10)

        assert [r["id"] for r in kept] == [str(i) for i in range(10)]

    def test_a_pair_costs_one_card_not_two(self):
        # 9 singles + a pair == 10 cards, so 11 rows survive.
        rows = [_row(str(i)) for i in range(9)]
        rows += [_row("old", "map:1", False), _row("new", "map:1", True)]
        rows += [_row("filler")]

        kept = _limit_with_pairs(rows, 10)

        assert len(kept) == 11
        assert {r["id"] for r in kept} >= {"old", "new"}
        assert "filler" not in {r["id"] for r in kept}

    def test_partner_below_the_cutoff_is_still_admitted(self):
        # The regression this guards: the pair's high-scoring member ranks 10th
        # and its partner 12th.  Trimming before grouping dropped the partner
        # and the transition rendered as a lone version.
        rows = [_row(str(i)) for i in range(9)]
        rows += [_row("new", "map:1", True)]
        rows += [_row("noise")]
        rows += [_row("old", "map:1", False)]

        kept = _limit_with_pairs(rows, 10)

        ids = [r["id"] for r in kept]
        assert "new" in ids and "old" in ids
        assert "noise" not in ids

    def test_pair_entirely_below_the_cutoff_is_excluded(self):
        rows = [_row(str(i)) for i in range(10)]
        rows += [_row("old", "map:1", False), _row("new", "map:1", True)]

        kept = _limit_with_pairs(rows, 10)

        assert len(kept) == 10
        assert "old" not in {r["id"] for r in kept}
        assert "new" not in {r["id"] for r in kept}

    def test_independent_pairs_each_cost_one_card(self):
        rows = [
            _row("a-old", "map:1", False), _row("a-new", "map:1", True),
            _row("b-old", "map:2", False), _row("b-new", "map:2", True),
        ]

        kept = _limit_with_pairs(rows, 2)

        assert len(kept) == 4
        assert {r["id"] for r in kept} == {"a-old", "a-new", "b-old", "b-new"}
