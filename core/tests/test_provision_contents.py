"""The depth limit on a provision permalink.

A permalink renders the matched provision *and its whole subtree*.  That is
right for an article and wrong for a part: in OBC 2006, ``Part 9`` is 1,338
descendants and ``B`` is 2,934, and nobody reads either on a screen.  Over
``CONTENTS_THRESHOLD`` the page shows what is inside instead.

What these tests hold down is that the switch is by *measured size* rather
than by level name, that nothing becomes unreachable, and that the exhibit
follows the page.
"""

from datetime import date

import pytest
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
)
from core.subtrees import CONTENTS_THRESHOLD


def _version(provision, version=0, title="Scope", html="<p>Text</p>"):
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


def _tree(edition, *, children: int, grandchildren: int = 0):
    """A root with ``children`` children, each with ``grandchildren``."""
    root = CodeEditionProvision.objects.create(
        edition=edition, provision_id="Part 9", level="part", division="B",
    )
    _version(root, title="Housing and Small Buildings")
    for c in range(children):
        child = CodeEditionProvision.objects.create(
            edition=edition, provision_id=f"9.{c + 1}.", level="section",
            division="B", parent=root,
        )
        _version(child, title=f"Section {c + 1}")
        for g in range(grandchildren):
            leaf = CodeEditionProvision.objects.create(
                edition=edition, provision_id=f"9.{c + 1}.{g + 1}.",
                level="subsection", division="B", parent=child,
            )
            _version(leaf, title=f"Sub {g + 1}")
    return root


PART = "/provision/OBC_2006/B/Part 9/v0/"

#: A fragment of the block's own copy.  The bare word "Contents" is no good:
#: the edition-nav row's tooltip says "Contents of OBC 2006", so asserting on
#: it passes on every page.
CONTENTS_MARKER = "too many to show at once"


@pytest.mark.django_db
class TestASmallSubtreeIsUnchanged:
    """The common case.  95% of provisions are already small, and the whole
    point of a permalink there is that the text arrives whole."""

    def test_it_still_renders_every_descendant(self, client, edition):
        _tree(edition, children=3, grandchildren=2)
        body = client.get(PART).content.decode()
        assert "Sub 1" in body
        assert CONTENTS_MARKER not in body

    def test_every_rendered_sub_provision_links_to_its_own_page(
        self, client, edition
    ):
        """Nothing above article level carries text, so a container page is
        its links.  The rail's "Subprovisions" names only the direct children,
        which left every deeper provision reachable only by going back up.
        """
        _tree(edition, children=2, grandchildren=2)
        body = client.get(PART).content.decode()
        assert '<a href="/provision/OBC_2006/B/9.1./v0/"' in body
        assert '<a href="/provision/OBC_2006/B/9.1.1./v0/"' in body

    def test_the_provision_being_read_does_not_link_to_itself(
        self, client, edition
    ):
        _tree(edition, children=2)
        body = client.get(PART).content.decode()
        assert '<a href="/provision/OBC_2006/B/Part 9/v0/"' not in body

    def test_right_at_the_threshold_it_still_renders_text(self, client, edition):
        # One root plus CONTENTS_THRESHOLD - 1 children is exactly the limit.
        _tree(edition, children=CONTENTS_THRESHOLD - 1)
        body = client.get(PART).content.decode()
        assert CONTENTS_MARKER not in body


@pytest.mark.django_db
class TestAnOversizedSubtreeBecomesContents:
    def test_one_past_the_threshold_switches(self, client, edition):
        _tree(edition, children=CONTENTS_THRESHOLD)
        body = client.get(PART).content.decode()
        assert CONTENTS_MARKER in body

    def test_the_matched_provision_keeps_its_own_text(self, client, edition):
        """The page is still about this provision.  Only what is *under* it
        is summarised."""
        _tree(edition, children=CONTENTS_THRESHOLD)
        body = client.get(PART).content.decode()
        assert "Housing and Small Buildings" in body

    def test_no_descendant_text_is_rendered(self, client, edition):
        """The cost saving, stated as a property.  A grandchild's text must
        not appear at all — that is the duplication this removes."""
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=2)
        body = client.get(PART).content.decode()
        assert "Sub 1" not in body

    def test_every_child_is_still_linked(self, client, edition):
        """Nothing becomes unreachable.  A crawler still walks the corpus; it
        just stops reading the same text at five depths."""
        _tree(edition, children=CONTENTS_THRESHOLD)
        body = client.get(PART).content.decode()
        for c in range(CONTENTS_THRESHOLD):
            assert f"/provision/OBC_2006/B/9.{c + 1}./v0/" in body

    def test_it_states_how_many_provisions_it_is_withholding(self, client, edition):
        """The count is stated, not implied.

        The subtree walk stops early once it knows the answer is "too many",
        so this number is not a by-product — ``descendant_count`` asks for it.
        A reader told their text is withheld is owed the size of it.
        """
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=2)
        body = client.get(PART).content.decode()
        total = CONTENTS_THRESHOLD + CONTENTS_THRESHOLD * 2
        assert f"{intcomma(total)}</strong>" in body
        assert f"{CONTENTS_THRESHOLD} sections are listed here" in body

    def test_the_count_covers_every_depth_not_just_the_children(
        self, client, edition
    ):
        """Direct children alone would understate it by the whole tail."""
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=5)
        body = client.get(PART).content.decode()
        assert f"{intcomma(CONTENTS_THRESHOLD * 6)}</strong>" in body

    def test_a_row_names_what_is_under_it(self, client, edition):
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=3)
        body = client.get(PART).content.decode()
        assert "3 subsections" in body

    def test_a_row_with_one_child_is_singular(self, client, edition):
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=1)
        body = client.get(PART).content.decode()
        assert "1 subsection" in body
        assert "1 subsections" not in body

    def test_a_row_with_nothing_under_it_states_no_count(self, client, edition):
        """"0 subsections" reads as a fault in the data rather than as a
        provision that simply carries its own text."""
        _tree(edition, children=CONTENTS_THRESHOLD)
        body = client.get(PART).content.decode()
        assert CONTENTS_MARKER in body
        assert "0 subsection" not in body

    def test_the_subprovisions_nav_gives_way_to_it(self, client, edition):
        """Two lists of the same children on one page is worse than either."""
        _tree(edition, children=CONTENTS_THRESHOLD)
        body = client.get(PART).content.decode()
        assert "Subprovisions" not in body


@pytest.mark.django_db
class TestTheSwitchIsBySizeNotByLevel:
    def test_a_small_part_still_renders_as_text(self, client, edition):
        """A "part" is not automatically oversized, and a "section" is not
        automatically small — in the real corpus a section runs from 0 to 201
        descendants.  The name does not predict the cost, so it is not what
        decides.
        """
        _tree(edition, children=2)
        body = client.get(PART).content.decode()
        assert CONTENTS_MARKER not in body
        assert "Section 1" in body


@pytest.mark.django_db
class TestTheWorkIsBounded:
    def test_width_does_not_drive_the_query_count(
        self, client, edition
    ):
        """The property, rather than a number somebody has to keep updating.

        The walk stops on the generation that would breach the limit, so
        tripling the width must cost the same queries — the one generation it
        already had to look at, and one grouped tally over the next.  A
        regression to a per-row query shows up here as a difference.
        """
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=2)
        with CaptureQueriesContext(connection) as narrow:
            client.get(PART)

        CodeEditionProvision.objects.all().delete()
        _tree(edition, children=CONTENTS_THRESHOLD * 3, grandchildren=2)
        with CaptureQueriesContext(connection) as wide:
            client.get(PART)

        assert len(wide) == len(narrow)


@pytest.mark.django_db
class TestAnEmptyBodyIsNotAlwaysAFault:
    """Every container in this corpus has an empty body.

    Reported from ``/provision/OBC_2012/B/Part 2/v0/``, which read
    "Part 2 — Part 2 / Content not available for this version" — one message
    claiming a failure, and a title printed twice.
    """

    def test_a_container_says_nothing_about_missing_text(self, client, edition):
        """Its text is its children's, and they are right below it."""
        _tree(edition, children=3)
        body = client.get(PART).content.decode()
        assert "No text is recorded" not in body

    def test_an_oversized_container_says_nothing_either(self, client, edition):
        """Here the children are listed rather than rendered, which is still
        an answer — so the page must not also claim it has nothing."""
        _tree(edition, children=CONTENTS_THRESHOLD)
        body = client.get(PART).content.decode()
        assert CONTENTS_MARKER in body
        assert "No text is recorded" not in body

    def test_a_provision_with_no_text_and_no_children_says_so(self, client, edition):
        """OBC 2012 Div B Part 2 exactly: no children, no body, no title.

        The wording states what we hold rather than implying a fetch that
        failed, because from here we cannot tell whether the code reserves the
        provision or whether our source omitted it.
        """
        empty = CodeEditionProvision.objects.create(
            edition=edition, provision_id="Part 2", level="part", division="B",
        )
        _version(empty, title="", html="")
        body = client.get("/provision/OBC_2006/B/Part 2/v0/").content.decode()
        assert "No text is recorded for this provision in this edition." in body

    def test_a_reserved_provision_says_it_is_reserved(self, client, edition):
        """A reserved provision is the code's own doing, not a gap in ours.

        e-Laws numbers it and leaves it empty so the number stays available;
        OBC 2012 alone has 34, from Section 1.2. down to single sentences.
        CCM ships "Reserved" as the title, so we know rather than guess.
        """
        reserved = CodeEditionProvision.objects.create(
            edition=edition, provision_id="1.2.", level="section", division="B",
        )
        _version(reserved, title="Reserved", html="")
        body = client.get("/provision/OBC_2006/B/1.2./v0/").content.decode()
        assert "This provision is reserved" in body
        assert "No text is recorded" not in body

    def test_an_untitled_provision_is_not_named_twice(self, client, edition):
        empty = CodeEditionProvision.objects.create(
            edition=edition, provision_id="Part 2", level="part", division="B",
        )
        _version(empty, title="", html="")
        body = client.get("/provision/OBC_2006/B/Part 2/v0/").content.decode()
        assert "Part 2 — Part 2" not in body
        assert "Part 2 &mdash; Part 2" not in body


@pytest.mark.django_db
class TestTheExhibitFollowsThePage:
    def test_printing_an_oversized_provision_prints_its_contents(
        self, client, edition, django_user_model
    ):
        """The alternative is a 1,339-provision exhibit, and the guarantee
        this export makes is that paper shows what the page shows."""
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=2)
        user = django_user_model.objects.create_user(
            email="reader@example.com", password="pw12345!"
        )
        client.force_login(user)
        url = reverse(
            "core:provision_print",
            kwargs={
                "code_edition": "OBC_2006", "division": "B",
                "provision_id": "Part 9", "version": 0,
            },
        )
        body = client.get(url).content.decode()
        assert CONTENTS_MARKER in body
        assert "Sub 1" not in body


def _overlay(client, provision_id: str, **extra):
    """The search overlay's panel for one provision, as the results page asks
    for it."""
    return client.get(
        reverse("core:viewer_section_content"),
        {
            "code": "OBC", "edition_id": "2006", "division": "B",
            "provision_id": provision_id, "query_date": "2007-06-01",
            **extra,
        },
        HTTP_HX_REQUEST="true",
    ).content.decode()


@pytest.mark.django_db
class TestTheSearchOverlayIsBoundedToo:
    """The overlay walks the *parent's* subtree, so a reader sees the match in
    context.  That walk had no limit at all, and a search result is not always
    a leaf article: the candidate query does not exclude an empty body, and
    BM25F scores the title as its own field, so a part or a section can be the
    match.  Its parent's subtree is then the render CONTENTS_THRESHOLD exists
    to prevent — inline, highlighted, on the one surface that had no cap.
    """

    def test_a_small_subtree_still_arrives_whole(self, client, edition):
        _tree(edition, children=3, grandchildren=2)

        body = _overlay(client, "9.1.")

        assert "Sub 1" in body
        assert "9.2." in body, "the siblings are the context this panel is for"

    def test_an_oversized_parent_gives_up_the_siblings_first(
        self, client, edition
    ):
        """Context is what the parent is here for, but the reader searched for
        one provision and must still be shown it.  So the root narrows to the
        match rather than the panel changing character."""
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=2)

        body = _overlay(client, "9.1.")

        assert "9.1.1." in body, "the match keeps its own subtree"
        assert "9.40." not in body, "the siblings are what was given up"

    def test_an_oversized_match_lists_what_is_inside(self, client, edition):
        """The permalink's behaviour, from the permalink's builder and the
        permalink's partial.  A reader who meets the contents of Part 9 here
        and again on its own page must meet one list."""
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=2)

        body = _overlay(client, "Part 9")

        assert CONTENTS_MARKER in body
        assert "Sub 1" not in body, "no generation past the limit is rendered"
        assert '<a href="/provision/OBC_2006/B/9.1./v0/"' in body

    def test_the_two_surfaces_show_the_same_list(self, client, edition):
        """The whole reason the builder moved out of the view layer.  Two
        lists of one thing drift, and the drift is invisible until somebody
        opens both."""
        _tree(edition, children=CONTENTS_THRESHOLD, grandchildren=2)

        panel = _overlay(client, "Part 9")
        page = client.get(PART).content.decode()

        for row in range(1, CONTENTS_THRESHOLD + 1):
            link = f'<a href="/provision/OBC_2006/B/9.{row}./v0/"'
            assert (link in panel) == (link in page)
        assert "2 subsections" in panel
        assert "2 subsections" in page

    def test_a_whole_subtree_that_fits_lists_nothing(self, client, edition):
        _tree(edition, children=3, grandchildren=2)

        body = _overlay(client, "Part 9")

        assert CONTENTS_MARKER not in body
        assert "Sub 1" in body, "it fits, so it is rendered"
