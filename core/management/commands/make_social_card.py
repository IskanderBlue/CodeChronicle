"""Draw the social card that every forwarded link shows.

The card is a build artifact, like the Tailwind CSS: a developer runs this
command and commits the PNG, because production collects static files while
building the image and cannot draw one then.

Nothing on it is typed in.  The edition bands are read from
:class:`~core.models.CodeEdition`, which is the same source the masthead's
corpus span measures, so the card and the masthead cannot disagree.  **Re-run
the command after loading an edition**; the command prints the bands it drew
so the change is visible in the diff.

Two rules the drawing depends on:

* **Edition dates, not version dates.**  A handful of provisions outlive their
  edition — five of the 2012 edition's versions run to 2025-03-31, three of
  the 2006 edition's to 2016-01-01 — and a tail of five must not set the width
  of a band standing for thousands.  ``CodeEdition.effective_date`` and
  ``ineffective_date`` are what a reader means by "the 2006 edition".
* **The frame is fixed at 2:1 and the bands are not.**  Each edition costs 46
  pixels and the frame cannot grow, so the command refuses to draw a card that
  would overflow rather than write a clipped one.  At four editions the
  staircase must become a single row of contiguous segments; the editions abut,
  so one row is faithful and its height is constant.

Pillow is a development dependency only.  Nothing the server runs imports this
module — Django loads a management command's module when the command runs.
"""

from datetime import date
from pathlib import Path
from typing import Any

from coloured_logger import Logger
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageChops, ImageDraw, ImageFont

from core.models import CodeEdition, CodeEditionProvisionVersion
from core.seo import SOCIAL_IMAGE_HEIGHT, SOCIAL_IMAGE_PATH, SOCIAL_IMAGE_WIDTH

logger = Logger(__name__)

#: The canvas the card is drawn on, and the frame it is cut to.  The frame is
#: 2:1 because that is the ratio every platform renders without cropping;
#: the canvas is taller so the drawing can be measured and then centred.
WIDTH = SOCIAL_IMAGE_WIDTH
FRAME_H = SOCIAL_IMAGE_HEIGHT
WORK_H = 900

#: The design tokens, as RGB.  Named for the role, matching base.html.
PAPER = (251, 248, 241)
INK = (26, 23, 20)
INK_3 = (107, 98, 89)
RULE = (205, 196, 182)
BAND = (232, 226, 214)
OXBLOOD = (122, 31, 43)

#: The accent bar down the left edge, and the margins around the text column.
SPINE = 18
LEFT = 72
RIGHT = 60
TEXT_WIDTH = WIDTH - LEFT - RIGHT

#: The vendored faces.  The site loads these families from a CDN, which a
#: drawing program cannot use, and the machine that draws the card has no
#: Source Serif 4 installed — so without these the wordmark on a forwarded
#: link would not be the wordmark on the site.  See fonts/README.md.
FONT_DIR = Path(settings.BASE_DIR) / "fonts"
SERIF_BOLD = FONT_DIR / "SourceSerif4-Bold.ttf"
SERIF_ITALIC = FONT_DIR / "SourceSerif4-MediumItalic.ttf"
SERIF_SEMI = FONT_DIR / "SourceSerif4-SemiBold.ttf"
MONO = FONT_DIR / "JetBrainsMono-Regular.ttf"
MONO_SEMI = FONT_DIR / "JetBrainsMono-SemiBold.ttf"

#: The wordmark, split the way base.html splits it: "Code" bold roman,
#: "Chronicle" medium italic.  The domain suffix carries the same ink — the
#: parts are told apart by weight and style, and a third distinction by colour
#: would read as de-emphasis on the one string that says where to go.
WORDMARK = (("Code", SERIF_BOLD), ("Chronicle", SERIF_ITALIC), (".ca", SERIF_SEMI))

#: The app bar sets the wordmark at -0.02em.
TRACKING = -0.02

SUBTITLE = "Dated, sourced, searchable building codes."
BAND_LABEL = "ONTARIO BUILDING CODE"

#: Geometry of the edition staircase.
BAR_H = 36
BAR_GAP = 10

#: Paper left above and below the drawing when it is shorter than the frame.
MIN_PAD = 20


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    """Open a vendored face.

    A missing file is fatal rather than a fallback: falling back to whatever
    serif the machine happens to have is how the card came to carry a wordmark
    that was not the site's.
    """
    try:
        return ImageFont.truetype(str(path), size)
    except OSError as exc:  # pragma: no cover - a deleted vendored file
        raise CommandError(f"cannot open the vendored face {path}: {exc}") from exc


def _tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    tracking: float,
) -> float:
    """Draw ``text`` with letter-spacing, and return the x it ended at.

    Pillow has no tracking, so the run is drawn a character at a time.
    """
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking
    return x


def _wordmark_width(draw: ImageDraw.ImageDraw, size: int) -> float:
    """How wide the three runs are at ``size``, tracking included."""
    tracking = size * TRACKING
    return sum(
        draw.textlength(char, font=_font(path, size)) + tracking
        for text, path in WORDMARK
        for char in text
    )


def _fit_wordmark(draw: ImageDraw.ImageDraw) -> int:
    """The largest size whose wordmark still fits the text column.

    Setting the wordmark to the measure is what makes the masthead define the
    card's width rather than sit inside it.
    """
    size = 40
    while size < 300 and _wordmark_width(draw, size + 2) <= TEXT_WIDTH:
        size += 2
    return size


def _fit_line(
    draw: ImageDraw.ImageDraw, text: str, path: Path, start: int, floor: int = 20
) -> ImageFont.FreeTypeFont:
    """The largest size at or below ``start`` that keeps ``text`` on one line."""
    size = start
    while size > floor and draw.textlength(text, font=_font(path, size)) > TEXT_WIDTH:
        size -= 1
    return _font(path, size)


def edition_bands() -> list[tuple[str, date, date]]:
    """The editions the corpus serves, with their in-force windows.

    Only editions that actually carry provisions, and only closed ones: a
    band needs both ends.  Ordered by date, never by name — OBC 1997 is named
    for the year it was made and came into force in 1998.
    """
    with_provisions = set(
        CodeEditionProvisionVersion.objects.values_list(
            "provision__edition_id", flat=True
        ).distinct()
    )
    return [
        (edition.edition_id, edition.effective_date, edition.ineffective_date)
        for edition in CodeEdition.objects.filter(pk__in=with_provisions).order_by(
            "effective_date"
        )
        if edition.effective_date and edition.ineffective_date
    ]


def _ink_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    """The drawing's bounding box, ignoring the spine.

    The bar runs the full height, so a box over the whole image always returns
    the whole image and reports no dead space at all.
    """
    body = image.crop((SPINE + 2, 0, image.width, image.height))
    return ImageChops.difference(body, Image.new("RGB", body.size, PAPER)).getbbox()


class Command(BaseCommand):
    help = "Draw the social card into static/, from the edition windows."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--out",
            default=None,
            help=(
                "Where to write the PNG.  Defaults to the first STATICFILES_DIRS "
                f"entry plus {SOCIAL_IMAGE_PATH}."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        out = Path(options["out"]) if options["out"] else self._default_path()
        out.parent.mkdir(parents=True, exist_ok=True)

        bands = edition_bands()
        if not bands:
            raise CommandError(
                "no closed edition has provisions, so the card has no bands to "
                "draw.  Load an edition and re-run."
            )

        image = Image.new("RGB", (WIDTH, WORK_H), PAPER)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, SPINE, WORK_H), fill=OXBLOOD)

        y_rule = self._draw_masthead(draw)
        y_sub, sub_size = self._draw_subtitle(draw, y_rule)
        self._draw_bands(draw, y_sub + sub_size + 110, bands)

        card = self._frame(image)
        card.save(out, "PNG", optimize=True)

        if card.size != (SOCIAL_IMAGE_WIDTH, SOCIAL_IMAGE_HEIGHT):  # pragma: no cover
            raise CommandError(
                f"the card came out {card.width}x{card.height}, but core.seo "
                f"declares {SOCIAL_IMAGE_WIDTH}x{SOCIAL_IMAGE_HEIGHT}."
            )

        logger.info(
            "wrote %s (%dx%d, %d bytes); bands: %s",
            out, card.width, card.height, out.stat().st_size,
            ", ".join(f"{e} {s}–{x}" for e, s, x in bands),
        )

    # ── the drawing, top to bottom ──────────────────────────────────────

    def _draw_masthead(self, draw: ImageDraw.ImageDraw) -> int:
        """Wordmark set to the measure, and the rule welded under it."""
        size = _fit_wordmark(draw)
        tracking = size * TRACKING
        x: float = LEFT
        for text, path in WORDMARK:
            x = _tracked(draw, (x, 88), text, _font(path, size), INK, tracking)
        bottom = draw.textbbox((LEFT, 88), "CodeChronicle", font=_font(SERIF_BOLD, size))[3]
        y_rule = int(bottom) + 24
        draw.line((LEFT, y_rule, WIDTH - RIGHT, y_rule), fill=RULE, width=2)
        return y_rule

    def _draw_subtitle(self, draw: ImageDraw.ImageDraw, y_rule: int) -> tuple[int, int]:
        font = _fit_line(draw, SUBTITLE, SERIF_SEMI, 54)
        y = y_rule + 34
        draw.text((LEFT, y), SUBTITLE, font=font, fill=INK_3)
        return y, int(font.size)

    def _draw_bands(
        self, draw: ImageDraw.ImageDraw, y: int, bands: list[tuple[str, date, date]]
    ) -> None:
        """The editions as bands on one axis, with the dates on a shared rule.

        The bands abut, so every end date is the next start date.  Printing
        both inside each band said each boundary twice and overran the
        narrowest band.
        """
        first, last = bands[0][1], bands[-1][2]
        span = (last - first).days
        x0, x1 = LEFT, WIDTH - RIGHT

        def at(when: date) -> int:
            return x0 + round((when - first).days / span * (x1 - x0))

        draw.text((LEFT, y - 44), BAND_LABEL, font=_font(MONO_SEMI, 22), fill=OXBLOOD)

        year_font = _font(MONO_SEMI, 22)
        for index, (edition_id, start, end) in enumerate(bands):
            top = y + index * (BAR_H + BAR_GAP)
            draw.rectangle((at(start), top, at(end), top + BAR_H), fill=BAND)
            draw.rectangle((at(start), top, at(start) + 4, top + BAR_H), fill=OXBLOOD)
            label_w = draw.textlength(edition_id, font=year_font)
            middle = (at(start) + at(end)) / 2
            if at(end) - at(start) > label_w + 16:
                draw.text(
                    (middle - label_w / 2, top + (BAR_H - 22) // 2),
                    edition_id, font=year_font, fill=INK,
                )

        date_font = _font(MONO, 19)
        y_axis = y + len(bands) * (BAR_H + BAR_GAP) + 10
        draw.line((x0, y_axis, x1, y_axis), fill=RULE, width=2)
        boundaries = [band[1] for band in bands] + [bands[-1][2]]
        for index, when in enumerate(boundaries):
            x = at(when)
            draw.line((x, y_axis - 5, x, y_axis + 5), fill=OXBLOOD, width=2)
            text = when.isoformat()
            width = draw.textlength(text, font=date_font)
            last_one = index == len(boundaries) - 1
            draw.text(
                (x1 - width if last_one else x, y_axis + 14),
                text, font=date_font, fill=INK_3,
            )

    def _frame(self, image: Image.Image) -> Image.Image:
        """Centre the drawing in the 2:1 frame, refusing to clip it."""
        box = _ink_box(image)
        if box is None:  # pragma: no cover - only a blank card reaches this
            raise CommandError("nothing was drawn")
        height = box[3] - box[1]
        if height + MIN_PAD * 2 > FRAME_H:
            raise CommandError(
                f"the drawing is {height}px tall and the frame is {FRAME_H}px. "
                "Each edition costs "
                f"{BAR_H + BAR_GAP}px, so the staircase has outgrown the card. "
                "Draw the editions as one row of contiguous segments instead: "
                "they abut, so one row is faithful and its height is constant."
            )
        centre = (box[1] + box[3]) // 2
        top = max(0, min(image.height - FRAME_H, centre - FRAME_H // 2))
        return image.crop((0, top, WIDTH, top + FRAME_H))

    def _default_path(self) -> Path:
        roots = list(getattr(settings, "STATICFILES_DIRS", []))
        if not roots:
            raise CommandError(
                "STATICFILES_DIRS is empty, so there is nowhere to write the "
                "card.  Pass --out."
            )
        return Path(roots[0]) / SOCIAL_IMAGE_PATH
