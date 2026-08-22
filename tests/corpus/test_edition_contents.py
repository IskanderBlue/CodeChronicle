"""The navigation ladder: division to division, up to the edition, sideways.

Before this, structural navigation climbed one parent at a time and stopped
at a root — so a reader inside Division B could not reach Division C, and no
page listed an edition's own contents.

The property under test is that the ladder does not assume what a root is.
OBC 2006 and 2012 open into three divisions; OBC 1997 has no division at all
and its parts are the roots. Both are correct data, and a rung written for
one shape silently drops the other.
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
from corpus.permalinks import provision_permalink_url


def _url(code_name, division, provision_id, version=0):
    """The permalink, reversed rather than written out."""
    return provision_permalink_url(code_name, division, provision_id, version)


def _version(provision, version=0, title="", **kwargs):
    return CodeEditionProvisionVersion.objects.create(
        provision=provision,
        version=version,
        effective_date=kwargs.pop("effective_date", date(2007, 1, 1)),
        title=title,
        html="<p>text</p>",
        **kwargs,
    )


@pytest.fixture
def corpus(db, settings):
    """Two editions of one code, with deliberately different root shapes."""
    settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")

    # The division-less shape: parts are the roots.
    old = CodeEdition.objects.create(
        code=code, edition_id="1997", year=1997,
        effective_date=date(1998, 4, 6), ineffective_date=date(2006, 12, 31),
    )
    for n in (1, 2, 10):
        part = CodeEditionProvision.objects.create(
            edition=old, provision_id=f"Part {n}", level="part", division="",
        )
        _version(part, title=f"Part {n} heading", effective_date=date(1998, 4, 6))

    # The division shape: A / B / C own the parts.
    new = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006,
        effective_date=date(2006, 12, 31),
    )
    for letter in ("A", "B", "C"):
        div = CodeEditionProvision.objects.create(
            edition=new, provision_id=letter, level="division", division=letter,
        )
        _version(div, title="" if letter == "B" else f"Division {letter}")
        part = CodeEditionProvision.objects.create(
            edition=new, provision_id="Part 1", level="part",
            division=letter, parent=div,
        )
        _version(part, title="Scope")

    # A loose row: no parent, no children, no level. Six of these exist in
    # OBC 2012 Division B and they are not a rung of the structure.
    orphan = CodeEditionProvision.objects.create(
        edition=new, provision_id="Table-1.3.1.2.", level="", division="B",
    )
    _version(orphan, title="A stray table")

    # An edition of the same code that was never loaded. The corpus carries
    # dozens of these; a pager that offered them would list empty rooms.
    CodeEdition.objects.create(
        code=code, edition_id="2006_v07", year=2006, effective_date=date(2007, 6, 1),
    )
    return {"code": code, "old": old, "new": new}


@pytest.mark.django_db
class TestTheEditionContentsPage:
    def test_a_division_edition_lists_its_divisions(self, client, corpus):
        body = client.get("/edition/OBC_2006/").content.decode()
        for letter in ("A", "B", "C"):
            assert f"/provision/OBC_2006/{letter}/{letter}/v0/" in body

    def test_a_division_less_edition_lists_its_parts(self, client, corpus, admin_user):
        """OBC 1997 is outside the free scope here, so sign in first."""
        client.force_login(admin_user)
        admin_user.pro_courtesy = True
        admin_user.save(update_fields=["pro_courtesy"])
        body = client.get("/edition/OBC_1997/").content.decode()
        # Built with the helper, never spelled out: a 1997 provision id holds
        # a space, so the reversed URL is percent-encoded.
        assert _url("OBC_1997", "", "Part 1") in body
        assert _url("OBC_1997", "", "Part 10") in body
        # Natural order, so Part 10 does not sort between Part 1 and Part 2.
        assert body.index(_url("OBC_1997", "", "Part 2")) < body.index(
            _url("OBC_1997", "", "Part 10")
        )

    def test_a_loose_row_is_not_offered_as_a_division(self, client, corpus):
        """No parent, no level: not a rung. Listing it would say this
        edition has four divisions."""
        body = client.get("/edition/OBC_2006/").content.decode()
        assert "Table-1.3.1.2." not in body

    def test_an_unloaded_edition_is_not_offered_sideways(self, client, corpus):
        """The corpus holds a placeholder row per consolidation, all empty."""
        body = client.get("/edition/OBC_2006/").content.decode()
        assert "2006_v07" not in body

    def test_it_links_the_neighbouring_editions(self, client, corpus):
        body = client.get("/edition/OBC_2006/").content.decode()
        assert "/edition/OBC_1997/" in body

    def test_a_root_with_no_title_still_gets_a_row(self, client, corpus):
        """Division B has no title, and needs none — the letter is the name.

        The row is [level][id][title], and the title is guarded, so an empty
        one prints nothing rather than a dangling separator.
        """
        body = client.get("/edition/OBC_2006/").content.decode()
        assert "/provision/OBC_2006/B/B/v0/" in body

    def test_an_unknown_edition_is_a_404(self, client, corpus):
        assert client.get("/edition/OBC_1066/").status_code == 404
        assert client.get("/edition/nonsense/").status_code == 404

    def test_the_gate_holds(self, client, corpus):
        """The shape of an edition is content, so it is gated like content."""
        assert client.get("/edition/OBC_2006/").status_code == 200
        assert client.get("/edition/OBC_1997/").status_code == 403


@pytest.mark.django_db
class TestTheRootPager:
    def test_a_division_pages_to_the_other_divisions(self, client, corpus):
        """The one place the division filter must be dropped: everywhere else
        ``division`` scopes the query, and here crossing it is the point."""
        body = client.get("/provision/OBC_2006/B/B/v0/").content.decode()
        assert "/provision/OBC_2006/A/A/v0/" in body
        assert "/provision/OBC_2006/C/C/v0/" in body

    def test_the_first_root_has_no_previous(self, client, corpus):
        body = client.get("/provision/OBC_2006/A/A/v0/").content.decode()
        assert "/provision/OBC_2006/B/B/v0/" in body
        assert "/provision/OBC_2006/C/C/v0/" not in body

    def test_a_root_part_pages_to_the_other_parts(self, client, corpus, admin_user):
        """The same rung, in an edition whose roots are parts."""
        admin_user.pro_courtesy = True
        admin_user.save(update_fields=["pro_courtesy"])
        client.force_login(admin_user)
        body = client.get(_url("OBC_1997", "", "Part 2")).content.decode()
        assert _url("OBC_1997", "", "Part 1") in body
        assert _url("OBC_1997", "", "Part 10") in body

    def test_a_loose_row_is_not_a_sibling_of_a_division(self, client, corpus):
        body = client.get("/provision/OBC_2006/C/C/v0/").content.decode()
        assert "Table-1.3.1.2." not in body


@pytest.mark.django_db
class TestTheClimbToTheEdition:
    def test_every_provision_page_offers_the_edition(self, client, corpus):
        """Reachable from any depth, not only from a root — "Within" climbs
        one parent at a time and a reader deep in a subtree should not have
        to walk back up it."""
        for url in (
            "/provision/OBC_2006/B/B/v0/",
            "/provision/OBC_2006/B/Part 1/v0/",
        ):
            assert "/edition/OBC_2006/" in client.get(url).content.decode()

    def test_the_exhibit_has_no_ladder(self, client, corpus):
        """There is nowhere to click on paper."""
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")
        body = client.get("/provision/OBC_2006/B/B/v0/print/").content.decode()
        assert "/edition/OBC_2006/" not in body
