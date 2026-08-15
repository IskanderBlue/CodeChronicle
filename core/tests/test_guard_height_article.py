"""The guard-height article (``core:guard_height``).

The article is one question and then every change to its answer.  The oldest
text renders in full; each amendment after it renders as a redline through the
shipping comparison panes.  That buys it one risk: the hand-written analysis
says "800 mm", "the number moved", "the landing gets two answers", and a corpus
reload could leave that prose describing text the page no longer shows.

**These tests pin behaviour, never content.**  A test earns its place by
catching an accident.  Prose is changed on purpose, its correctness is a
judgement, and a red test on a reworded sentence reports nothing but an edit.
Several tests here used to assert phrases from the article; between them they
broke six times on rewordings that left every claim intact, and found no
defect.  They are gone.

So: assert what the *view* does — the status, the wiring, which versions
render, the redlines, the gate, the date the call to action searches — and let
the author write.  Two exceptions, both obligations rather than judgements:
the Compendium attribution string, and the quotation being reproduced in full.
Accurate reproduction is a licence condition, not a stylistic preference.

**What these tests can and cannot pin.**  They build their own corpus, so they
prove the *view* surfaces the facts the prose depends on — the opening text,
the five transitions, the moved provision number, the 800 mm sentence in 1997
and its absence in 2006, the scan, the locked links.  They cannot prove the
shipping corpus still says those things, because a fixture asserting its own
data is circular.  ``verify_guard_height_article`` does that half, against a
real database — and that is the right home for a claim about the code, because
it checks the corpus rather than the page.
"""

import json
import re
from datetime import date

import pytest
from django.urls import reverse

from core.management.commands.verify_guard_height_article import allows_800_mm
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    Regulation,
)
from core.views.guard_height import MODIFIED, OPENING, PUBLISHED, TRANSITIONS

#: The 1997 sentences the article's opening turns on.
#:
#: Every edition carries the exterior-guard sentence as well, and the fixture
#: keeps it on purpose: it reads "not more than 1 800 mm above the finished
#: ground level", so a naive ``"800 mm" in html`` check finds the 1997
#: allowance in every edition and reports that it never went away.  The trap
#: stays here so a check that falls into it fails in the suite rather than in
#: production.
TEXT_1997 = (
    "<p>(2) Guards for porches, decks, landings and balconies are permitted to be a "
    "minimum of 900 mm high where the walking surface is not more than 1 800 mm above "
    "the finished ground level.</p>"
    "<p>(4) Guards for stairs within dwelling units shall be not less than 800 mm "
    "measured vertically above a line drawn through the outside edges of stair "
    "nosings, and not less than 900 mm above landings.</p>"
)
#: Its replacement.  The article's first claim is that the 800 mm allowance is
#: gone and the flight now reads 900 mm.
TEXT_2006_V0 = (
    "<p>(2) All guards within dwelling units shall be not less than 900 mm high.</p>"
    "<p>(3) Exterior guards serving not more than one dwelling unit shall be not less "
    "than 900 mm high where the walking surface served by the guard is not more than "
    "1 800 mm above the finished ground level.</p>"
    "<p>(4) Guards for flights of steps, except in required exit stairs, shall be not "
    "less than 900 mm high.</p>"
    "<p>(5) The height of guards for flights of steps shall be measured vertically "
    "from a line drawn through the leading edge of the treads served by the guard.</p>"
)
#: 2010: the measurement sentence gains a starting point, and nothing else moves.
TEXT_2006_V1 = TEXT_2006_V0.replace(
    "measured vertically from a line",
    "measured vertically from the top of the guard to a line",
)
#: 2014: sentence (5) arrives, and the landing goes to 1 070 mm from here.
#:
#: Sentence (1)'s except-list grows with it.  That list is what the article's
#: argument turns on — it is why sentence (2) can lower anything, and its
#: absence between (2) and (5) is why both of those apply at once — so the
#: fixture carries the real one rather than the 2006 wording.
TEXT_2012_V0 = TEXT_2006_V1.replace(
    "Except as provided in Sentences (2) to (4)",
    "Except as provided in Sentences (2) to (6)",
) + (
    "<p>(5) Except as provided in Sentence (6), the height of guards shall be not "
    "less than, (a) 920 mm for required exit stairs, and (b) 1 070 mm around "
    "landings.</p>"
)
#: 2017: the exterior sentence is reworded, and only that.
TEXT_2012_V1 = TEXT_2012_V0.replace(
    "Exterior guards serving not more than one dwelling unit",
    "Exterior guards serving a house or an individual dwelling unit",
)
#: 2022: sentence (5) is revoked, and spiral stairs leave sentence (2).
TEXT_2012_V2 = TEXT_2012_V1.replace(
    "Except as provided in Sentences (2) to (6)",
    "Except as provided in Sentences (2), (3), (4) and (6)",
).replace(
    "(2) All guards within dwelling units shall",
    "(2) All guards within dwelling units, other than guards serving spiral stairs, shall",
).replace(
    "<p>(5) Except as provided in Sentence (6), the height of guards shall be not "
    "less than, (a) 920 mm for required exit stairs, and (b) 1 070 mm around "
    "landings.</p>",
    "<p>(5) Reserved</p>",
)

#: (edition, division, provision_id, version, effective, ineffective, html)
ROWS = (
    ("1997", "", "9.8.8.2.", 0, date(1998, 4, 6), date(2006, 12, 31), TEXT_1997),
    ("2006", "B", "9.8.8.3.", 0, date(2006, 12, 31), date(2010, 1, 1), TEXT_2006_V0),
    ("2006", "B", "9.8.8.3.", 1, date(2010, 1, 1), date(2014, 1, 1), TEXT_2006_V1),
    ("2012", "B", "9.8.8.3.", 0, date(2014, 1, 1), date(2017, 7, 1), TEXT_2012_V0),
    ("2012", "B", "9.8.8.3.", 1, date(2017, 7, 1), date(2022, 1, 1), TEXT_2012_V1),
    ("2012", "B", "9.8.8.3.", 2, date(2022, 1, 1), date(2025, 1, 1), TEXT_2012_V2),
)


@pytest.fixture
def corpus(db) -> None:
    """Three editions and the six guard-height versions, in the real shape.

    Mirrors the production corpus closely enough to exercise every claim the
    article makes: OBC 1997 carries no division letter and is scanned paper,
    the later two are Division B and HTML, the provision number moves between
    the first and the second, and each amendment changes what the section
    beside it says it changed.  It also carries Part 3's exit-stair guard,
    which is not guard height in a house and is on the page as the evidence
    for what sentence (5) means.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    windows = {
        "1997": (date(1998, 4, 6), date(2006, 12, 31)),
        "2006": (date(2006, 12, 31), date(2014, 1, 1)),
        "2012": (date(2014, 1, 1), date(2025, 1, 1)),
    }
    editions = {}
    for edition_id, (start, end) in windows.items():
        edition = CodeEdition.objects.create(
            code=code,
            edition_id=edition_id,
            year=int(edition_id),
            effective_date=start,
            ineffective_date=end,
            amendment_chain_complete=True,
            verified=True,
        )
        Regulation.objects.create(
            edition=edition,
            reg_id=f"1/{edition_id[-2:]}",
            role=Regulation.Role.BASE,
            effective_date=start,
        )
        editions[edition_id] = edition

    provisions: dict[tuple[str, str], CodeEditionProvision] = {}
    for edition_id, division, provision_id, number, start, end, html in ROWS:
        key = (edition_id, provision_id)
        if key not in provisions:
            provisions[key] = CodeEditionProvision.objects.create(
                edition=editions[edition_id],
                provision_id=provision_id,
                division=division,
                level="article",
                version_count=0,
            )
        provision = provisions[key]
        # OBC 1997 is scanned paper: the page image is the record, and the
        # article promises to show it.  The later editions are e-Laws HTML.
        page_images = (
            [{"image": "documents/ont_reg_1997_v2/261.webp",
              "bboxes": [{"x": 0.028, "y": 0.24992, "w": 0.452, "h": 0.36416}]}]
            if edition_id == "1997"
            else []
        )
        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=number,
            title="Height of Guards",
            html=html,
            page_images=page_images,
            effective_date=start,
            ineffective_date=end,
        )
        provision.version_count += 1
        provision.save(update_fields=["version_count"])


@pytest.fixture
def production_scope(settings):
    """The real free tier.  ``conftest`` widens it so unrelated tests keep
    testing their own subject; the gate tests here need the narrow one."""
    settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]


def _page(client):
    response = client.get(reverse("core:guard_height"))
    assert response.status_code == 200
    return response


class TestTheAllowanceCheck:
    """``allows_800_mm`` decides the article's opening claim, so it gets its
    own tests.  A plain substring search reported the allowance in every
    edition, because they all mention a 1 800 mm drop."""

    def test_it_finds_the_1997_allowance(self) -> None:
        assert allows_800_mm(TEXT_1997)

    def test_it_is_not_fooled_by_an_1800_mm_drop(self) -> None:
        assert not allows_800_mm(TEXT_2006_V0)

    def test_it_is_not_fooled_by_tags_or_line_breaks(self) -> None:
        assert allows_800_mm("<p>shall be not\n  less than <b>800</b> mm high</p>")

    def test_empty_text_allows_nothing(self) -> None:
        assert not allows_800_mm(None)
        assert not allows_800_mm("")


@pytest.mark.django_db
class TestTheArticleRenders:
    def test_it_is_public(self, client) -> None:
        assert client.get(reverse("core:guard_height")).status_code == 200

    def test_it_renders_without_a_corpus(self, client) -> None:
        """A fresh development database has no corpus.  The prose must still
        render, because a front-of-house page that 500s is harder to work on
        than one missing its specimens."""
        response = _page(client)
        assert response.context["opening"] is None
        assert response.context["transitions"] == {}

    def test_it_uses_its_own_template(self, client) -> None:
        response = _page(client)
        assert "guard_height.html" in [t.name for t in response.templates]

    def test_it_carries_its_own_title_and_description(self, client) -> None:
        """Set in the view, not in a block, so the forwarded link and the page
        agree.  ``_social_meta.html`` reads these same two names."""
        response = _page(client)
        body = response.content.decode()
        assert response.context["meta_title"] in body
        assert response.context["meta_description"] in body
        assert 'property="og:title"' in body

    def test_the_opening_table_splits_the_flight_from_the_landing(self, client) -> None:
        """The first answer the page gives used to be one number for a stair.
        The code splits the stair: OBC 1997 sets 800 mm on the flight and
        900 mm above landings in one sentence, and from 2014 to 2022 the
        landing stood 170 mm above the flight beside it.  A single-number
        opening is wrong on both counts.

        The 2014 landing cell states one figure, 1 070 mm.  Two earlier drafts
        hedged it — "900 or 1 070 mm", then "900 mm, 1 070 on one reading" —
        both of which came from reading sentences (2) and (5) as contradicting
        each other.  They do not: they are minimums, both apply, and the higher
        one is the requirement."""
        body = _page(client).content.decode()
        assert ">Flight<" in body
        assert ">Landing<" in body
        # And a third column, because a spiral stair diverges from both from
        # 1 January 2022: O. Reg. 88/19 takes it out of sentence (2) on the
        # same day it stops the code counting a spiral stair as flights, so
        # nothing gives its guard the 900 mm and sentence (1) governs.
        assert ">Spiral stair<" in body

    def test_it_quotes_the_2024_article_in_full(self, client) -> None:
        """The quotation is reproduced under the Compendium licence, and
        accurate reproduction is a condition of it.  So this is not a content
        test: it guards an obligation, the way the attribution test below
        does.  A truncated quotation breaches the licence; a reworded sentence
        elsewhere on the page does not, and no test here should care."""
        body = _page(client).content.decode()
        for phrase in (
            "All guards within dwelling units or within houses with a secondary suite",
            "Exterior guards serving not more than one dwelling unit or a house",
            "the top of the guard to a line drawn through the tread nosing served by the guard",
        ):
            assert phrase in body, f"the 2024 article is not quoted in full: {phrase!r}"

    def test_it_carries_the_compendium_attribution(self, client) -> None:
        """Reproducing Compendium material carries conditions, and this is the
        one that is a string on the page.  The others are properties of the
        page as a whole: quote accurately, claim no official status, use no
        Ontario trademark.  See the card's "What the Compendium licence
        permits"."""
        body = _page(client).content.decode()
        assert "King's Printer for Ontario, 2024. Reproduced with permission." in body
        assert "not an official version" in body

    def test_it_declares_a_canonical_url(self, client) -> None:
        assert 'rel="canonical"' in _page(client).content.decode()

    def test_it_is_in_the_sitemap(self) -> None:
        from core.sitemaps import STATIC_PAGE_NAMES

        assert "core:guard_height" in STATIC_PAGE_NAMES

    def test_it_sets_no_cookie(self, client) -> None:
        """A response carrying ``Set-Cookie`` is one no shared cache stores.
        A single ``csrf_token`` on the page is enough to attach one."""
        response = _page(client)
        assert not response.cookies
        assert "csrfmiddlewaretoken" not in response.content.decode()

    def test_no_template_tag_leaks(self, client) -> None:
        """Django tokenises tags everywhere and a tag spanning a newline ships
        as literal text."""
        body = _page(client).content.decode()
        assert "{%" not in body
        assert "{{" not in body


@pytest.mark.django_db
class TestTheArgumentSurvivesTheCorpus:
    """Each test backs one claim the article's prose makes."""

    def test_it_opens_on_the_oldest_text(self, client, corpus) -> None:
        """The article starts at 1998 and everything after it is a change to
        that text, so the opening block is the 1997 one or the page is telling
        a different story from its own headings."""
        opening = _page(client).context["opening"]
        assert opening["edition_year"] == 1997
        assert opening["provision_id"] == OPENING[2] == "9.8.8.2."

    def test_every_named_transition_is_drawn(self, client, corpus) -> None:
        """The view drops a transition whose sides are missing, silently, so
        nothing else would notice."""
        transitions = _page(client).context["transitions"]
        assert len(transitions) == len(TRANSITIONS) == 5
        assert set(transitions) == {slug for slug, _, _ in TRANSITIONS}

    def test_each_transition_carries_a_redline(self, client, corpus) -> None:
        """The prose says "changed words stand out, unchanged words are
        dimmed".  A pair below the redline floor renders as two plain panes
        instead, which makes that sentence false."""
        for slug, transition in _page(client).context["transitions"].items():
            assert transition["redline"], f"{slug} fell through the redline floor"
            assert transition["old_diff"], f"{slug} has no marked earlier pane"
            assert transition["new_diff"], f"{slug} has no marked later pane"

    def test_each_transition_reads_earlier_to_later(self, client, corpus) -> None:
        """A comparison that ran the other way would show every amendment as
        its own undoing."""
        for slug, transition in _page(client).context["transitions"].items():
            earlier = transition["side_a"]["version"].effective_date
            later = transition["side_b"]["version"].effective_date
            assert earlier < later, f"{slug} runs backwards"

    def test_each_transition_names_both_instruments(self, client, corpus) -> None:
        """A redline of two texts that are not fully identified is an
        assertion, not evidence.  ``_compare_sides.html`` states the window and
        the regulation for each side, and it reads them from these dicts."""
        for slug, transition in _page(client).context["transitions"].items():
            for side in transition["sides"]:
                assert side["edition_name"], f"{slug} has an unnamed edition"
                assert side["version"].effective_date is not None

    def test_the_transitions_span_the_whole_record(self, client, corpus) -> None:
        """Five pairs over six texts, each starting where the last one ended.
        A gap would be an amendment the article passes over in silence."""
        transitions = _page(client).context["transitions"]
        chain = [transitions[slug] for slug, _, _ in TRANSITIONS]
        assert chain[0]["side_a"]["version"].pk == _page(client).context["opening"][
            "version"
        ].pk
        for before, after in zip(chain, chain[1:], strict=False):
            assert before["side_b"]["version"].pk == after["side_a"]["version"].pk

    def test_every_table_row_reaches_the_section_behind_it(
        self, client, corpus
    ) -> None:
        """The table has a row per text, and each one is an assertion the
        reader cannot check from the table itself.  Every row therefore links
        to the section that shows the text it came from.  With a corpus,
        because four of the five sections are the corpus."""
        body = _page(client).content.decode()
        for anchor in ("start", "renumbered", "split", "resolved", "today"):
            assert f'href="#{anchor}"' in body, f"no row reaches #{anchor}"
            assert f'id="{anchor}"' in body, f"#{anchor} is not on the page"

    def test_the_provision_number_moved(self, client, corpus) -> None:
        """The sharpest claim: 9.8.8.2. in 1997, 9.8.8.3. from 2006 on.  The
        first transition is where it happens, so it is the one pair on the page
        whose two sides carry different numbers."""
        renumbered = _page(client).context["transitions"]["renumbered"]
        assert renumbered["side_a"]["provision"].provision_id == "9.8.8.2."
        assert renumbered["side_b"]["provision"].provision_id == "9.8.8.3."

    def test_the_1997_text_allows_800_mm(self, client, corpus) -> None:
        """The table's first row turns on this number."""
        assert allows_800_mm(_page(client).context["opening"]["version"].html)

    def test_the_2006_text_does_not(self, client, corpus) -> None:
        """The table reads 800 mm for 1998 and 900 mm for 2006, which holds
        only while the 800 mm allowance is absent from the later text."""
        renumbered = _page(client).context["transitions"]["renumbered"]
        assert not allows_800_mm(renumbered["side_b"]["version"].html)

    def test_the_2012_edition_holds_three_texts(self, client, corpus) -> None:
        """"The 2012 code says" is not a sentence — the argument that defeats
        a reader's one saved PDF."""
        versions = set()
        for transition in _page(client).context["transitions"].values():
            for side in transition["sides"]:
                if side["edition"].edition_id == "2012":
                    versions.add(side["version"].pk)
        assert len(versions) == 3

    def test_the_1997_scan_is_shown(self, client, corpus) -> None:
        """A scan of the paper edition is evidence in a way reset text is not,
        and the article says it shows one."""
        assert _page(client).context["opening"]["version"].page_images

    def test_the_opening_reports_its_last_governed_day(self, client, corpus) -> None:
        """The stored window is half-open, so the end date names the first day
        the text did *not* govern.  ``core.seo.last_governed_day`` owns that
        conversion for the whole product."""
        assert _page(client).context["opening"]["last_day"] == date(2006, 12, 30)


@pytest.mark.django_db
class TestTheGate:
    def test_the_gated_text_renders_for_a_logged_out_reader(
        self, client, corpus, production_scope
    ) -> None:
        """The article depends on showing OBC 1997 to somebody who has not
        signed in.  The view leaves ``locked_edition_name`` unset rather than
        asking ``core.access`` for a provision-level exception."""
        response = _page(client)
        assert response.context["opening"]["version"].page_images
        assert "is Pro content" not in response.content.decode()

    def test_the_1997_permalink_is_marked_locked(
        self, client, corpus, production_scope
    ) -> None:
        """The link lands on the teaser, and the article says so rather than
        letting the reader find out by clicking."""
        assert _page(client).context["opening"]["locked"] is True

    def test_a_transition_with_a_gated_side_is_marked_locked(
        self, client, corpus, production_scope
    ) -> None:
        """``/compare/`` gates both sides, so one gated side locks the pair."""
        transitions = _page(client).context["transitions"]
        assert transitions["renumbered"]["locked"] is True

    def test_a_transition_inside_the_free_tier_is_not(
        self, client, corpus, production_scope
    ) -> None:
        transitions = _page(client).context["transitions"]
        assert transitions["measured"]["locked"] is False

    def test_the_call_to_action_searches_a_free_date(
        self, client, corpus, production_scope, settings
    ) -> None:
        """The article's one call to action must land on results the reader
        can read.  It used to search 1 June 1999, which is OBC 1997 — outside
        the free tier — so a first-time reader's first click was a locked
        page.  The date has to sit inside a free-tier edition's window, and
        this fails if either the date or the tier moves without the other."""
        body = _page(client).content.decode()
        match = re.search(r"&amp;d=(\d{4}-\d{2}-\d{2})", body)
        assert match, "the call to action names no date"
        searched = date.fromisoformat(match.group(1))
        windows = [
            (edition.effective_date, edition.ineffective_date)
            for edition in CodeEdition.objects.all()
            if f"{edition.code.code}_{edition.edition_id}"
            in settings.FREE_TIER_CODE_NAMES
        ]
        assert windows, "the fixture holds no free-tier edition"
        # A null end is an edition still in force, not a zero-length one.
        assert any(
            start <= searched and (end is None or searched < end)
            for start, end in windows
        ), f"{searched} is not inside a free-tier edition: {windows}"


@pytest.mark.django_db
class TestStructuredData:
    """The page tells a crawler it is *writing about* the law, not the law.

    Typing it as ``Legislation`` — the type the provision pages carry — would
    be the strongest available way to blur that line, on the one page where
    the analysis and the quoted text sit together.
    """

    def _block(self, client, corpus) -> dict:
        body = _page(client).content.decode()
        match = re.search(
            r'<script type="application/ld\+json">(.*?)</script>', body, re.S
        )
        assert match, "the page carries no JSON-LD"
        return json.loads(match.group(1))

    def test_it_is_typed_as_an_article(self, client, corpus) -> None:
        assert self._block(client, corpus)["@type"] == "Article"

    def test_it_names_the_page_it_is_about(self, client, corpus) -> None:
        block = self._block(client, corpus)
        assert block["url"].endswith(reverse("core:guard_height"))
        assert block["mainEntityOfPage"]["@id"] == block["url"]

    def test_it_declares_free_access(self, client, corpus) -> None:
        """Not decoration: the Compendium licence permits reproduction for
        non-commercial use and defines that as free access, so the claim the
        page makes and the condition it relies on are one fact."""
        assert self._block(client, corpus)["isAccessibleForFree"] is True

    def test_the_dates_are_the_authors_and_not_the_corpus(
        self, client, corpus
    ) -> None:
        """The historical texts render live, so a modified date taken from
        the last data load would claim the writing had changed every time an
        edition reloaded."""
        block = self._block(client, corpus)
        assert block["datePublished"] == PUBLISHED.isoformat()
        assert block["dateModified"] == MODIFIED.isoformat()
