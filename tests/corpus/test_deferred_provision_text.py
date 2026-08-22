"""How text leaves a permalink page, one provision at a time.

A permalink names one provision and used to hand over up to forty texts.  The
reading ledger can only be as granular as delivery is, so a signed-in reader
now gets the matched provision's text, the *headings* of everything under it,
and one request per body.  Item 3 of
``tasks/complete/reading-ledger-for-the-website.md``.

Two properties every test here defends.  **Anonymous rendering is unchanged**,
because that is what crawlers see and what the cost work was measured against.
**The deferred body and the inline body are the same text**, because there are
now two code paths to one guarantee — the same guarantee the print branch
exists to make.
"""

from datetime import date

import pytest
from django.urls import reverse

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionFetch,
    User,
)

PARENT_TEXT = "the parent's own words"
CHILD_TEXT = "a guard shall be not less than"
OTHER_TEXT = "every exit shall be maintained"

PARENT_URL = "/provision/OBC_2006/B/9.8./v0/"
PRINT_URL = "/provision/OBC_2006/B/9.8./v0/print/"


def _version(provision, *, title, html, version=0):
    return CodeEditionProvisionVersion.objects.create(
        provision=provision, version=version, effective_date=date(2007, 1, 1),
        title=title, html=html,
    )


@pytest.fixture
def edition(db, settings):
    settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    return CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006, effective_date=date(2006, 12, 31),
    )


@pytest.fixture
def subtree(edition):
    """A subsection with two articles under it — three texts on one page."""
    parent = CodeEditionProvision.objects.create(
        edition=edition, provision_id="9.8.", level="subsection", division="B",
    )
    _version(parent, title="Stairs, Ramps and Guards", html=f"<p>{PARENT_TEXT}</p>")
    first = CodeEditionProvision.objects.create(
        edition=edition, provision_id="9.8.1.", level="article", division="B",
        parent=parent,
    )
    _version(first, title="Guard Height", html=f"<p>{CHILD_TEXT}</p>")
    second = CodeEditionProvision.objects.create(
        edition=edition, provision_id="9.8.2.", level="article", division="B",
        parent=parent,
    )
    _version(second, title="Exits", html=f"<p>{OTHER_TEXT}</p>")
    return {"parent": parent, "first": first, "second": second}


@pytest.fixture
def reader(db):
    return User.objects.create_user(email="reader@example.com")


def _text_url(provision_id="9.8.1.", version=0, division="B"):
    return reverse(
        "web:provision_text", args=["OBC_2006", division, provision_id, version]
    )


@pytest.mark.django_db
class TestAnonymousRenderingIsUnchanged:
    """Crawlers are nearly all the traffic, the edge stores their copy, and
    ``CONTENTS_THRESHOLD`` was measured against this page.  Deferring here
    would multiply the requests and record none of them."""

    def test_every_descendant_body_is_still_inline(self, client, subtree):
        body = client.get(PARENT_URL).content.decode()

        assert PARENT_TEXT in body
        assert CHILD_TEXT in body
        assert OTHER_TEXT in body

    def test_no_fetch_url_is_emitted(self, client, subtree):
        assert "/text/" not in client.get(PARENT_URL).content.decode()


@pytest.mark.django_db
class TestASignedInReaderGetsHeadingsAndFetchesBodies:
    def test_the_descendant_bodies_are_withheld(self, client, subtree, reader):
        client.force_login(reader)

        body = client.get(PARENT_URL).content.decode()

        assert CHILD_TEXT not in body
        assert OTHER_TEXT not in body

    def test_the_headings_are_not(self, client, subtree, reader):
        """The reader must still see what is under this provision.  An id and
        a title are identity, which ``/api/search`` gives away freely and the
        ledger declines to count."""
        client.force_login(reader)

        body = client.get(PARENT_URL).content.decode()

        assert "9.8.1." in body
        assert "Guard Height" in body

    def test_each_body_has_its_own_url(self, client, subtree, reader):
        client.force_login(reader)

        body = client.get(PARENT_URL).content.decode()

        assert _text_url("9.8.1.") in body
        assert _text_url("9.8.2.") in body

    def test_a_row_with_no_version_in_force_is_rendered_here(
        self, client, subtree, edition, reader
    ):
        """A later amendment adds a provision, so at this page's anchor date it
        has no version — and therefore no version number a fragment URL could
        name.  It has no body to fetch either, so it renders its one line
        inline and costs no request."""
        added_later = CodeEditionProvision.objects.create(
            edition=edition, provision_id="9.8.3.", level="article", division="B",
            parent=subtree["parent"],
        )
        CodeEditionProvisionVersion.objects.create(
            provision=added_later, version=0, effective_date=date(2012, 1, 1),
            title="Vapour Barriers", html="<p>added by the 2012 amendment</p>",
        )
        client.force_login(reader)

        body = client.get(PARENT_URL).content.decode()

        assert "Not in force at this date." in body
        assert "9.8.3./v0/text/" not in body

    def test_the_provision_the_url_names_is_never_deferred(
        self, client, subtree, reader
    ):
        """A page that answers a request for one provision with a spinner is
        not a page."""
        client.force_login(reader)

        assert PARENT_TEXT in client.get(PARENT_URL).content.decode()


@pytest.mark.django_db
class TestTheExhibitNeverDefers:
    """A printed page has no later.  The print branch also renders the whole
    subtree with no ``CONTENTS_THRESHOLD``, which makes it the cheapest way to
    take text out of the product — a hole here reads as a clean account."""

    def test_the_print_branch_carries_every_body(self, client, subtree, reader):
        client.force_login(reader)

        body = client.get(PRINT_URL).content.decode()

        assert PARENT_TEXT in body
        assert CHILD_TEXT in body
        assert OTHER_TEXT in body

    def test_the_page_and_the_exhibit_name_the_same_provisions(
        self, client, subtree, reader
    ):
        """Parity.  The reading page lists what it defers, so both surfaces
        must still describe one subtree — there is no longer one code path to
        guarantee it."""
        client.force_login(reader)

        page = client.get(PARENT_URL).content.decode()
        printed = client.get(PRINT_URL).content.decode()

        for provision_id in ("9.8.", "9.8.1.", "9.8.2."):
            assert provision_id in page
            assert provision_id in printed


@pytest.mark.django_db
class TestTheFragment:
    def test_it_answers_the_same_text_the_inline_render_carries(
        self, client, subtree, reader
    ):
        client.force_login(reader)

        assert CHILD_TEXT in client.get(_text_url("9.8.1.")).content.decode()

    def test_an_anonymous_reader_is_refused(self, client, subtree):
        """Nothing anonymous links here — an anonymous permalink renders its
        whole subtree inline — so answering would open a second, unrecorded
        way to sweep the corpus for no feature at all.  403 rather than a
        login redirect, because htmx swaps nothing on a non-2xx."""
        assert client.get(_text_url("9.8.1.")).status_code == 403

    def test_the_content_gate_still_runs(self, client, subtree, reader, settings):
        """A fragment URL changes how an account asks, never what it may
        read."""
        settings.FREE_TIER_CODE_NAMES = ["OBC_2012"]
        client.force_login(reader)

        response = client.get(_text_url("9.8.1."))

        assert response.status_code == 403
        assert CHILD_TEXT not in response.content.decode()

    def test_a_version_that_does_not_exist_is_a_404(self, client, subtree, reader):
        client.force_login(reader)

        assert client.get(_text_url("9.8.1.", version=7)).status_code == 404


@pytest.mark.django_db
class TestTheLedgerFollowsDelivery:
    def test_the_page_records_only_what_it_rendered(self, client, subtree, reader):
        client.force_login(reader)

        client.get(PARENT_URL)

        held = set(ProvisionFetch.objects.values_list("provision_id", flat=True))
        assert held == {"9.8."}

    def test_a_fetched_body_adds_its_own_row(self, client, subtree, reader):
        client.force_login(reader)

        client.get(PARENT_URL)
        client.get(_text_url("9.8.1."))

        held = set(ProvisionFetch.objects.values_list("provision_id", flat=True))
        assert held == {"9.8.", "9.8.1."}

    def test_a_refused_fragment_records_nothing(
        self, client, subtree, reader, settings
    ):
        """A refusal delivered nothing, so it writes nothing — the same rule
        the API side follows."""
        settings.FREE_TIER_CODE_NAMES = ["OBC_2012"]
        client.force_login(reader)

        client.get(_text_url("9.8.1."))

        assert ProvisionFetch.objects.count() == 0

    def test_the_exhibit_records_the_whole_subtree(self, client, subtree, reader):
        client.force_login(reader)

        client.get(PRINT_URL)

        held = set(ProvisionFetch.objects.values_list("provision_id", flat=True))
        assert held == {"9.8.", "9.8.1.", "9.8.2."}
