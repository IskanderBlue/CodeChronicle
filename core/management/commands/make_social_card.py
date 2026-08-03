"""Draw the static social card that every forwarded link shows.

The card is a build artifact, like the Tailwind CSS: a developer runs this
command and commits the PNG, because production collects static files while
building the image and cannot draw one then.

The coverage span is read from :class:`~core.models.CorpusCurrency`, never
typed in.  A figure about the corpus that a person writes by hand is a figure
that goes stale the next time an edition loads, and this one is printed on
every link anybody sends.  Re-run the command after loading an edition; the
command prints the span it drew so the change is visible in the diff.

Pillow is a development dependency only.  Nothing the server runs imports this
module — Django loads a management command's module when the command runs.
"""

from pathlib import Path
from typing import Any

from coloured_logger import Logger
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageDraw, ImageFont

from core.models import CorpusCurrency
from core.seo import SOCIAL_IMAGE_PATH

logger = Logger(__name__)

#: Every crawler scales to this, and several crop anything else.
WIDTH, HEIGHT = 1200, 630

#: The design tokens, as RGB.  Named for the role, matching base.html: paper,
#: ink, and the one accent (oxblood).
PAPER = (251, 248, 241)
INK = (26, 23, 20)
INK_3 = (107, 98, 89)
RULE = (205, 196, 182)
OXBLOOD = (122, 31, 43)

#: The card's own fonts.  The site loads Source Serif 4 and JetBrains Mono from
#: a CDN, which a drawing program cannot use, so the card falls back to the
#: same families the CSS stack names next: a transitional serif and a
#: fixed-width face.  First readable candidate wins.
SERIF_CANDIDATES = (
    "C:/Windows/Fonts/georgiab.ttf",
    "C:/Windows/Fonts/georgia.ttf",
    "C:/Windows/Fonts/times.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
)
MONO_CANDIDATES = (
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)

TAGLINE = "The Ontario Building Code: dated, sourced, and searchable."

#: A card travels further than the link it came from — it is screenshotted,
#: pasted into a deck, and forwarded again.  The domain is how a reader who
#: meets the image alone can get back to the site.
DOMAIN = "codechronicle.ca"

#: Where the text block starts, and how wide it may run before it collides
#: with the right edge.
LEFT = 96
TEXT_WIDTH = WIDTH - LEFT * 2


def _font(
    candidates: tuple[str, ...], size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """The first candidate that opens, else Pillow's built-in face.

    A missing font must not stop the card being drawn.  The fallback is ugly
    at this size, so the command says which face it used.
    """
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    logger.warning("no candidate font opened; falling back to the built-in face")
    return ImageFont.load_default(size=size)


def _fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    candidates: tuple[str, ...],
    size: int,
    width: int = TEXT_WIDTH,
    floor: int = 20,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """The largest size at or below ``size`` that keeps ``text`` inside ``width``.

    The copy on this card is edited by people, and a longer sentence that
    silently runs off the right edge is a defect nobody sees until a link is
    already forwarded.  So the drawing measures rather than trusts.
    """
    while size > floor:
        font = _font(candidates, size)
        if draw.textlength(text, font=font) <= width:
            return font
        size -= 2
    return _font(candidates, floor)


class Command(BaseCommand):
    help = "Draw the 1200x630 social card into static/, from the corpus stamp."

    def add_arguments(self, parser) -> None:
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

        currency = CorpusCurrency.get_solo()
        span = (currency.corpus_span if currency else "") or ""
        label = (currency.corpus_label if currency else "") or ""
        if not span:
            # A card that states no span is honest; a card that states a made-up
            # one is not.  Say so loudly rather than draw a placeholder.
            logger.warning(
                "no CorpusCurrency stamp, so the card carries no span.  "
                "Load an edition and re-run to put the coverage back on it."
            )

        image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
        draw = ImageDraw.Draw(image)

        # The accent bar reads as the spine of a bound volume, which is the
        # same figure the masthead uses.
        draw.rectangle((0, 0, 18, HEIGHT), fill=OXBLOOD)

        nameplate = _fit(draw, "CodeChronicle", SERIF_CANDIDATES, 96)
        tagline = _fit(draw, TAGLINE, SERIF_CANDIDATES, 40)
        mono = _fit(draw, span or label, MONO_CANDIDATES, 28)

        draw.text((LEFT, 150), "CodeChronicle", font=nameplate, fill=INK)
        draw.text((LEFT, 290), TAGLINE, font=tagline, fill=INK_3)

        draw.line((LEFT, 420, WIDTH - LEFT, 420), fill=RULE, width=2)

        if span:
            draw.text((LEFT, 456), span.upper(), font=mono, fill=OXBLOOD)
        if label:
            draw.text((LEFT, 502), label.upper(), font=mono, fill=INK_3)

        # Right-aligned against the same margin the text block uses, so the
        # domain reads as a colophon rather than as another line of the block.
        domain_font = _fit(draw, DOMAIN, MONO_CANDIDATES, 24)
        draw.text(
            (WIDTH - LEFT - draw.textlength(DOMAIN, font=domain_font), 502),
            DOMAIN,
            font=domain_font,
            fill=INK_3,
        )

        image.save(out, "PNG", optimize=True)
        logger.info(
            "wrote %s (%dx%d, %d bytes); span=%r label=%r",
            out, WIDTH, HEIGHT, out.stat().st_size, span, label,
        )

    def _default_path(self) -> Path:
        roots = list(getattr(settings, "STATICFILES_DIRS", []))
        if not roots:
            raise CommandError(
                "STATICFILES_DIRS is empty, so there is nowhere to write the "
                "card.  Pass --out."
            )
        return Path(roots[0]) / SOCIAL_IMAGE_PATH
