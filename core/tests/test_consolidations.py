"""Tests for the e-Laws consolidation map: the as-of resolver and its loader."""

import json
from datetime import date

import pytest
from django.core.management import call_command

from core.models import Code, CodeEdition, ElawsConsolidation


@pytest.fixture
def edition(db) -> CodeEdition:
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    return CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012, effective_date=date(2014, 1, 1)
    )


def _make(edition: CodeEdition, version: int, frm: date, to: date | None) -> None:
    ElawsConsolidation.objects.create(
        edition=edition,
        version=version,
        url=f"https://www.ontario.ca/laws/regulation/120332/v{version}",
        effective_from=frm,
        effective_to=to,
    )


class TestResolve:
    def test_picks_the_period_covering_the_date(self, edition: CodeEdition) -> None:
        _make(edition, 5, date(2014, 1, 1), date(2014, 12, 31))
        _make(edition, 7, date(2015, 1, 1), date(2015, 12, 31))
        got = ElawsConsolidation.objects.resolve(edition.pk, date(2015, 6, 1))
        assert got is not None and got.version == 7

    def test_inclusive_end_day(self, edition: CodeEdition) -> None:
        _make(edition, 5, date(2014, 1, 1), date(2014, 12, 31))
        got = ElawsConsolidation.objects.resolve(edition.pk, date(2014, 12, 31))
        assert got is not None and got.version == 5

    def test_open_ended_current_period(self, edition: CodeEdition) -> None:
        _make(edition, 38, date(2024, 4, 10), None)
        got = ElawsConsolidation.objects.resolve(edition.pk, date(2099, 1, 1))
        assert got is not None and got.version == 38

    def test_uncovered_date_returns_none(self, edition: CodeEdition) -> None:
        _make(edition, 5, date(2014, 1, 1), date(2014, 12, 31))
        assert ElawsConsolidation.objects.resolve(edition.pk, date(2013, 1, 1)) is None

    def test_none_date_returns_none(self, edition: CodeEdition) -> None:
        _make(edition, 5, date(2014, 1, 1), date(2014, 12, 31))
        assert ElawsConsolidation.objects.resolve(edition.pk, None) is None


class TestLoader:
    def test_loads_and_skips_unknown_editions(
        self, edition: CodeEdition, tmp_path
    ) -> None:
        rows = [
            {
                "code": "OBC", "edition": "2012", "version": 5,
                "url": "https://www.ontario.ca/laws/regulation/120332/v5",
                "effective_from": "2014-01-01", "effective_to": "2014-12-31",
            },
            {
                "code": "OBC", "edition": "2012", "version": 38,
                "url": "https://www.ontario.ca/laws/regulation/120332/v38",
                "effective_from": "2024-04-10", "effective_to": None,
            },
            # Edition not in the DB — must be skipped, not error.
            {
                "code": "OBC", "edition": "2099", "version": 1,
                "url": "https://www.ontario.ca/laws/regulation/990001/v1",
                "effective_from": "2099-01-01", "effective_to": None,
            },
        ]
        src = tmp_path / "elaws_consolidations.json"
        src.write_text(json.dumps(rows), encoding="utf-8")

        call_command("load_consolidations", source=str(src))

        loaded = ElawsConsolidation.objects.filter(edition=edition)
        assert loaded.count() == 2
        assert loaded.get(version=38).effective_to is None

    def test_reload_replaces_rows(self, edition: CodeEdition, tmp_path) -> None:
        _make(edition, 99, date(2000, 1, 1), None)  # stale row from a prior run
        rows = [{
            "code": "OBC", "edition": "2012", "version": 5,
            "url": "https://www.ontario.ca/laws/regulation/120332/v5",
            "effective_from": "2014-01-01", "effective_to": "2014-12-31",
        }]
        src = tmp_path / "c.json"
        src.write_text(json.dumps(rows), encoding="utf-8")

        call_command("load_consolidations", source=str(src))

        versions = set(ElawsConsolidation.objects.values_list("version", flat=True))
        assert versions == {5}  # stale v99 wiped
