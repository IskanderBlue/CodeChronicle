"""Tests for IN FORCE band rail geometry."""

from datetime import date

from api.band import compute_band_geometry, parse_iso_date

FROM = date(1992, 12, 1)
UNTIL = date(1997, 4, 6)


def test_parse_iso_date_accepts_strings_dates_and_junk():
    assert parse_iso_date("1993-05-12") == date(1993, 5, 12)
    assert parse_iso_date(date(1993, 5, 12)) == date(1993, 5, 12)
    assert parse_iso_date("1993-05-12T00:00:00") == date(1993, 5, 12)
    assert parse_iso_date(None) is None
    assert parse_iso_date("") is None
    assert parse_iso_date("not-a-date") is None


def test_no_from_date_is_unanchored():
    assert compute_band_geometry(None, UNTIL, date(1993, 5, 12)) is None


def test_query_inside_window_is_covered_and_tick_within_span():
    g = compute_band_geometry(FROM, UNTIL, date(1993, 5, 12))
    assert g is not None
    assert g["covered"] is True
    # tick sits between the span's left edge and its right edge
    assert g["span_left_pct"] < g["tick_pct"] < g["span_left_pct"] + g["span_width_pct"]


def test_query_before_from_is_not_covered_and_tick_left_of_span():
    g = compute_band_geometry(FROM, UNTIL, date(1990, 1, 1))
    assert g is not None
    assert g["covered"] is False
    assert g["tick_pct"] < g["span_left_pct"]


def test_query_after_until_is_not_covered_and_tick_right_of_span():
    g = compute_band_geometry(FROM, UNTIL, date(2000, 1, 1))
    assert g is not None
    assert g["covered"] is False
    assert g["tick_pct"] > g["span_left_pct"] + g["span_width_pct"]


def test_until_boundary_is_exclusive():
    # The day the version ceased to be in force is NOT covered.
    g = compute_band_geometry(FROM, UNTIL, UNTIL)
    assert g is not None
    assert g["covered"] is False


def test_from_boundary_is_inclusive():
    g = compute_band_geometry(FROM, UNTIL, FROM)
    assert g is not None
    assert g["covered"] is True


def test_open_ended_covers_any_date_after_from():
    g = compute_band_geometry(FROM, None, date(2030, 1, 1), today=date(2026, 5, 30))
    assert g is not None
    assert g["open_ended"] is True
    assert g["covered"] is True


def test_no_query_date_hides_tick_and_coverage():
    g = compute_band_geometry(FROM, UNTIL, None)
    assert g is not None
    assert g["tick_pct"] is None
    assert g["covered"] is None
    # span still positioned
    assert g["span_width_pct"] > 0


def test_span_stays_within_bounds():
    g = compute_band_geometry(FROM, UNTIL, date(1993, 5, 12))
    assert g is not None
    assert 0 <= g["span_left_pct"] <= 100
    assert 0 <= g["span_left_pct"] + g["span_width_pct"] <= 100
    assert 0 <= g["tick_pct"] <= 100


def test_inverted_range_does_not_crash():
    # Bad data: until before from — span clamps to zero width, no exception.
    g = compute_band_geometry(UNTIL, FROM, date(1995, 1, 1))
    assert g is not None
    assert g["span_width_pct"] >= 0
