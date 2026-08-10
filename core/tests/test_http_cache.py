"""Conditional responses on the read surfaces (``core.http_cache``).

The subject is cost, not correctness of the page body: a crawler that fetches
the same provision six times should render it once.  These tests pin the three
rules that make that safe — anonymous only, the corpus stamp drives it, and a
data load or a deploy invalidates it.
"""

from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.http import http_date

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    CorpusCurrency,
    EngagementEvent,
    Regulation,
    User,
)

PERMALINK = reverse(
    "core:provision_permalink_no_division",
    kwargs={"code_edition": "OBC_1997", "provision_id": "1.1.1.1.", "version": 0},
)


@pytest.fixture
def corpus(db, settings):
    """A free-tier provision, plus the stamp the validator reads."""
    settings.FREE_TIER_CODE_NAMES = ["OBC_1997"]
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="1997", year=1997, effective_date=date(1998, 4, 6),
    )
    provision = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.1.1.1.", level="article", division="",
    )
    version = CodeEditionProvisionVersion.objects.create(
        provision=provision, version=0, effective_date=date(1998, 4, 6),
        title="Application", html="<p>This Code applies to all buildings.</p>",
    )
    Regulation.objects.create(
        reg_id="403/97", edition=edition, role="base",
        effective_date=date(1998, 4, 6),
    )
    CorpusCurrency.refresh()
    return {"edition": edition, "provision": provision, "version": version}


def _currency() -> CorpusCurrency:
    currency = CorpusCurrency.get_solo()
    assert currency is not None
    return currency


def _stamp() -> str:
    return http_date(_currency().refreshed_at.timestamp())


@pytest.mark.django_db
class TestAnonymousGetsAValidator:
    def test_first_fetch_carries_last_modified(self, client: Client, corpus):
        response = client.get(PERMALINK)
        assert response.status_code == 200
        assert response["Last-Modified"] == _stamp()

    def test_repeat_fetch_is_not_modified(self, client: Client, corpus):
        first = client.get(PERMALINK)
        second = client.get(PERMALINK, HTTP_IF_MODIFIED_SINCE=first["Last-Modified"])
        assert second.status_code == 304

    def test_the_response_varies_on_cookie(self, client: Client, corpus):
        # Without this a shared cache could hand a free-tier body to a Pro
        # subscriber, because the validator deliberately differs by reader.
        response = client.get(PERMALINK)
        assert "Cookie" in response.get("Vary", "")

    def test_a_304_renders_nothing_and_records_no_view(
        self, client: Client, corpus
    ):
        first = client.get(PERMALINK)
        EngagementEvent.objects.all().delete()
        second = client.get(PERMALINK, HTTP_IF_MODIFIED_SINCE=first["Last-Modified"])
        assert second.status_code == 304
        # A 304 is not a reading.  Counting it as one is how a bot-heavy
        # crawl inflates the traction figures on /insights/.
        assert EngagementEvent.objects.count() == 0


@pytest.mark.django_db
class TestTheStampTracksTheCorpus:
    def test_a_data_load_invalidates_the_cached_copy(self, client: Client, corpus):
        first = client.get(PERMALINK)
        # Move the stamp on rather than calling refresh() and racing the
        # clock: HTTP dates carry whole seconds, so a reload finishing in the
        # same second as the fetch above would legitimately still answer 304.
        # The subject here is that a *newer* stamp invalidates the copy.
        CorpusCurrency.objects.filter(pk=CorpusCurrency.SINGLETON_PK).update(
            refreshed_at=timezone.now() + timedelta(seconds=2)
        )
        again = client.get(PERMALINK, HTTP_IF_MODIFIED_SINCE=first["Last-Modified"])
        assert again.status_code == 200
        assert again["Last-Modified"] != first["Last-Modified"]

    def test_refresh_moves_the_stamp(self, corpus):
        """``load_edition`` ends with this call, so it must bump the stamp."""
        before = _currency().refreshed_at
        CorpusCurrency.refresh()
        assert _currency().refreshed_at > before

    def test_no_validator_before_the_first_load(self, client: Client, corpus):
        CorpusCurrency.objects.all().delete()
        response = client.get(PERMALINK)
        assert response.status_code == 200
        assert response.get("Last-Modified") is None


@pytest.mark.django_db
class TestSignedInReadersAreNeverCached:
    def test_an_authenticated_reader_gets_no_validator(
        self, client: Client, corpus
    ):
        user = User.objects.create_user(email="reader@example.com", password="pw12345!")
        client.force_login(user)
        response = client.get(PERMALINK)
        assert response.status_code == 200
        assert response.get("Last-Modified") is None

    def test_an_anonymous_stamp_cannot_freeze_a_subscriber(
        self, client: Client, corpus
    ):
        """The upgrade case: a reader caches a page, then signs in.

        If the validator ignored the reader, the 304 would keep showing the
        free-tier rendering to somebody who has just paid for the other one.
        """
        anon = client.get(PERMALINK)
        user = User.objects.create_user(email="pro@example.com", password="pw12345!")
        client.force_login(user)
        after = client.get(PERMALINK, HTTP_IF_MODIFIED_SINCE=anon["Last-Modified"])
        assert after.status_code == 200


@pytest.mark.django_db
class TestTheExhibitIsNeverValidated:
    def test_the_print_route_carries_no_validator(self, client: Client, corpus):
        url = reverse(
            "core:provision_print_no_division",
            kwargs={"code_edition": "OBC_1997", "provision_id": "1.1.1.1.", "version": 0},
        )
        response = client.get(url)
        # Anonymous print is a login redirect; the point is that it is never
        # answered from a validator the reading page handed out.
        assert response.status_code in (302, 200)
        assert response.get("Last-Modified") is None


@pytest.mark.django_db
class TestOnlyAServableBodyIsStamped:
    """Django stamps every safe-method response; we narrow that to 200/304.

    A 404 carrying a validator can later be answered 304, which tells a
    crawler its cached miss is still current.
    """

    def test_a_missing_provision_carries_no_validator(self, client: Client, corpus):
        url = reverse(
            "core:provision_permalink_no_division",
            kwargs={
                "code_edition": "OBC_1997",
                "provision_id": "9.9.9.9.",
                "version": 0,
            },
        )
        response = client.get(url)
        assert response.status_code == 404
        assert response.get("Last-Modified") is None

    def test_a_missing_comparison_carries_no_validator(self, client: Client, corpus):
        response = client.get("/compare/", {"a": "nonsense", "b": "nonsense"})
        assert response.status_code == 404
        assert response.get("Last-Modified") is None

    def test_the_304_keeps_its_validator(self, client: Client, corpus):
        # RFC 9110: a 304 carries the validator it matched on.
        first = client.get(PERMALINK)
        second = client.get(PERMALINK, HTTP_IF_MODIFIED_SINCE=first["Last-Modified"])
        assert second.status_code == 304
        assert second["Last-Modified"] == first["Last-Modified"]


@pytest.mark.django_db
class TestTheOtherReadSurfaces:
    def test_regulation_detail_is_conditional(self, client: Client, corpus):
        reg = Regulation.objects.get(reg_id="403/97")
        first = client.get(f"/regulation/{reg.pk}/")
        assert first["Last-Modified"] == _stamp()
        second = client.get(
            f"/regulation/{reg.pk}/", HTTP_IF_MODIFIED_SINCE=first["Last-Modified"]
        )
        assert second.status_code == 304

    def test_edition_contents_is_conditional(self, client: Client, corpus):
        url = reverse("core:edition_contents", kwargs={"code_edition": "OBC_1997"})
        first = client.get(url)
        assert first["Last-Modified"] == _stamp()
        second = client.get(url, HTTP_IF_MODIFIED_SINCE=first["Last-Modified"])
        assert second.status_code == 304

    def test_edition_chain_is_conditional(self, client: Client, corpus):
        url = reverse("core:edition_chain", kwargs={"pk": corpus["edition"].pk})
        first = client.get(url)
        assert first["Last-Modified"] == _stamp()
        second = client.get(url, HTTP_IF_MODIFIED_SINCE=first["Last-Modified"])
        assert second.status_code == 304
