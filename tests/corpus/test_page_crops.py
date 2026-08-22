"""Tests for cropping a scanned page down to the provision on it.

The geometry is the part of the export that fails silently.  A wrong crop
still prints — it just prints somebody else's provision, or the same text at
two sizes — so the properties here are the ones a screenshot would not settle:
that a crop is its own region and never the union of its neighbours, and that
one provision is drawn at one scale.
"""

from datetime import date

import pytest

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    User,
)
from corpus.printing.page_crops import MARGIN_X, MARGIN_Y, build_crops

# A two-column scan: the left column, then the right, the way CCM emits them.
TWO_COLUMNS = [
    {
        "image": "documents/ont_reg_1997_v2/13.webp",
        "bboxes": [
            {"x": 0.023, "y": 0.044, "w": 0.452, "h": 0.911},
            {"x": 0.512, "y": 0.044, "w": 0.453, "h": 0.912},
        ],
    }
]


def test_no_images_is_an_empty_list():
    assert build_crops(None) == []
    assert build_crops([]) == []


def test_each_bbox_becomes_its_own_crop():
    crops = build_crops(TWO_COLUMNS)
    # Two columns, two crops — never one crop spanning both.  A union of the
    # two column regions is the whole page again, which is the thing the
    # export exists to avoid.
    assert len(crops) == 2
    assert crops[0]["x"] < crops[1]["x"]


def test_a_crop_carries_a_margin_and_stays_on_the_page():
    crops = build_crops([
        {"image": "p.webp", "bboxes": [{"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}]}
    ])
    crop = crops[0]
    assert crop["x"] == round(0.4 - MARGIN_X, 6)
    assert crop["y"] == round(0.4 - MARGIN_Y, 6)
    assert abs(crop["w"] - (0.2 + 2 * MARGIN_X)) < 1e-9
    assert abs(crop["h"] - (0.2 + 2 * MARGIN_Y)) < 1e-9


def test_a_bbox_at_the_edge_is_clamped_rather_than_bleeding_off():
    crops = build_crops([
        {"image": "p.webp", "bboxes": [{"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}]}
    ])
    crop = crops[0]
    assert crop["x"] == 0.0
    assert crop["y"] == 0.0
    assert crop["w"] == 1.0
    assert crop["h"] == 1.0


class TestOneScaleForTheWholeProvision:
    """The widest crop fills the column; the rest are drawn in proportion."""

    def test_the_widest_crop_fills_the_column(self):
        crops = build_crops([
            {
                "image": "p.webp",
                "bboxes": [
                    {"x": 0.02, "y": 0.1, "w": 0.45, "h": 0.3},   # a column
                    {"x": 0.02, "y": 0.5, "w": 0.90, "h": 0.3},   # a wide table
                ],
            }
        ])
        column, table = crops
        assert table["width_pct"] == 100.0
        # The column is genuinely about half as wide, and saying so is what
        # keeps the type one size: drawing both at 100% would print the column
        # at twice the table's scale.
        assert 50 < column["width_pct"] < 55

    def test_scan_skew_does_not_change_the_scale_perceptibly(self):
        crops = build_crops(TWO_COLUMNS)
        widths = [c["width_pct"] for c in crops]
        # Measured over the corpus the median width spread inside one version
        # is 0.3% of page width — scanner skew, not structure.  It must not
        # read as two different sizes.
        assert max(widths) - min(widths) < 1.0


def test_the_offsets_place_the_image_inside_the_wrapper():
    crops = build_crops([
        {"image": "p.webp", "bboxes": [{"x": 0.5, "y": 0.25, "w": 0.4, "h": 0.2}]}
    ])
    crop = crops[0]
    # The image is drawn 1/w times the wrapper's width and pulled left by the
    # crop's own offset; both are percentages of the wrapper, so they hold at
    # any printed size.
    assert crop["image_width_pct"] == round(100 / crop["w"], 4)
    assert crop["offset_left_pct"] == round(-crop["x"] / crop["w"] * 100, 4)
    assert crop["offset_top_pct"] == round(-crop["y"] / crop["h"] * 100, 4)


def test_a_page_with_no_bboxes_is_passed_through_whole():
    crops = build_crops([{"image": "elaws/table.jpg", "bboxes": []}])
    # A pre-composited artefact: the image already *is* the content, so there
    # is nothing to crop away.
    assert crops == [{"image": "elaws/table.jpg", "page": 1, "full": True,
                      "width_pct": 100.0}]


def test_a_degenerate_bbox_is_dropped_rather_than_drawn_as_a_sliver():
    crops = build_crops([
        {"image": "p.webp", "bboxes": [
            {"x": 1.0, "y": 1.0, "w": 0.0, "h": 0.0},
            {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4},
        ]}
    ])
    assert len(crops) == 1


def test_pages_are_numbered_for_the_caption():
    crops = build_crops([
        {"image": "a.webp", "bboxes": [{"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}]},
        {"image": "b.webp", "bboxes": [{"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}]},
    ])
    assert [c["page"] for c in crops] == [1, 2]


# A column beside a full-page table: the pair the one-scale rule exists for.
MIXED_WIDTHS = [
    {
        "image": "documents/ont_reg_1997_v2/13.webp",
        "bboxes": [
            {"x": 0.023, "y": 0.100, "w": 0.452, "h": 0.300},
            {"x": 0.023, "y": 0.500, "w": 0.930, "h": 0.300},
        ],
    }
]


@pytest.fixture
def scanned(db, settings):
    """One free-tier provision whose version is a scan."""
    settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006, effective_date=date(2006, 12, 31),
    )
    prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.2.5.7.", level="article", division="B",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=prov,
        version=0,
        effective_date=date(2006, 12, 31),
        title="Fire Department Access Routes",
        page_images=MIXED_WIDTHS,
    )
    return prov


@pytest.mark.django_db
class TestTheExhibitIsDrawnAtTheScaleThatWasComputed:
    """The handoff, which the unit tests above cannot reach.

    ``build_crops`` is proven on its own, but nothing it returns matters until
    a page prints it.  The print view attaches the crops to the version rows
    and the shared partial places them, and a scale computed correctly and
    then dropped prints exactly the fault the rule exists to prevent — with
    every unit test still green.
    """

    URL = "/provision/OBC_2006/B/3.2.5.7./v0/"

    def _printed(self, client):
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")
        return client.get(f"{self.URL}print/").content.decode()

    def test_the_exhibit_carries_the_computed_widths(self, client, scanned):
        printed = self._printed(client)
        column, table = build_crops(MIXED_WIDTHS)
        # The widest fills the printable width; the column is drawn at its
        # true share of it.  Both are read off build_crops rather than written
        # out, so this asserts the handoff and never re-states the geometry.
        assert table["width_pct"] == 100.0
        assert f'width: {table["width_pct"]}%' in printed
        assert f'width: {column["width_pct"]}%' in printed
        assert column["width_pct"] < 50

    def test_the_crop_is_placed_not_just_sized(self, client, scanned):
        """A wrapper at the right width holding an unmoved image shows the
        neighbouring provision at the right size — a plausible wrong exhibit.
        """
        printed = self._printed(client)
        for crop in build_crops(MIXED_WIDTHS):
            assert f'width: {crop["image_width_pct"]}%' in printed
            assert f'left: {crop["offset_left_pct"]}%' in printed
            assert f'top: {crop["offset_top_pct"]}%' in printed

    def test_the_reading_page_shows_the_whole_page_instead(self, client, scanned):
        """Crops are the export form.  On screen the scan is shown whole with
        the region highlighted, because a reader wants it in its setting.
        """
        body = client.get(self.URL).content.decode()
        assert "doc-crop" not in body
