"""Tests for the drawn social card.

The card is the whole of what a forwarded link shows, and it is redrawn by
hand after a data load.  Two things can go wrong quietly: the drawing can
disagree with the size the tags declare, and the dates on it can stop being
the dates in the database.  Neither shows up anywhere else.
"""

from datetime import date

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from PIL import Image

from core.management.commands.make_social_card import edition_bands
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
)
from core.seo import SOCIAL_IMAGE_HEIGHT, SOCIAL_IMAGE_WIDTH


def _edition(code, edition_id, start, end, *, with_provision=True):
    edition = CodeEdition.objects.create(
        code=code,
        edition_id=edition_id,
        year=int(edition_id[:4]),
        effective_date=start,
        ineffective_date=end,
    )
    if with_provision:
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id="1.1.1.1.", level="article", division="B",
        )
        CodeEditionProvisionVersion.objects.create(
            provision=provision, version=0, effective_date=start,
            ineffective_date=end, title="Application", html="<p>text</p>",
        )
    return edition


@pytest.fixture
def obc(db):
    """Three closed editions, with the 1997 edition's real start in 1998."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    _edition(code, "1997", date(1998, 4, 6), date(2006, 12, 31))
    _edition(code, "2006", date(2006, 12, 31), date(2014, 1, 1))
    _edition(code, "2012", date(2014, 1, 1), date(2025, 1, 1))
    return code


@pytest.mark.django_db
class TestEditionBands:
    def test_bands_come_from_the_edition_rows_in_date_order(self, obc):
        assert edition_bands() == [
            ("1997", date(1998, 4, 6), date(2006, 12, 31)),
            ("2006", date(2006, 12, 31), date(2014, 1, 1)),
            ("2012", date(2014, 1, 1), date(2025, 1, 1)),
        ]

    def test_the_first_band_starts_when_the_edition_did_not_when_it_was_named(
        self, obc
    ):
        """OBC 1997 came into force on 1998-04-06.  A card that drew the band
        at its name would be wrong about the one thing this product sells."""
        edition_id, start, _ = edition_bands()[0]
        assert edition_id == "1997"
        assert start == date(1998, 4, 6)

    def test_an_open_edition_is_left_out(self, obc):
        """The edition in force has no end, and a band needs both ends."""
        _edition(obc, "2024", date(2025, 1, 1), None)
        assert [band[0] for band in edition_bands()] == ["1997", "2006", "2012"]

    def test_an_edition_with_no_provisions_is_left_out(self, obc):
        """A consolidation row we hold no text for is not coverage."""
        _edition(obc, "1990", date(1990, 10, 1), date(1998, 4, 6), with_provision=False)
        assert [band[0] for band in edition_bands()] == ["1997", "2006", "2012"]


@pytest.mark.django_db
class TestDrawing:
    def test_the_card_is_drawn_at_the_size_the_tags_declare(self, obc, tmp_path):
        out = tmp_path / "card.png"
        call_command("make_social_card", out=str(out))
        with Image.open(out) as card:
            assert card.size == (SOCIAL_IMAGE_WIDTH, SOCIAL_IMAGE_HEIGHT)
            assert card.width == card.height * 2

    def test_no_editions_is_an_error_not_a_blank_card(self, db, tmp_path):
        with pytest.raises(CommandError, match="no closed edition"):
            call_command("make_social_card", out=str(tmp_path / "card.png"))

    def test_too_many_editions_refuses_rather_than_clips(self, obc, tmp_path):
        """Each edition costs 46px and the frame cannot grow.  The staircase
        must become a single row before the card silently overflows — and it
        would overflow on a data load, when nobody is looking at the card."""
        for edition_id, start, end in (
            ("1975", date(1975, 12, 31), date(1983, 8, 8)),
            ("1983", date(1983, 8, 8), date(1986, 7, 7)),
            ("1986", date(1986, 7, 7), date(1990, 10, 1)),
            ("1990", date(1990, 10, 1), date(1998, 4, 6)),
        ):
            _edition(obc, edition_id, start, end)
        with pytest.raises(CommandError, match="outgrown the card"):
            call_command("make_social_card", out=str(tmp_path / "card.png"))
