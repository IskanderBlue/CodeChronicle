"""The Crown copyright acknowledgement, which is a condition of the permission.

The King's Printer for Ontario permits reproduction of Ontario legal materials
on three conditions. Two of them are markup, and a surface that reproduces the
text without them reproduces it outside the permission — which is why these are
tests rather than a style rule.
"""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from api.tests.test_integration import _create_obc_fixtures
from core.attribution import crown_years_for_editions, crown_years_for_provisions
from core.models import Code, CodeEdition, CodeEditionProvision, Regulation, User
from core.permalinks import provision_permalink_url

ACKNOWLEDGEMENT = "King&rsquo;s Printer for Ontario"
NOT_OFFICIAL = "not an official version"


#: The three loaded editions, as production holds them on 19 August 2026:
#: ``(edition_id, base reg, filed, in force)``.  Two of the three were made in
#: one year and came into force in another, which is exactly why the
#: acknowledgement cannot be read off the edition's name.
REAL_EDITIONS = [
    ("1997", "403/97", date(1997, 11, 3), date(1998, 4, 6)),
    ("2006", "350/06", date(2006, 6, 28), date(2006, 12, 31)),
    ("2012", "332/12", date(2012, 11, 2), date(2014, 1, 1)),
]


@pytest.mark.django_db
class TestTheYearIsTheOneAskedFor:
    """The King's Printer asks for the year the regulation was "first brought
    into law", which this product reads as the year it came into force.

    Nothing reads ``edition_id``. An edition is named for the year its base
    regulation was *made*, and for two of the three loaded editions that is a
    different year from the one it came into force — 1997/1998 and 2012/2014.
    These tests are what stops somebody reinstating the shortcut.
    """

    def setup_method(self):
        system = Code.objects.create(
            code="OBC", display_name="Ontario Building Code", is_national=False
        )
        for edition_id, reg_id, filed, in_force in REAL_EDITIONS:
            edition = CodeEdition.objects.create(
                code=system,
                edition_id=edition_id,
                year=int(edition_id),
                effective_date=in_force,
                source="e-Laws",
            )
            Regulation.objects.create(
                reg_id=reg_id,
                edition=edition,
                role="base",
                filed_date=filed,
                effective_date=in_force,
            )

    def test_an_edition_names_its_commencement_year_not_its_own_name(self):
        assert crown_years_for_editions(["OBC_1997"]) == "1998"
        assert crown_years_for_editions(["OBC_2012"]) == "2014"

    def test_the_filing_year_is_not_used(self):
        """O. Reg. 332/12 was filed in 2012 and came into force in 2014. The
        edition is called 2012 and the acknowledgement says 2014."""
        edition = CodeEdition.objects.get(edition_id="2012")
        base = edition.regulations.get(role="base")
        assert base.filed_date is not None

        assert base.filed_date.year == 2012
        assert edition.edition_id == "2012"
        assert crown_years_for_editions([edition]) == "2014"

    def test_several_editions_are_named_oldest_first(self):
        assert crown_years_for_editions(
            ["OBC_2012", "OBC_1997", "OBC_2006"]
        ) == "1998, 2006, 2014"

    def test_a_repeat_is_named_once(self):
        assert crown_years_for_editions(["OBC_2006", "OBC_2006"]) == "2006"

    def test_nothing_recognisable_yields_nothing(self):
        """A wrong year misidentifies which regulation was reproduced, so an
        unusable value is skipped rather than guessed."""
        assert crown_years_for_editions(["", None, "OBC"]) == ""

    def test_an_unloaded_edition_yields_nothing(self):
        assert crown_years_for_editions(["OBC_2024"]) == ""


@pytest.mark.django_db
class TestTheReadingSurfaces:
    """Every surface that reproduces legislative text carries both statements."""

    def setup_method(self):
        self.client = Client()
        _create_obc_fixtures()
        self.user = User.objects.create_user(
            email="pro@example.com", password="pw12345678", pro_courtesy=True
        )
        self.client.force_login(self.user)

    def _assert_carries(self, response):
        assert response.status_code == 200
        body = response.content.decode()
        assert ACKNOWLEDGEMENT in body
        assert NOT_OFFICIAL in body
        return body

    def test_the_year_is_the_one_the_provision_was_first_enacted_in(self):
        """A permalink names the regulation that introduced the provision, not
        the edition and not the amendment that last touched it."""
        provision = CodeEditionProvision.objects.filter(
            division="B", versions__version=0
        ).first()
        assert provision is not None
        origin = provision.origin_regulation

        years = crown_years_for_provisions([provision])

        if origin is None:
            assert years == ""
        else:
            assert years == str(origin.effective_date.year)

    def test_a_provision_permalink_carries_it(self):
        provision = CodeEditionProvision.objects.filter(
            division="B", versions__version=0
        ).first()
        assert provision is not None
        url = provision_permalink_url(
            provision.edition.code_name,
            provision.division,
            provision.provision_id,
            0,
        )

        self._assert_carries(self.client.get(url))

    def test_the_edition_contents_page_carries_it(self):
        """A contents page holds no bodies, but every entry is a title taken
        from the law."""
        edition = CodeEdition.objects.first()
        assert edition is not None

        self._assert_carries(
            self.client.get(reverse("core:edition_contents", args=[edition.code_name]))
        )

    def test_the_amendment_chain_carries_it(self):
        edition = CodeEdition.objects.first()
        assert edition is not None

        self._assert_carries(
            self.client.get(reverse("core:edition_chain", args=[edition.pk]))
        )

    def test_a_page_that_reproduces_nothing_does_not_claim_to(self):
        """The pricing page acknowledges no reproduction, because it makes
        none."""
        response = self.client.get(reverse("core:pricing"))

        assert response.status_code == 200
        assert ACKNOWLEDGEMENT not in response.content.decode()
