"""Tests for api.band date coercion."""

from datetime import date

from api.band import parse_iso_date


def test_parse_iso_date_accepts_strings_dates_and_junk():
    assert parse_iso_date("1993-05-12") == date(1993, 5, 12)
    assert parse_iso_date(date(1993, 5, 12)) == date(1993, 5, 12)
    assert parse_iso_date("1993-05-12T00:00:00") == date(1993, 5, 12)
    assert parse_iso_date(None) is None
    assert parse_iso_date("") is None
    assert parse_iso_date("not-a-date") is None
