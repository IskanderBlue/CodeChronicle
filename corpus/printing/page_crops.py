"""Cropping a scanned page down to the provision that is actually on it.

The pre-e-Laws editions are scans.  A version's ``page_images`` name whole
pages, and ``bboxes`` mark the region of each page the provision occupies —
``{x, y, w, h}`` as image fractions with a top-left origin.  On screen the
page is shown whole with the region highlighted, which is right for reading:
the reader can see the provision in its setting.

An export is a different job.  A printed page carries the neighbouring
provisions too, and an exhibit that shows more than it quotes invites the
argument it exists to close.  So the export crops.

Two rules do the work, and the second is the one that is easy to get wrong:

* **A crop is its own bbox plus a small margin**, clamped to the page.  Never
  the union of the bboxes on a page: a provision's regions are separate for a
  reason, and a union of two column regions is the whole page again.
* **One scale for the whole provision.**  The widths are real and they are not
  continuous — measured over the corpus they cluster into a fragment, a column
  (``w≈0.45``, these pages are set in two columns) and a full-page table
  (``w≈0.93``).  Drawing every crop at the printable width would print a
  narrow fragment in giant type beside a wide table in tiny type, and would
  make one continuous column of text change size from page to page.  So the
  widest crop of a provision fills the printable width and every other crop is
  drawn in proportion to it.  Type size is then identical throughout, which is
  what makes a set of crops read as one document.

The crop itself is done in CSS — an ``overflow: hidden`` wrapper with the
whole image positioned inside it — so no image is processed, nothing new is
stored, and the printed pixels are the ones the page already serves.  The one
value CSS cannot supply is the wrapper's height, because that needs the
image's aspect ratio and CCM ships no dimensions with ``page_images``.  The
print page reads it off each image once it loads; see
``partials/_document_crops.html``.
"""

from __future__ import annotations

from typing import Any

#: Margin around a bbox, as a fraction of the page.  Separate values for the
#: two axes so the printed margin looks even: a page is taller than it is
#: wide, so the same fraction of height is a bigger margin than that fraction
#: of width.  These are about 2 mm each on a Letter-shaped page.
MARGIN_X = 0.010
MARGIN_Y = 0.007


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def build_crops(page_images: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """One crop per bbox, in reading order, ready for the print template.

    Reading order is the order CCM emits: page by page, and within a page the
    regions in the order they are read.  On a two-column page that is the left
    column then the right one, so stacking the crops vertically puts the text
    in reading order — which the original page does not do.

    A page image with no bboxes is passed through whole (``full`` is True).
    That is a pre-composited artefact — an e-Laws table JPG, say — where the
    image already *is* the content, and there is nothing to crop away.

    Returns an empty list for no images, so a caller can test the list rather
    than testing the input twice.
    """
    entries = page_images or []
    boxes: list[dict[str, Any]] = []
    for page_index, entry in enumerate(entries, start=1):
        image = entry.get("image") or ""
        if not image:
            continue
        bboxes = entry.get("bboxes") or []
        if not bboxes:
            boxes.append({"image": image, "page": page_index, "full": True})
            continue
        for bbox in bboxes:
            if bbox.get("w", 0) <= 0 or bbox.get("h", 0) <= 0:
                # A bbox with no area marks nothing.  Tested before the margin
                # is added, because the margin would turn it into a real —
                # and meaningless — sliver of the page.
                continue
            left = _clamp(bbox["x"] - MARGIN_X)
            top = _clamp(bbox["y"] - MARGIN_Y)
            right = _clamp(bbox["x"] + bbox["w"] + MARGIN_X)
            bottom = _clamp(bbox["y"] + bbox["h"] + MARGIN_Y)
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                # A degenerate bbox.  Dropped rather than drawn as a sliver:
                # an empty frame in an exhibit reads as missing content.
                continue
            boxes.append({
                "image": image,
                "page": page_index,
                "full": False,
                "x": left,
                "y": top,
                "w": width,
                "h": height,
            })

    croppable = [b for b in boxes if not b["full"]]
    widest = max((b["w"] for b in croppable), default=1.0)
    for box in boxes:
        if box["full"]:
            box["width_pct"] = 100.0
            continue
        # The one-scale rule: the widest crop fills the column, the rest are
        # drawn in proportion.  Everything else here is the CSS crop —
        # percentages of the wrapper, so they hold at any printed size.
        box["width_pct"] = round(box["w"] / widest * 100, 4)
        box["image_width_pct"] = round(100 / box["w"], 4)
        box["offset_left_pct"] = round(-box["x"] / box["w"] * 100, 4)
        box["offset_top_pct"] = round(-box["y"] / box["h"] * 100, 4)
    return boxes
