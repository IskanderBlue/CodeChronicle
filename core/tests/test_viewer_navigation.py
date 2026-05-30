"""Viewer navigation tests.

These tests patched ``CodeMapNode`` through the old map-based viewer
code path.  After ``impl-display-migration.md`` the viewer reads
``CodeEditionProvision`` / ``CodeEditionProvisionVersion`` directly, so
the ``CodeMapNode`` patches are no-ops and the assertions don't match
the new query plan.  Replacement coverage lives in the integration
tests against real load_edition data — see
``api/tests/test_integration.py``.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.views.search import _build_viewer_navigation, _build_viewer_url_params

pytestmark = pytest.mark.skip(
    reason=(
        "Superseded by impl-display-migration: viewer no longer reads "
        "CodeMapNode.  Rewrite against CodeEditionProvision once the "
        "real-data integration tests are in place."
    )
)


def _fake_edition(pk, system_code, edition_id, system_display=""):
    """Build a lightweight stand-in for a CodeEdition instance."""
    code_obj = SimpleNamespace(code=system_code, display_name=system_display)
    return SimpleNamespace(
        pk=pk,
        code=code_obj,
        edition_id=edition_id,
        code_name=f"{system_code}_{edition_id}",
        map_codes=[f"{system_code}_{edition_id}_map"],
    )


def _fake_node(node_id, map_code, title=None, division=""):
    """Build a lightweight stand-in for a CodeMapNode instance."""
    code_map = SimpleNamespace(map_code=map_code)
    return SimpleNamespace(
        node_id=node_id,
        title=title or f"Section {node_id}",
        code_map=code_map,
        page=10,
        page_end=12,
        initial_page_top=640.0,
        final_page_bottom=88.0,
        division=division,
    )


def _sliceable_qs(items):
    """Return a MagicMock queryset that supports .select_related()[:N] and .first()."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.select_related.return_value = qs
    qs.first.return_value = items[0] if items else None
    qs.__getitem__ = lambda self, key: items[key] if isinstance(key, slice) else items[key]
    return qs


# ---------------------------------------------------------------------------
# _build_viewer_navigation
# ---------------------------------------------------------------------------
class TestBuildViewerNavigation:
    def test_returns_none_when_code_empty(self):
        result = _build_viewer_navigation("", "3.1.1", "2024-01-01", "OBC_2012")
        assert result == {"previous": None, "next": None}

    def test_returns_none_when_code_has_no_underscore(self):
        result = _build_viewer_navigation("OBC", "3.1.1", "2024-01-01", "OBC_2012")
        assert result == {"previous": None, "next": None}

    @patch("core.views.search.CodeEdition")
    def test_returns_none_when_edition_not_found(self, mock_ce):
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.first.return_value = None
        mock_ce.objects.select_related.return_value = qs

        result = _build_viewer_navigation("OBC_9999", "3.1.1", "2024-01-01", "OBC_2012")
        assert result == {"previous": None, "next": None}

    @patch("core.views.search.get_source_url", return_value="")
    @patch("core.views.search.get_download_url", return_value="")
    @patch("core.views.search.get_pdf_filename", return_value="")
    @patch("core.views.search.get_code_display_name", return_value="Ontario Building Code")
    @patch("core.views.search.CodeMapNode")
    @patch("core.views.search.CodeEdition")
    def test_returns_adjacent_editions(
        self, mock_ce, mock_cmn, mock_display, mock_pdf, mock_dl, mock_src
    ):
        e1 = _fake_edition(1, "OBC", "2006", "Ontario Building Code")
        e2 = _fake_edition(2, "OBC", "2012", "Ontario Building Code")
        e3 = _fake_edition(3, "OBC", "2017", "Ontario Building Code")

        # First select_related().filter().first() returns current edition (e2)
        first_qs = MagicMock()
        first_qs.filter.return_value = first_qs
        first_qs.first.return_value = e2

        # Second select_related().filter().order_by() returns all editions
        all_qs = MagicMock()
        all_qs.filter.return_value = all_qs
        all_qs.order_by.return_value = [e1, e2, e3]

        mock_ce.objects.select_related.side_effect = [first_qs, all_qs, MagicMock(), MagicMock()]

        node = _fake_node("3.1.1", "OBC_2006_map")
        mock_cmn.objects = _sliceable_qs([node])

        # _build_viewer_url_params is called for prev (e1) and next (e3);
        # each call does its own CodeEdition + CodeMapNode lookups.
        # Re-wire select_related for the url_params calls.
        prev_qs = MagicMock()
        prev_qs.filter.return_value = prev_qs
        prev_qs.first.return_value = e1
        next_qs = MagicMock()
        next_qs.filter.return_value = next_qs
        next_qs.first.return_value = e3
        mock_ce.objects.select_related.side_effect = [first_qs, all_qs, prev_qs, next_qs]

        result = _build_viewer_navigation("OBC_2012", "3.1.1", "2024-01-01", "OBC_2012")

        prev = result["previous"]
        nxt = result["next"]
        assert prev is not None
        assert nxt is not None
        assert prev["id"] == "3.1.1"
        assert prev["code"] == "OBC_2006"
        assert nxt["id"] == "3.1.1"
        assert nxt["code"] == "OBC_2017"

    @patch("core.views.search.get_source_url", return_value="")
    @patch("core.views.search.get_download_url", return_value="")
    @patch("core.views.search.get_pdf_filename", return_value="")
    @patch("core.views.search.get_code_display_name", return_value="Ontario Building Code")
    @patch("core.views.search.CodeMapNode")
    @patch("core.views.search.CodeEdition")
    def test_first_edition_has_no_previous(
        self, mock_ce, mock_cmn, mock_display, mock_pdf, mock_dl, mock_src
    ):
        e1 = _fake_edition(1, "OBC", "2006", "Ontario Building Code")
        e2 = _fake_edition(2, "OBC", "2012", "Ontario Building Code")

        first_qs = MagicMock()
        first_qs.filter.return_value = first_qs
        first_qs.first.return_value = e1

        all_qs = MagicMock()
        all_qs.filter.return_value = all_qs
        all_qs.order_by.return_value = [e1, e2]

        next_qs = MagicMock()
        next_qs.filter.return_value = next_qs
        next_qs.first.return_value = e2

        mock_ce.objects.select_related.side_effect = [first_qs, all_qs, next_qs]

        node = _fake_node("3.1.1", "OBC_2012_map")
        mock_cmn.objects = _sliceable_qs([node])

        result = _build_viewer_navigation("OBC_2006", "3.1.1", "2024-01-01", "OBC_2012")

        assert result["previous"] is None
        assert result["next"] is not None
        assert result["next"]["code"] == "OBC_2012"

    @patch("core.views.search.get_source_url", return_value="")
    @patch("core.views.search.get_download_url", return_value="")
    @patch("core.views.search.get_pdf_filename", return_value="")
    @patch("core.views.search.get_code_display_name", return_value="Ontario Building Code")
    @patch("core.views.search.CodeMapNode")
    @patch("core.views.search.CodeEdition")
    def test_last_edition_has_no_next(
        self, mock_ce, mock_cmn, mock_display, mock_pdf, mock_dl, mock_src
    ):
        e1 = _fake_edition(1, "OBC", "2012", "Ontario Building Code")
        e2 = _fake_edition(2, "OBC", "2017", "Ontario Building Code")

        first_qs = MagicMock()
        first_qs.filter.return_value = first_qs
        first_qs.first.return_value = e2

        all_qs = MagicMock()
        all_qs.filter.return_value = all_qs
        all_qs.order_by.return_value = [e1, e2]

        prev_qs = MagicMock()
        prev_qs.filter.return_value = prev_qs
        prev_qs.first.return_value = e1

        mock_ce.objects.select_related.side_effect = [first_qs, all_qs, prev_qs]

        node = _fake_node("3.1.1", "OBC_2012_map")
        mock_cmn.objects = _sliceable_qs([node])

        result = _build_viewer_navigation("OBC_2017", "3.1.1", "2024-01-01", "OBC_2012")

        assert result["next"] is None
        assert result["previous"] is not None
        assert result["previous"]["code"] == "OBC_2012"

    @patch("core.views.search.CodeMapNode")
    @patch("core.views.search.CodeEdition")
    def test_omits_direction_when_node_missing_in_adjacent_edition(
        self, mock_ce, mock_cmn
    ):
        e1 = _fake_edition(1, "OBC", "2006")
        e2 = _fake_edition(2, "OBC", "2012")

        first_qs = MagicMock()
        first_qs.filter.return_value = first_qs
        first_qs.first.return_value = e1

        all_qs = MagicMock()
        all_qs.filter.return_value = all_qs
        all_qs.order_by.return_value = [e1, e2]

        # _build_viewer_url_params for next (e2): edition found but node missing
        next_edition_qs = MagicMock()
        next_edition_qs.filter.return_value = next_edition_qs
        next_edition_qs.first.return_value = e2

        mock_ce.objects.select_related.side_effect = [first_qs, all_qs, next_edition_qs]

        mock_cmn.objects = _sliceable_qs([])  # node not found

        result = _build_viewer_navigation("OBC_2006", "3.1.1", "2024-01-01", "OBC_2012")

        assert result["next"] is None
        assert result["previous"] is None


# ---------------------------------------------------------------------------
# _build_viewer_url_params
# ---------------------------------------------------------------------------
class TestBuildViewerUrlParams:
    def test_returns_none_when_no_underscore(self):
        result = _build_viewer_url_params(
            code_name="OBC", node_id="3.1.1",
            query_date="2024-01-01", query_code="OBC_2012",
        )
        assert result is None

    @patch("core.views.search.CodeEdition")
    def test_returns_none_for_nonexistent_edition(self, mock_ce):
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.first.return_value = None
        mock_ce.objects.select_related.return_value = qs

        result = _build_viewer_url_params(
            code_name="OBC_9999", node_id="3.1.1",
            query_date="2024-01-01", query_code="OBC_2012",
        )
        assert result is None

    @patch("core.views.search.CodeMapNode")
    @patch("core.views.search.CodeEdition")
    def test_returns_none_when_node_not_found(self, mock_ce, mock_cmn):
        edition = _fake_edition(1, "OBC", "2012")
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.first.return_value = edition
        mock_ce.objects.select_related.return_value = qs

        mock_cmn.objects = _sliceable_qs([])  # node not found

        result = _build_viewer_url_params(
            code_name="OBC_2012", node_id="99.99.99",
            query_date="2024-01-01", query_code="OBC_2012",
        )
        assert result is None

    @patch("core.views.search.get_source_url", return_value="https://example.com")
    @patch("core.views.search.get_download_url", return_value="https://example.com/dl")
    @patch("core.views.search.get_pdf_filename", return_value="OBC2012.pdf")
    @patch("core.views.search.get_code_display_name", return_value="Ontario Building Code")
    @patch("core.views.search.CodeMapNode")
    @patch("core.views.search.CodeEdition")
    def test_returns_params_for_valid_edition_and_node(
        self, mock_ce, mock_cmn, mock_display, mock_pdf, mock_dl, mock_src
    ):
        edition = _fake_edition(1, "OBC", "2012", "Ontario Building Code")
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.first.return_value = edition
        mock_ce.objects.select_related.return_value = qs

        node = _fake_node("3.1.1", "OBC_2012_map")
        mock_cmn.objects = _sliceable_qs([node])

        result = _build_viewer_url_params(
            code_name="OBC_2012", node_id="3.1.1",
            query_date="2024-01-01", query_code="OBC_2012",
        )
        assert result is not None
        assert result["id"] == "3.1.1"
        assert result["title"] == "Section 3.1.1"
        assert result["code"] == "OBC_2012"
        assert result["code_display_name"] == "Ontario Building Code 2012"
        assert result["map_code"] == "OBC_2012_map"
        assert result["page"] == 10
        assert result["page_end"] == 12
        assert result["initial_page_top"] == 640.0
        assert result["final_page_bottom"] == 88.0
        assert result["pdf_filename"] == "OBC2012.pdf"
        assert result["pdf_download_url"] == "https://example.com/dl"
        assert result["source_url"] == "https://example.com"
        assert result["query_date"] == "2024-01-01"
        assert result["query_code"] == "OBC_2012"
