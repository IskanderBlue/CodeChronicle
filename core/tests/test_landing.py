"""The public landing page (``core.views.landing``), at ``/`` and ``/about/``.

Three things can break this page, and the tests are about those three:

1. **The routing split.**  ``/`` used to be the search page.  It is now the
   front door, and a signed-in reader is sent straight on to ``/search/``;
   ``/about/`` is the same page with that redirect off, so the explanation
   stays reachable for everybody.  Getting either half wrong is invisible in
   development (both render) and obvious in production.
2. **Template rendering.**  Django tokenises tags everywhere, so a leaked tag
   ships as literal text on the one page every visitor sees first.
3. **The figures.**  Every quantity on the page is counted from the same
   tables the search reads.  The moment one becomes a typed-in constant, the
   page can claim coverage the product does not have — which is the single
   worst failure available to a landing page for a citation tool.
"""

import re
from datetime import date

import pytest
from django.urls import reverse

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    Regulation,
    User,
)

# The module, not the view: ``core.views.landing`` resolves to the re-exported
# view function via ``core/views/__init__.py``.
from core.views.landing import SPECIMEN, _free_tier_examples


@pytest.fixture
def loaded_edition(db) -> CodeEdition:
    """One verified edition with two amending regulations.

    Mirrors the publish gate the page reports: ``verified`` plus at least one
    regulation.  The counts asserted below are derived from this fixture, not
    from whatever happens to be in a developer's database.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code,
        edition_id="2006",
        year=2006,
        effective_date=date(2006, 12, 31),
        ineffective_date=date(2014, 1, 1),
        amendment_chain_complete=True,
        verified=True,
    )
    base = Regulation.objects.create(
        edition=edition, reg_id="350/06", role=Regulation.Role.BASE,
        effective_date=date(2006, 12, 31),
        source_kind=Regulation.SourceKind.ELAWS,
        source_url="https://www.ontario.ca/laws/regulation/060350",
    )
    # One regulation per publication source, so row 05's "one chip per source"
    # wiring is exercised.  In the real corpus the Gazette scans belong to the
    # pre-2003 era, not to a 2007 regulation; the fixture pairs them here only
    # because it models a single edition.
    for reg_id, day, kind, url in (
        ("315/07", date(2007, 7, 1), Regulation.SourceKind.ARCHIVE_GAZETTE,
         "https://archive.org/details/ontarioregulations"),
        ("151/09", date(2009, 4, 1), Regulation.SourceKind.ELAWS, ""),
    ):
        Regulation.objects.create(
            edition=edition, reg_id=reg_id, role=Regulation.Role.AMENDMENT,
            effective_date=day, amends=base, source_kind=kind, source_url=url,
        )
    return edition


@pytest.fixture
def specimen_provision(loaded_edition: CodeEdition) -> CodeEditionProvision:
    """The provision section III's specimens are rendered from.

    Deliberately thin — three versions and one citation — because the point is
    not to reproduce the corpus but to prove that the row renders the shipping
    partial against whatever record is there.  ``SPECIMEN`` names the identity,
    so a change of exemplar in the view fails here rather than silently leaving
    the specimens blank in production.
    """
    edition_id, division, provision_id, _version = SPECIMEN
    assert loaded_edition.edition_id == edition_id
    provision = CodeEditionProvision.objects.create(
        edition=loaded_edition,
        provision_id=provision_id,
        division=division,
        level="article",
    )
    for number, day in enumerate(
        (date(2006, 12, 31), date(2007, 4, 2), date(2010, 1, 1))
    ):
        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=number,
            effective_date=day,
            title="Application of Part 9",
            html='<p class="subsection-e">(1) Subject to Article 1.3.1.2., Part 9 '
                 "applies.</p>\n<p class=\"clause-e\">(a) of three or fewer storeys,</p>",
        )
    return provision


@pytest.mark.django_db
class TestLandingRouting:
    def test_root_renders_the_landing_page_for_a_visitor(self, client) -> None:
        response = client.get(reverse("core:landing"))
        assert response.status_code == 200
        assert "landing.html" in [t.name for t in response.templates]

    def test_root_sends_a_signed_in_reader_to_the_search_page(self, client) -> None:
        """They have already been sold; a marketing page between them and the
        tool is friction on every visit."""
        user = User.objects.create_user(email="reader@example.com", password="x")
        client.force_login(user)
        response = client.get(reverse("core:landing"))
        assert response.status_code == 302
        assert response.url == reverse("core:search")

    def test_about_never_redirects(self, client) -> None:
        """``/about/`` is the same view without the redirect, so the footer's
        link works for a signed-in reader too."""
        user = User.objects.create_user(email="reader2@example.com", password="x")
        client.force_login(user)
        response = client.get(reverse("core:about"))
        assert response.status_code == 200
        assert "landing.html" in [t.name for t in response.templates]

    def test_search_page_still_serves_the_search_template(self, client) -> None:
        response = client.get(reverse("core:search"))
        assert response.status_code == 200
        assert "search.html" in [t.name for t in response.templates]

    def test_try_links_carry_their_date(self, client, loaded_edition) -> None:
        """The AS-OF picker is the date the search runs at, so a link with only
        ``?q=`` answers a 1999 question with whatever the default date returns.
        Every offered example must carry ``?d=``."""
        body = client.get(reverse("core:landing")).content.decode()
        offered = re.findall(r'href="/search/\?q=([^"&]+)(&amp;d=([\d-]+))?"', body)
        assert offered, "no try-this examples rendered"
        for _query, dated, _day in offered:
            assert dated, "a try-this link is missing its ?d= date"

    def test_try_links_stay_inside_the_free_tier(self, client, loaded_edition) -> None:
        """An anonymous visitor gets one search a day. Spending it on a locked
        edition is the worst available first impression."""
        for example in _free_tier_examples():
            when = date.fromisoformat(example["date"])
            assert loaded_edition.effective_date <= when
            assert loaded_edition.ineffective_date is None or when < loaded_edition.ineffective_date

    def test_search_page_seeds_the_date_from_the_url(self, client) -> None:
        body = client.get(f"{reverse('core:search')}?q=guards&d=2010-06-01").content.decode()
        assert re.search(r'name="date"[^>]*value="2010-06-01"', body)

    def test_search_page_ignores_a_malformed_date(self, client) -> None:
        """A hand-edited URL must not put junk in the field."""
        body = client.get(f"{reverse('core:search')}?q=guards&d=nonsense").content.decode()
        assert 'value="nonsense"' not in body

    def test_a_seeded_link_runs_its_own_search(self, client) -> None:
        """``?q=`` lands on results, not on a filled-in box.

        Every link we hand somebody — the front page, a history card, a message
        we send — relies on this.  The block is found by its own attribute
        rather than by the ``htmx.trigger`` call inside it: the example-chip
        handler makes the identical call and is always on the page, so a test
        matching the call would pass with the auto-run deleted.
        """
        body = client.get(f"{reverse('core:search')}?q=guards&d=2010-06-01").content.decode()
        assert "data-autorun-search" in body
        # The search it runs is the one in the link.  A block that fires
        # against an empty box runs a search for nothing.
        assert 'value="guards"' in body

    def test_no_template_syntax_leaks_into_the_search_page(self, client) -> None:
        """The search page carries comments inside HTML tags and inside script
        blocks.  Django scans for its own syntax everywhere, so a comment that
        the tokenizer does not recognise prints itself into the page."""
        body = client.get(reverse("core:search")).content.decode()
        for leak in ("{%", "{{", "{#"):
            assert leak not in body, f"unrendered template syntax {leak!r} in page body"

    def test_an_unseeded_search_page_runs_nothing(self, client) -> None:
        """A reader who opens /search/ themselves has asked for nothing yet."""
        body = client.get(reverse("core:search")).content.decode()
        assert "data-autorun-search" not in body

    def test_hero_query_hands_off_to_the_search_page(self, client) -> None:
        """The hero field is a real GET to ``/search/?q=``, which the search
        page already auto-runs — a visitor arrives holding their own
        question."""
        body = client.get(reverse("core:landing")).content.decode()
        assert f'action="{reverse("core:search")}"' in body
        assert 'name="q"' in body


@pytest.mark.django_db
class TestLandingRendering:
    def test_no_template_syntax_leaks_into_the_page(self, client) -> None:
        body = client.get(reverse("core:landing")).content.decode()
        for leak in ("{%", "{{", "{#"):
            assert leak not in body, f"unrendered template syntax {leak!r} in page body"

    def test_renders_with_an_empty_corpus(self, client) -> None:
        """No editions loaded must not mean a broken page or, worse, a page
        still asserting coverage.  The band and the table simply do not
        render."""
        response = client.get(reverse("core:landing"))
        assert response.status_code == 200
        assert response.context["band"] == []
        assert response.context["edition_count"] == 0

    def test_names_every_difference_class_it_claims_to(self, client) -> None:
        """The section's argument is that the residue after the two
        reconstructions are diffed is a *closed, named* vocabulary.  A missing
        chip weakens it silently — including on an empty corpus, where the
        examples cannot resolve but the vocabulary still stands."""
        body = client.get(reverse("core:landing")).content.decode()
        for name in ("editorial-drift", "elaws-advance-notice", "revoked-before-effect"):
            assert name in body, f"missing difference class {name!r}"

    def test_an_unresolvable_example_renders_no_link(self, client) -> None:
        """A dead permalink on the front page is worse than no permalink."""
        classes = client.get(reverse("core:landing")).context["difference_classes"]
        assert classes, "the difference-class vocabulary vanished on an empty corpus"
        assert all(entry["url"] == "" for entry in classes)


@pytest.mark.django_db
class TestSectionThreeSpecimens:
    """Section III shows the shipping components, not drawings of them.

    Row 01 renders ``_search_form.html`` — the same form the search page renders.
    Rows 02, 03 and 04 render ``_provenance_rail.html``, ``_provenance_band.html``
    and ``core.cross_refs`` output against one real provision. These tests are
    what stops a row quietly reverting to markup written on this page.
    """

    def test_the_query_specimen_is_the_shipping_search_form(self, client) -> None:
        """Row 01 and the hero both render the real form. They used to be two
        hand-drawn miniatures, and both had lost its Jurisdiction cell — so the
        front page advertised a control the product does not have."""
        rendered = [t.name for t in client.get(reverse("core:landing")).templates]
        assert rendered.count("partials/_search_form.html") == 2

    def test_renders_without_the_specimen_provision(self, client) -> None:
        """A landing page must render before the data does."""
        response = client.get(reverse("core:landing"))
        assert response.status_code == 200
        assert response.context["specimen"] == {}

    def test_the_chain_specimen_is_the_shipping_partial(
        self, client, specimen_provision
    ) -> None:
        response = client.get(reverse("core:landing"))
        rendered = [t.name for t in response.templates]
        assert "partials/_provenance_rail.html" in rendered, (
            "row 02 is drawing its own amendment chain again"
        )

    def test_the_rail_specimen_is_the_whole_in_force_band(
        self, client, specimen_provision
    ) -> None:
        """The rail never appears alone in the product — it is the band's body,
        and the band paints the fill the rail's marks are drawn against. Showing
        the rail by itself put it on the wrong colour and made it the wrong
        object."""
        rendered = [
            t.name for t in client.get(reverse("core:landing")).templates
        ]
        assert "partials/_provenance_band.html" in rendered
        assert "partials/_attestation_rail.html" in rendered

    def test_the_specimen_names_its_own_provision(
        self, client, specimen_provision
    ) -> None:
        """The caption and the link come from the record, so they cannot name a
        provision the specimen is not actually showing."""
        specimen = client.get(reverse("core:landing")).context["specimen"]
        assert specimen["cite"] == "1.1.2.4."
        assert specimen["title"] == "Application of Part 9"
        assert specimen["url"] == "/provision/OBC_2006/A/1.1.2.4./v2/"

    def test_the_citation_specimen_is_a_single_whole_block(
        self, client, specimen_provision
    ) -> None:
        """The excerpt is cut at the first closing paragraph, never mid-tag."""
        specimen = client.get(reverse("core:landing")).context["specimen"]
        assert specimen["lead_html"].endswith("</p>")
        assert specimen["lead_html"].count("</p>") == 1

    def test_source_chips_are_real_regulations(self, client, specimen_provision) -> None:
        """One chip per publication source actually in use, with its real URL —
        a typed pair would go on advertising a source after it stopped being
        used."""
        chips = client.get(reverse("core:landing")).context["source_chips"]
        assert chips, "no source chips resolved"
        for regulation in chips:
            assert regulation.source_url
        # One per kind, never two of the same: the pairing is the claim.
        assert len({r.source_kind for r in chips}) == len(chips)


@pytest.mark.django_db
class TestLandingFigures:
    def test_counts_come_from_the_database(self, client, loaded_edition) -> None:
        context = client.get(reverse("core:landing")).context
        assert context["edition_count"] == 1
        # The base regulation is not an amendment and must not be counted.
        assert context["amending_regs"] == 2
        assert list(context["editions"]) == [loaded_edition]

    def test_unverified_editions_are_not_advertised(self, client, loaded_edition) -> None:
        """``verified`` is the publish gate: an edition whose discrepancies are
        still under review is not something the front page may count."""
        loaded_edition.verified = False
        loaded_edition.save(update_fields=["verified"])
        context = client.get(reverse("core:landing")).context
        assert context["edition_count"] == 0
        assert context["amending_regs"] == 0

    def test_until_shows_the_inclusive_last_day(self, client, loaded_edition) -> None:
        """``ineffective_date`` is exclusive. Printed raw it shows the successor
        edition's first day, so the rows read as overlapping."""
        editions = client.get(reverse("core:landing")).context["editions"]
        assert editions[0].last_day == date(2013, 12, 31)
        assert editions[0].ineffective_date == date(2014, 1, 1)

    def test_every_class_names_a_specific_example_provision(self, client) -> None:
        """Each class must at least name the provision it was closed on, even
        when that edition is not loaded and the link cannot be built."""
        classes = client.get(reverse("core:landing")).context["difference_classes"]
        for entry in classes:
            assert entry["cite"], f"{entry['name']} names no example provision"
            assert entry["edition_label"]

    def test_a_class_absent_from_the_free_tier_says_which_editions_it_arose_in(
        self, client
    ) -> None:
        """Eight of the eleven classes never arose in OBC 2006, so their worked
        examples have to come from 1997 or 2012 and land on the locked teaser.
        Without the note that reads as a choice — as though we could have shown
        a free one and didn't."""
        classes = client.get(reverse("core:landing")).context["difference_classes"]
        by_name = {entry["name"]: entry for entry in classes}

        ocr = by_name["non-keyword-table-ocr"]
        assert ocr["absent_from_free_tier"] is True
        assert ocr["occurs_in"] == ("1997",)

        drift = by_name["editorial-drift"]
        assert drift["absent_from_free_tier"] is False

    def test_every_free_tier_class_uses_a_free_tier_example(self, client) -> None:
        """The converse, and the rule the exemplars are chosen by: where OBC 2006
        raised the class, the example must be the OBC 2006 one."""
        classes = client.get(reverse("core:landing")).context["difference_classes"]
        for entry in classes:
            if not entry["absent_from_free_tier"]:
                assert entry["edition_label"] == "OBC 2006", entry["name"]

    def test_the_page_states_no_parity_counts(self, client) -> None:
        """``occurs_in`` is transcribed from CCM's reports, not read from the
        database, so it may name editions and must never carry a quantity — the
        page's whole discipline is that its numbers are re-derivable."""
        for entry in client.get(reverse("core:landing")).context["difference_classes"]:
            for edition_id in entry["occurs_in"]:
                assert edition_id in {"1997", "2006", "2012"}

    def test_band_spans_the_whole_covered_range(self, client, loaded_edition) -> None:
        """The band is laid out as percentages of the corpus span, so a single
        edition fills it end to end."""
        band = client.get(reverse("core:landing")).context["band"]
        assert len(band) == 1
        assert band[0]["left"] == 0
        assert round(band[0]["left"] + band[0]["width"]) == 100
