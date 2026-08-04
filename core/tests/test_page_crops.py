"""Tests for cropping a scanned page down to the provision on it.

The geometry is the part of the export that fails silently.  A wrong crop
still prints — it just prints somebody else's provision, or the same text at
two sizes — so the properties here are the ones a screenshot would not settle:
that a crop is its own region and never the union of its neighbours, and that
one provision is drawn at one scale.
"""

from core.page_crops import MARGIN_X, MARGIN_Y, build_crops

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
