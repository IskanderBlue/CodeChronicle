"""How an account arrived at a provision page.

The reading ledger counts texts held.  What it cannot see is whether a reader
followed a link or composed the URL.  That is a shape, and a shape has no
ceiling problem — no amount of ordinary reading produces 3,000 cold arrivals in
id order.  Item 5 of ``tasks/b-reading-ledger-for-the-website.md``.

The rule these tests defend hardest is the privacy one: **the referrer URL is
never stored.**  A route name says a reader came from a contents page; a URL
says which one, and a referrer from outside can carry somebody else's search.
"""

from datetime import date

import pytest
from django.test import RequestFactory
from django.urls import reverse

from core.events import arrival_context
from core.insights import reading_coverage
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
    User,
)
from core.subtrees import CONTENTS_THRESHOLD

ARTICLE_URL = "/provision/OBC_2006/B/9.8.1./v0/"
PART_URL = "/provision/OBC_2006/B/Part 9/v0/"


@pytest.fixture
def edition(db, settings):
    settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    return CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006, effective_date=date(2006, 12, 31),
    )


def _version(provision, title="Scope", html="<p>Text</p>"):
    return CodeEditionProvisionVersion.objects.create(
        provision=provision, version=0, effective_date=date(2007, 1, 1),
        title=title, html=html,
    )


@pytest.fixture
def article(edition):
    prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id="9.8.1.", level="article", division="B",
    )
    _version(prov, title="Guard Height")
    return prov


@pytest.fixture
def oversized_part(edition):
    """A part with more children than ``CONTENTS_THRESHOLD``, so its page
    answers with a list of links instead of the subtree."""
    root = CodeEditionProvision.objects.create(
        edition=edition, provision_id="Part 9", level="part", division="B",
    )
    _version(root, title="Housing and Small Buildings", html="")
    for n in range(CONTENTS_THRESHOLD + 1):
        child = CodeEditionProvision.objects.create(
            edition=edition, provision_id=f"9.{n + 1}.", level="section",
            division="B", parent=root,
        )
        _version(child, title=f"Section {n + 1}")
    return root


@pytest.fixture
def reader(db):
    return User.objects.create_user(email="reader@example.com")


@pytest.mark.django_db
class TestArrival:
    def _classify(self, referer=None):
        request = RequestFactory().get(ARTICLE_URL)
        if referer is not None:
            request.META["HTTP_REFERER"] = referer
        return arrival_context(request)

    def test_no_referrer_is_cold(self):
        """A reader follows links.  A script composes URLs."""
        assert self._classify() == {"arrival": "cold"}

    def test_another_page_of_ours_names_its_route(self):
        assert self._classify("http://testserver" + reverse("core:search")) == {
            "arrival": "internal",
            "from": "search",
        }

    def test_a_relative_referrer_is_internal(self):
        """No host means same host, which is what a browser sends for a
        same-origin link under a strict referrer policy."""
        assert self._classify(ARTICLE_URL)["arrival"] == "internal"

    def test_somewhere_else_is_external_and_unnamed(self):
        """An outside referrer can carry somebody else's search terms, and no
        version of this signal needs them."""
        assert self._classify("https://example.com/?q=secret+thing") == {
            "arrival": "external"
        }

    def test_an_internal_path_that_no_longer_routes_is_still_internal(self):
        assert self._classify("http://testserver/gone/") == {
            "arrival": "internal",
            "from": "",
        }

    def test_the_url_is_never_stored(self, client, article, reader):
        client.force_login(reader)

        client.get(ARTICLE_URL, HTTP_REFERER="https://example.com/?q=secret+thing")

        context = EngagementEvent.objects.get().context
        assert "secret" not in str(context)
        assert context["arrival"] == "external"


@pytest.mark.django_db
class TestWhatEachSurfaceRecords:
    def test_a_permalink_records_a_provision_view(self, client, article, reader):
        client.force_login(reader)

        client.get(ARTICLE_URL)

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.PROVISION_VERSION_VIEW
        assert event.context["surface"] == "permalink"

    def test_the_exhibit_records_an_export_and_no_view(
        self, client, article, reader
    ):
        """A print request is an export, and counting it twice makes the export
        totals unreadable against the views."""
        client.force_login(reader)

        client.get(ARTICLE_URL.rstrip("/") + "/print/")

        assert (
            EngagementEvent.objects.get().event_type
            == EngagementEvent.EventType.EXPORT
        )


@pytest.mark.django_db
class TestTheReadout:
    def test_cold_arrivals_land_beside_the_coverage(
        self, client, article, oversized_part, reader
    ):
        """One list of rows, so /insights/ reports the arrival shape and the
        coverage from the same accounts."""
        client.force_login(reader)
        client.get(PART_URL)
        client.get(ARTICLE_URL, HTTP_REFERER="http://testserver" + PART_URL)

        row = reading_coverage()[0]

        # The part page was arrived at cold; the article was followed to.
        assert row["cold"] == 1
