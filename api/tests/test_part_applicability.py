"""Tests for the part-applicability table.

The property that matters is that the table answers what the *code* answers,
including where that contradicts the obvious word.  A four-storey townhouse is
a house and is not a Part 9 building, and a design that cannot say so is the
design this table replaced.

No database and no Django: ``config`` is plain data.
"""

from dataclasses import replace
from datetime import date

import pytest

from config.part_applicability import (
    OCCUPANCIES,
    RULES,
    Verdict,
    coerce_building,
    part_of,
    rule_for,
    size_relevance_intervals,
    size_thresholds,
    verdict_for,
)

# Every loaded edition puts Part 9 and Part 3 where these say.
OBC_2012 = {"edition_id": "2012", "division": "B"}
OBC_2006 = {"edition_id": "2006", "division": "B"}
OBC_1997 = {"edition_id": "1997", "division": ""}

GUARDS_PART_9 = "9.8.8.1."
GUARDS_PART_3 = "3.4.6.5."


def ask(edition: dict, provision_id: str, **building) -> Verdict:
    """``verdict_for`` with the search-side arguments defaulted to unknown."""
    return verdict_for(
        edition_id=edition["edition_id"],
        division=edition["division"],
        provision_id=provision_id,
        occupancy=building.get("occupancy"),
        storeys=building.get("storeys"),
        area_m2=building.get("area_m2"),
        on_date=building.get("on_date", date(2015, 6, 1)),
    )


class TestTheSizeTest:
    def test_a_small_house_is_a_part_9_building(self):
        small = {"occupancy": "residential", "storeys": 2, "area_m2": 140}
        assert ask(OBC_2012, GUARDS_PART_9, **small) is Verdict.APPLIES
        assert ask(OBC_2012, GUARDS_PART_3, **small) is Verdict.EXCLUDED

    def test_a_four_storey_house_is_not_a_part_9_building(self):
        """The case a guessed storey count gets wrong.

        The reader says "townhouse", the model would say two storeys, and the
        boost would push Part 9 at somebody Part 9 does not govern.  1.1.2.4.
        joins its three conditions with "and", so four storeys decides it
        whatever the area.
        """
        tall = {"occupancy": "residential", "storeys": 4, "area_m2": 140}
        assert ask(OBC_2012, GUARDS_PART_9, **tall) is Verdict.EXCLUDED
        assert ask(OBC_2012, GUARDS_PART_3, **tall) is Verdict.APPLIES

    def test_storeys_alone_can_decide_when_it_breaches(self):
        """No area given, and none needed: over three storeys is already out."""
        assert ask(
            OBC_2012, GUARDS_PART_9, occupancy="residential", storeys=4
        ) is Verdict.EXCLUDED

    def test_area_alone_can_decide_when_it_breaches(self):
        assert ask(
            OBC_2012, GUARDS_PART_9, occupancy="residential", area_m2=900
        ) is Verdict.EXCLUDED

    def test_under_one_threshold_with_the_other_unstated_decides_nothing(self):
        """Two storeys is not enough to say Part 9 applies — the unstated area
        may be the measurement that breaches.  Undecided must never boost."""
        assert ask(
            OBC_2012, GUARDS_PART_9, occupancy="residential", storeys=2
        ) is Verdict.UNKNOWN
        assert ask(
            OBC_2012, GUARDS_PART_9, occupancy="residential", area_m2=140
        ) is Verdict.UNKNOWN

    def test_a_threshold_is_inclusive_on_the_small_side(self):
        """"three or fewer storeys" and "not exceeding 600 m²"."""
        edge = {"occupancy": "residential", "storeys": 3, "area_m2": 600}
        assert ask(OBC_2012, GUARDS_PART_9, **edge) is Verdict.APPLIES


class TestOccupancyAlone:
    @pytest.mark.parametrize(
        "occupancy", ["assembly", "care-or-detention", "high-hazard-industrial"]
    )
    def test_some_occupancies_decide_with_no_measurement(self, occupancy):
        """1.1.2.2.(1)(a) states no size test for Groups A, B and F1, so a
        school or a hospital is settled by the word alone."""
        assert ask(OBC_2012, GUARDS_PART_3, occupancy=occupancy) is Verdict.APPLIES
        assert ask(OBC_2012, GUARDS_PART_9, occupancy=occupancy) is Verdict.EXCLUDED

    def test_no_occupancy_decides_nothing(self):
        assert ask(OBC_2012, GUARDS_PART_9, storeys=2, area_m2=140) is Verdict.UNKNOWN

    def test_an_unknown_occupancy_decides_nothing(self):
        assert ask(OBC_2012, GUARDS_PART_9, occupancy="spaceport") is Verdict.UNKNOWN


class TestWhatTheArticlesDoNotGate:
    @pytest.mark.parametrize("provision_id", ["1.1.1.1.", "7.2.1.1.", "12.1.1.1."])
    def test_an_ungated_part_is_never_boosted(self, provision_id):
        """Parts 1, 7 and 12 apply to all buildings, so nothing distinguishes
        them.  Parts 8, 10 and 11 gate on a system or an activity, not a
        building."""
        assert ask(
            OBC_2012, provision_id, occupancy="residential", storeys=2, area_m2=140
        ) is Verdict.UNKNOWN

    def test_division_a_is_never_boosted(self):
        """A reader asking what a word means needs Division A 1.4.1.2.,
        whatever they are building."""
        assert verdict_for(
            edition_id="2012",
            division="A",
            provision_id="1.4.1.2.",
            occupancy="residential",
            storeys=2,
            area_m2=140,
            on_date=date(2015, 6, 1),
        ) is Verdict.UNKNOWN

    def test_division_c_is_never_boosted(self):
        assert verdict_for(
            edition_id="2012",
            division="C",
            provision_id="3.1.1.1.",
            occupancy="residential",
            storeys=2,
            area_m2=140,
            on_date=date(2015, 6, 1),
        ) is Verdict.UNKNOWN

    def test_an_edition_with_no_rule_is_never_boosted(self):
        assert verdict_for(
            edition_id="2024",
            division="B",
            provision_id=GUARDS_PART_9,
            occupancy="residential",
            storeys=2,
            area_m2=140,
            on_date=date(2025, 6, 1),
        ) is Verdict.UNKNOWN


class TestTheRuleMovesWithTheDate:
    """1.1.2.4. v1 removed retirement homes from Part 9 on 1 July 2017, and
    1.1.2.2. v2 added them to Parts 3, 5 and 6 on the same day."""

    def test_a_retirement_home_is_a_part_9_building_before_the_change(self):
        before = {
            "occupancy": "retirement-home",
            "storeys": 2,
            "area_m2": 400,
            "on_date": date(2016, 6, 1),
        }
        assert ask(OBC_2012, GUARDS_PART_9, **before) is Verdict.APPLIES
        assert ask(OBC_2012, GUARDS_PART_3, **before) is Verdict.EXCLUDED

    def test_a_retirement_home_is_a_part_3_building_after_the_change(self):
        after = {
            "occupancy": "retirement-home",
            "storeys": 2,
            "area_m2": 400,
            "on_date": date(2018, 6, 1),
        }
        assert ask(OBC_2012, GUARDS_PART_9, **after) is Verdict.EXCLUDED
        assert ask(OBC_2012, GUARDS_PART_3, **after) is Verdict.APPLIES

    def test_the_window_is_half_open_on_the_day_itself(self):
        """Every other window in this product is half-open, and the change
        takes effect on 1 July 2017, not the day after."""
        on_the_day = {
            "occupancy": "retirement-home",
            "storeys": 2,
            "area_m2": 400,
            "on_date": date(2017, 7, 1),
        }
        assert ask(OBC_2012, GUARDS_PART_9, **on_the_day) is Verdict.EXCLUDED


class TestEveryEditionIsCovered:
    def test_the_1997_body_carries_no_division(self):
        small = {"occupancy": "residential", "storeys": 2, "area_m2": 140}
        assert ask(OBC_1997, GUARDS_PART_9, **small) is Verdict.APPLIES
        assert ask(OBC_1997, GUARDS_PART_3, **small) is Verdict.EXCLUDED

    def test_2006_gates_division_b(self):
        small = {"occupancy": "residential", "storeys": 2, "area_m2": 140}
        assert ask(OBC_2006, GUARDS_PART_9, **small) is Verdict.APPLIES

    def test_every_rule_cites_the_article_it_reads(self):
        for rule in RULES:
            assert rule.source_small
            assert rule.source_large

    def test_every_occupancy_is_placed_by_every_rule(self):
        """A word in the control that no rule classifies would be offered to
        the reader and then ignored."""
        for rule in RULES:
            placed = rule.sized_occupancies | rule.unsized_occupancies
            assert placed == set(OCCUPANCIES), rule


class TestRuleLookup:
    def test_a_date_of_none_takes_the_earliest_rule(self):
        rule = rule_for("2012", None)
        assert rule is not None
        assert rule.ineffective == date(2017, 7, 1)

    def test_an_unknown_edition_has_no_rule(self):
        assert rule_for("2024", date(2025, 1, 1)) is None


class TestCoerceBuilding:
    """Everything here arrives from a form post or a hand-editable address."""

    def test_it_keeps_what_it_can_use(self):
        assert coerce_building("residential", "4", "140.5") == {
            "occupancy": "residential",
            "storeys": 4,
            "area": 140.5,
            "area_unit": "m2",
            "area_m2": 140.5,
        }

    def test_square_feet_are_converted_and_the_readers_figure_kept(self):
        """The trap this selector exists for: a small house is about 1,500
        ft², which is 139 m².  Typed into a metric box it describes a building
        two and a half times over the Part 9 limit, and the page just
        re-ranks — nothing tells the reader why."""
        building = coerce_building("residential", "1", "1500", "sqft")

        assert building["area"] == 1500.0
        assert building["area_unit"] == "sqft"
        assert building["area_m2"] == 139.35

    def test_the_converted_value_is_what_the_rule_reads(self):
        small = coerce_building("residential", "1", "1500", "sqft")
        assert verdict_for(
            edition_id="2012", division="B", provision_id=GUARDS_PART_9,
            occupancy=small["occupancy"],
            storeys=small["storeys"],
            area_m2=small["area_m2"],
            on_date=date(2015, 6, 1),
        ) is Verdict.APPLIES

    def test_an_unknown_unit_falls_back_to_metres(self):
        """A hand-edited address.  Metres is the code's own unit, so falling
        back to it never silently converts a figure by an unknown factor."""
        assert coerce_building(None, None, "500", "cubits")["area_unit"] == "m2"

    def test_a_bound_is_applied_to_the_converted_value(self):
        """The limit is on the real area, so it cannot be evaded by choosing
        the unit that makes the number look smaller."""
        assert "area_m2" not in coerce_building(None, None, "1e12", "sqft")

    def test_an_unusable_value_becomes_an_absent_key(self):
        """Not a default.  A default here would be a guess about somebody's
        building, which is the thing this whole design avoids."""
        assert coerce_building("spaceport", "many", "big") == {}

    def test_a_blank_control_clears_the_building(self):
        assert coerce_building("", "", "") == {}

    def test_none_is_accepted_from_a_parse_that_said_nothing(self):
        assert coerce_building(None, None, None) == {}

    @pytest.mark.parametrize("storeys", [0, -3, 10_000])
    def test_an_impossible_storey_count_is_dropped(self, storeys):
        assert "storeys" not in coerce_building(None, storeys, None)

    @pytest.mark.parametrize("area", [0, -10, 10_000_000])
    def test_an_impossible_area_is_dropped(self, area):
        assert "area_m2" not in coerce_building(None, None, area)

    def test_nan_is_dropped(self):
        assert "area_m2" not in coerce_building(None, None, float("nan"))

    def test_a_parsed_building_survives_a_round_trip(self):
        """The view re-reads the building out of ``parsed_params`` to write the
        address, so the values it wrote must come back unchanged."""
        first = coerce_building("residential", "4", "140")
        assert coerce_building(*(first.get(k) for k in ("occupancy", "storeys", "area_m2"))) == first


class TestPartOf:
    @pytest.mark.parametrize(
        ("provision_id", "expected"),
        [
            ("9.8.8.3.", 9),
            ("3.4.6.5.", 3),
            ("12.1.1.1.", 12),
            ("Part 9", 9),
            ("Part 11", 11),
            ("", None),
            ("A-9.8.8.3.", None),
        ],
    )
    def test_the_part_is_the_first_dotted_segment(self, provision_id, expected):
        assert part_of(provision_id) == expected

    def test_a_two_digit_part_is_not_confused_with_a_one_digit_part(self):
        assert part_of("11.2.1.1.") == 11
        assert part_of("1.2.1.1.") == 1


class TestPartOfReadsBothVocabularies:
    """``core.views.regulation`` groups on this too, and passes other ids.

    A provision's own id names its level (``Part 9``); a clause's
    ``target_id`` does not, because ``target_level`` sits beside it.  One
    parser has to read both, or the two disagree in a way nothing tests.
    """

    def test_an_undotted_subsection_target_keeps_its_part(self):
        """``2(2)`` is a clause target: a subsection with a sentence, no dot."""
        assert part_of("2(2)") == 2
        assert part_of("3(20)") == 3

    def test_a_regulation_citation_has_no_part(self):
        """``target_level="regulation"`` carries ids like ``350/06``.

        Reading the leading digits put those under a "Part 350" heading on the
        regulation page — a Part that does not exist in any edition.
        """
        assert part_of("350/06") is None
        assert part_of("332/12") is None

    def test_a_slash_deeper_in_the_id_is_not_a_citation(self):
        """``11.5.1.1.D/E.`` is a real Part 11 table.

        The citation test is on the first segment alone.  Applied to the whole
        id it took the part away from every row of that table.
        """
        assert part_of("11.5.1.1.D/E.") == 11
        assert part_of("11.5.1.1.D/E.(Item 51)") == 11


class TestWhenTheControlMayAskForASize:
    """The control asks for a measurement only where one can decide, on the
    date the reader is searching.

    Division A 1.1.2.2.(1)(a) states no size test for Groups A, B and F1, so
    asking a reader with a school how many storeys it has invites an answer
    that changes nothing. And a retirement home moves between the two sides on
    1 July 2017, so the answer depends on the AS-OF date and not only on the
    word.
    """

    #: The three loaded editions, as the corpus dates them.
    WINDOWS = {
        "1997": (date(1998, 4, 6), date(2006, 12, 31)),
        "2006": (date(2006, 12, 31), date(2014, 1, 1)),
        "2012": (date(2014, 1, 1), date(2025, 1, 1)),
    }

    def sized_on(self, day: date) -> set[str]:
        """What the control would offer a size for, on ``day``."""
        out: set[str] = set()
        for window in size_relevance_intervals(self.WINDOWS):
            if (window.start is None or day >= window.start) and (
                window.end is None or day < window.end
            ):
                out |= window.sized
        return out

    @pytest.mark.parametrize(
        "occupancy", ["assembly", "care-or-detention", "high-hazard-industrial"]
    )
    def test_an_unsized_occupancy_is_never_asked(self, occupancy):
        assert occupancy not in self.sized_on(date(2015, 6, 1))

    @pytest.mark.parametrize("occupancy", ["residential", "business", "mercantile"])
    def test_a_sized_occupancy_is_asked(self, occupancy):
        assert occupancy in self.sized_on(date(2015, 6, 1))

    def test_a_retirement_home_is_asked_before_the_2017_change(self):
        assert "retirement-home" in self.sized_on(date(2016, 6, 1))

    def test_a_retirement_home_is_not_asked_after_it(self):
        """The answer changed, so the control changes with it — the reader
        sees the field go when they move the date past 1 July 2017."""
        assert "retirement-home" not in self.sized_on(date(2018, 6, 1))

    def test_an_edition_that_is_not_loaded_contributes_nothing(self):
        """The control describes the corpus, not the table. A rule for an
        edition nobody can search must not put a field on the screen."""
        only_1997 = size_relevance_intervals({"1997": self.WINDOWS["1997"]})
        assert len(only_1997) == 1
        assert only_1997[0].start == date(1998, 4, 6)

    def test_each_interval_is_clipped_to_its_edition(self):
        """A rule carries only the window of its own split; the edition's
        dates are what bound it. Unclipped, OBC 1997's rule would still be
        offering fields in 2020."""
        for window in size_relevance_intervals(self.WINDOWS):
            assert window.start is not None
            assert window.end is not None

    def test_the_2012_split_lands_on_the_day_itself(self):
        boundaries = {w.end for w in size_relevance_intervals(self.WINDOWS)}
        assert date(2017, 7, 1) in boundaries

    def test_a_rule_whose_window_misses_its_edition_is_dropped(self):
        """An overlap of zero length is not an interval, and emitting one
        would draw a field for a day that does not exist."""
        assert size_relevance_intervals(
            {"2012": (date(2014, 1, 1), date(2014, 1, 1))}
        ) == []


class TestTheStatedThresholds:
    def test_it_reports_the_pair_every_rule_agrees_on(self):
        """The copy prints these numbers, so they must come from the table
        rather than from somebody's memory of the code."""
        assert size_thresholds() == (3, 600)

    def test_it_reports_nothing_when_the_rules_disagree(self, monkeypatch):
        """A future edition with different limits must silence the sentence,
        not make it lie about the corpus as a whole."""
        import config.part_applicability as pa

        divergent = pa.RULES + (
            replace(pa.RULES[-1], edition_id="2099", max_storeys=6, max_area_m2=900),
        )
        monkeypatch.setattr(pa, "RULES", divergent)
        assert pa.size_thresholds() is None
