"""Tests for what an exhibit repeats.

CCM ships a scanned provision's tables twice: inside the page image, and again
as table rows. On the reading page the second copy sits behind a disclosure,
so nobody meets both at once. On paper both print, and an exhibit showing the
same table twice invites the question of which copy is the evidence.

The property under test is that the default is decided by *how the version
renders*, not by a page-wide switch — and that the switch still exists.
"""

from types import SimpleNamespace

from django.http import QueryDict

from corpus.printing.print_options import (
    apply_tables_mode,
    resolve_tables_mode,
    show_tables_for,
    toggle_query,
)


def _scanned():
    return SimpleNamespace(page_images=[{"image": "p.webp", "bboxes": []}])


def _html():
    return SimpleNamespace(page_images=[])


class TestTheDefaultFollowsHowTheVersionRenders:
    def test_a_scanned_version_does_not_repeat_its_tables(self):
        # The scan already shows them.
        assert show_tables_for(_scanned(), None) is False

    def test_an_html_version_keeps_its_tables(self):
        # ``version.html`` carries the text; the tables hang off the version
        # separately, so suppressing them would drop content that appears
        # nowhere else in the exhibit.
        assert show_tables_for(_html(), None) is True


class TestTheReaderCanOverrideEitherWay:
    def test_on_repeats_them_even_for_a_scan(self):
        assert show_tables_for(_scanned(), "on") is True

    def test_off_drops_them_even_from_html(self):
        assert show_tables_for(_html(), "off") is False

    def test_an_unknown_value_falls_back_to_the_default(self):
        # A hand-edited URL must not silently mean "off".
        assert resolve_tables_mode("maybe") is None
        assert resolve_tables_mode(None) is None
        assert resolve_tables_mode("on") == "on"
        assert resolve_tables_mode("off") == "off"


class TestApplyingTheModeToAPage:
    def test_it_stamps_each_version_and_reports_the_page_state(self):
        scanned, html = _scanned(), _html()
        separate = apply_tables_mode([scanned, html], None)
        assert scanned.show_tables is False
        assert html.show_tables is True
        # Mixed reads as "not shown": something was suppressed, and that is
        # the honest label for the control.
        assert separate is False

    def test_all_html_reads_as_shown(self):
        assert apply_tables_mode([_html(), _html()], None) is True

    def test_forcing_on_reports_shown(self):
        assert apply_tables_mode([_scanned(), _html()], "on") is True


class TestTheToggleKeepsTheRestOfTheQuery:
    def test_it_flips_the_value_and_preserves_the_other_parameters(self):
        params = QueryDict("a=OBC_1997/3.1.4.6./v0&b=OBC_2006/B/3.1.4.6./v0")
        query = toggle_query(params, separate=False)
        # A link that dropped the two references would turn "show the tables"
        # into "which comparison?".
        assert "a=OBC_1997" in query
        assert "b=OBC_2006" in query
        assert "tables=on" in query

    def test_it_flips_back(self):
        assert "tables=off" in toggle_query(QueryDict(""), separate=True)
