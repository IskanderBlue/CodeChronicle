"""The comparison page and the prepared pair it opens.

Two things are worth stating about the fixtures. OBC 2006 is the free-tier
edition and OBC 2012 is not, so a cross-edition pair between them exercises
the gate without inventing a tier. And every version carries real ``html``,
because the redline floor measures words: a fixture with empty bodies would
pass the ladder tests while telling you nothing about the fallback.
"""

from datetime import date

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client

from accounts.access import edition_gate
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EditionTransition,
    EngagementEvent,
    ProvisionCrossReference,
    ProvisionMapping,
    Regulation,
    User,
)
from corpus.lineage.compare import (
    PreparedPair,
    parse_version_ref,
    prepared_pair,
    version_ref,
    version_timeline,
)
from corpus.lineage.provision_lineage import resolve_lineage

FREE = ["OBC_2006"]


@pytest.fixture
def corpus(db):
    """OBC 2006 and OBC 2012, mapped, with a multi-version provision."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    e2006 = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006,
        effective_date=date(2006, 12, 31), ineffective_date=date(2014, 1, 1),
    )
    e2012 = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012, effective_date=date(2014, 1, 1),
    )
    EditionTransition.objects.create(old_edition=e2006, new_edition=e2012)
    base = Regulation.objects.create(
        reg_id="350/06", edition=e2006, role="base",
        effective_date=date(2006, 12, 31),
    )

    # Amended twice inside OBC 2006.  The three bodies stay close enough to
    # each other to clear the redline floor.
    amended = CodeEditionProvision.objects.create(
        edition=e2006, provision_id="3.2.5.7.", level="article", division="B",
    )
    bodies = [
        "<p>A fire separation shall be provided between the storeys.</p>",
        "<p>A fire separation shall be provided between the storeys and rooms.</p>",
        "<p>A fire separation shall be installed between the storeys and rooms.</p>",
    ]
    versions = [
        CodeEditionProvisionVersion.objects.create(
            provision=amended, version=n, title="Fire separations",
            effective_date=date(2007 + n * 2, 1, 1), html=body,
        )
        for n, body in enumerate(bodies)
    ]

    # Renumbered into OBC 2012, one version each side.
    old = CodeEditionProvision.objects.create(
        edition=e2006, provision_id="9.10.18.6.", level="article", division="B",
    )
    new = CodeEditionProvision.objects.create(
        edition=e2012, provision_id="9.10.18.7.", level="article", division="B",
    )
    carried = {}
    for key, prov, body in (
        ("old", old, "<p>Smoke alarms shall be installed in each dwelling unit.</p>"),
        ("new", new, "<p>Smoke alarms shall be installed in every dwelling unit.</p>"),
    ):
        carried[key] = CodeEditionProvisionVersion.objects.create(
            provision=prov, version=0, title="Smoke Alarms",
            effective_date=prov.edition.effective_date, html=body,
        )
    ProvisionMapping.objects.create(
        old_provision=old, new_provision=new, mapping_type="renumbered",
    )

    return {
        "e2006": e2006, "e2012": e2012, "base": base,
        "amended": amended, "versions": versions,
        "old": old, "new": new,
        "old_v0": carried["old"], "new_v0": carried["new"],
    }


@pytest.fixture
def pro(db):
    return User.objects.create_user(
        email="pro@example.com", password="testpass", pro_courtesy=True,
    )


def _pair_for(version) -> PreparedPair | None:
    """The ladder, fed the way the real callers feed it."""
    provision = version.provision
    lineage = resolve_lineage([provision]).get(provision.pk)
    return prepared_pair(
        version=version,
        chain=list(
            CodeEditionProvisionVersion.objects.filter(provision=provision)
        ),
        predecessors=lineage.predecessors if lineage else None,
        successors=lineage.successors if lineage else None,
    )


class TestVersionReference:
    """The reference form is the permalink path form, both directions."""

    def test_a_reference_with_a_division_round_trips(self):
        ref = parse_version_ref("OBC_2006/B/3.2.5.7./v0")
        assert ref is not None
        assert ref.division == "B"
        assert ref.path == "OBC_2006/B/3.2.5.7./v0"

    def test_a_division_less_reference_round_trips(self):
        """OBC 1997 stores division="" and its permalink omits the segment."""
        ref = parse_version_ref("OBC_1997/3.2.5.7./v3")
        assert ref is not None
        assert ref.division == ""
        assert ref.provision_id == "3.2.5.7."
        assert ref.path == "OBC_1997/3.2.5.7./v3"

    @pytest.mark.parametrize(
        "raw", ["", None, "OBC_2006", "OBC_2006/B/3.2.5.7.", "OBC_2006/B/3.2.5.7./3"],
    )
    def test_a_malformed_reference_is_none(self, raw):
        assert parse_version_ref(raw) is None

    @pytest.mark.django_db
    def test_a_version_names_itself(self, corpus):
        assert version_ref(corpus["versions"][1]).path == "OBC_2006/B/3.2.5.7./v1"


@pytest.mark.django_db
class TestPreparedPair:
    """What "Compare versions" opens, in ladder order."""

    def test_the_previous_version_wins(self, corpus):
        pair = _pair_for(corpus["versions"][2])
        assert pair is not None
        assert pair.a.path == "OBC_2006/B/3.2.5.7./v1"
        assert pair.b.path == "OBC_2006/B/3.2.5.7./v2"

    def test_with_no_previous_version_it_reaches_back_an_edition(self, corpus):
        """The OBC 2012 side is v0, so its only earlier text is the mapped one.

        This is the rung that makes an unamended provision cross the edition
        boundary by itself.
        """
        pair = _pair_for(corpus["new_v0"])
        assert pair is not None
        assert pair.a.path == "OBC_2006/B/9.10.18.6./v0"
        assert pair.b.path == "OBC_2012/B/9.10.18.7./v0"

    def test_v0_with_a_later_version_compares_forward(self, corpus):
        """Nothing earlier exists, so this version becomes the earlier side."""
        pair = _pair_for(corpus["versions"][0])
        assert pair is not None
        assert pair.a.path == "OBC_2006/B/3.2.5.7./v0"
        assert pair.b.path == "OBC_2006/B/3.2.5.7./v1"

    def test_only_a_mapped_successor_is_still_a_pair(self, corpus):
        """The OBC 2006 side has one version and a successor, nothing before."""
        pair = _pair_for(corpus["old_v0"])
        assert pair is not None
        assert pair.a.path == "OBC_2006/B/9.10.18.6./v0"
        assert pair.b.path == "OBC_2012/B/9.10.18.7./v0"

    def test_a_lone_version_has_no_pair(self, corpus):
        """No sibling and no mapping, so no control is offered at all."""
        lonely = CodeEditionProvision.objects.create(
            edition=corpus["e2006"], provision_id="1.1.1.1.",
            level="article", division="A",
        )
        version = CodeEditionProvisionVersion.objects.create(
            provision=lonely, version=0, title="Scope",
            effective_date=date(2006, 12, 31), html="<p>Scope.</p>",
        )
        assert _pair_for(version) is None

    def test_the_url_carries_both_references_readably(self, corpus):
        pair = _pair_for(corpus["versions"][2])
        assert pair is not None
        assert pair.url == (
            "/compare/?a=OBC_2006/B/3.2.5.7./v1&b=OBC_2006/B/3.2.5.7./v2"
        )


@pytest.mark.django_db
class TestComparePage:
    def test_it_states_both_windows_and_both_regulations(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        ).content.decode()
        assert "2007-01-01" in body
        assert "2009-01-01" in body
        assert "v0" in body and "v1" in body

    def test_the_pair_is_ordered_by_date_not_by_parameter(
        self, client: Client, corpus, settings,
    ):
        """Naming the later version as `a` still reads earlier-to-later."""
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v2", "b": "OBC_2006/B/3.2.5.7./v0"},
        ).content.decode()
        assert body.index("2007-01-01") < body.index("2011-01-01")

    def test_a_missing_version_says_which_one(self, client: Client, corpus, settings):
        settings.FREE_TIER_CODE_NAMES = FREE
        response = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v9"},
        )
        assert response.status_code == 404
        assert "v9 is not in OBC_2006" in response.content.decode()

    def test_a_malformed_reference_explains_the_form(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        response = client.get("/compare/", {"a": "nonsense", "b": "also-nonsense"})
        assert response.status_code == 404
        assert "OBC_2006/B/3.2.5.7./v0" in response.content.decode()

    def test_one_version_against_itself_is_refused(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        response = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v1", "b": "OBC_2006/B/3.2.5.7./v1"},
        )
        assert response.status_code == 404
        assert "two different versions" in response.content.decode()

    def test_an_unchanged_pair_says_so(self, client: Client, corpus, settings):
        """The one thing a redline cannot show is that it marked nothing.

        Without the line, a reader has to read both columns to the end to tell
        "no change" from "I have not reached the change yet".
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        later = corpus["versions"][1]
        later.html = corpus["versions"][0].html
        later.save()
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        ).content.decode()
        assert "The text is unchanged." in body
        # The legend describes a contrast this page does not draw.
        assert "Changed text stands out" not in body

    def test_a_changed_pair_does_not_say_the_text_is_unchanged(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        ).content.decode()
        assert "The text is unchanged." not in body
        assert "Changed text stands out" in body

    def test_citations_in_the_panes_are_links(
        self, client: Client, corpus, settings,
    ):
        """A citation is a link on every other provision surface.

        The comparison renders the version bodies itself, so it has to run the
        same annotation; otherwise the one page that most invites a reader to
        follow a reference is the one page where references are dead text.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        citing = corpus["versions"][1]
        citing.html = (
            "<p>A fire separation conforming to Article 9.10.18.6. is required.</p>"
        )
        citing.save()
        ProvisionCrossReference.objects.create(
            from_version=citing,
            to_provision=corpus["old"],
            surface_text="9.10.18.6.",
            start=citing.html.index("9.10.18.6."),
            end=citing.html.index("9.10.18.6.") + len("9.10.18.6."),
            targets=[
                {
                    "version": 0,
                    "effective_date": "2006-12-31",
                    "ineffective_date": "",
                }
            ],
        )
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        ).content.decode()
        assert 'class="cross-ref ui-cite"' in body


@pytest.mark.django_db
class TestCompareGating:
    """The tier rule applied once per side, never redefined."""

    def test_same_edition_inside_the_free_tier_is_open(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        response = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        )
        assert response.status_code == 200

    def test_cross_edition_is_locked_for_a_free_reader(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        response = client.get(
            "/compare/",
            {"a": "OBC_2006/B/9.10.18.6./v0", "b": "OBC_2012/B/9.10.18.7./v0"},
        )
        assert response.status_code == 403
        assert "Pro content" in response.content.decode()

    def test_cross_edition_is_open_for_pro(
        self, client: Client, corpus, settings, pro,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        client.force_login(pro)
        response = client.get(
            "/compare/",
            {"a": "OBC_2006/B/9.10.18.6./v0", "b": "OBC_2012/B/9.10.18.7./v0"},
        )
        assert response.status_code == 200


@pytest.mark.django_db
class TestComparisonEvent:
    """A comparison is recorded as value delivered, and only when it was."""

    def test_a_delivered_comparison_is_recorded(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        )
        event = EngagementEvent.objects.get(
            event_type=EngagementEvent.EventType.VERSION_COMPARISON,
        )
        assert event.context["a"] == "OBC_2006/B/3.2.5.7./v0"
        assert event.context["b"] == "OBC_2006/B/3.2.5.7./v1"
        assert event.context["cross_edition"] is False
        assert event.object_id == corpus["versions"][1].pk

    def test_a_cross_edition_comparison_is_marked_as_one(
        self, client: Client, corpus, settings, pro,
    ):
        """The split that matters: this is the comparison Pro buys."""
        settings.FREE_TIER_CODE_NAMES = FREE
        client.force_login(pro)
        client.get(
            "/compare/",
            {"a": "OBC_2006/B/9.10.18.6./v0", "b": "OBC_2012/B/9.10.18.7./v0"},
        )
        event = EngagementEvent.objects.get(
            event_type=EngagementEvent.EventType.VERSION_COMPARISON,
        )
        assert event.context["cross_edition"] is True

    def test_a_refused_comparison_records_the_refusal_and_nothing_else(
        self, client: Client, corpus, settings,
    ):
        """A locked reader is a conversion signal, not a delivered comparison.

        The two counts are the numerator and the denominator of one question,
        so a refusal must never land in both.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        client.get(
            "/compare/",
            {"a": "OBC_2006/B/9.10.18.6./v0", "b": "OBC_2012/B/9.10.18.7./v0"},
        )
        assert not EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.VERSION_COMPARISON,
        ).exists()
        assert EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.LOCKED_CONTENT_VIEW,
        ).exists()

    def test_a_comparison_that_cannot_be_built_records_nothing(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v9"},
        )
        assert not EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.VERSION_COMPARISON,
        ).exists()


@pytest.mark.django_db
class TestPairingBasis:
    """A cross-edition redline must say where the equivalence came from."""

    def test_two_versions_of_one_provision_claim_nothing(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        ).content.decode()
        assert "counterparts" not in body
        assert "did not enact them as a pair" not in body

    def test_a_mapped_pair_cites_the_mapping(
        self, client: Client, corpus, settings, pro,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        client.force_login(pro)
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/9.10.18.6./v0", "b": "OBC_2012/B/9.10.18.7./v0"},
        ).content.decode()
        assert "counterparts, not the same provision" in body
        assert "did not enact them as a pair" in body

    def test_a_version_outliving_its_edition_still_cites_the_mapping(
        self, client: Client, corpus, settings, pro,
    ):
        """The sides sort by date; a mapping runs in edition order.

        CCM lets a version's window run past its edition on purpose, so the
        older edition's version can carry the later date and land on side B.
        Asked only forwards, the page then reported "no mapping links them"
        for a pair whose rail names the counterpart on both provisions.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        client.force_login(pro)
        old_v0 = corpus["old_v0"]
        old_v0.effective_date = date(2016, 1, 1)   # after the 2012 edition starts
        old_v0.save()
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/9.10.18.6./v0", "b": "OBC_2012/B/9.10.18.7./v0"},
        ).content.decode()
        assert "counterparts, not the same provision" in body
        assert "does not pair these two provisions" not in body
        # Named in the mapping's own direction, not the drawing order.
        assert body.index("9.10.18.6.", body.index("CodeChronicle maps")) < body.index(
            "9.10.18.7.", body.index("CodeChronicle maps"),
        )

    def test_a_hand_built_unmapped_pair_says_so(
        self, client: Client, corpus, settings, pro,
    ):
        """Reachable only by editing the URL, and it must not imply a pairing."""
        settings.FREE_TIER_CODE_NAMES = FREE
        client.force_login(pro)
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2012/B/9.10.18.7./v0"},
        ).content.decode()
        assert "does not pair these two provisions" in body


@pytest.mark.django_db
class TestRedlineFloor:
    """Two texts with nothing in common are shown, not redlined."""

    @pytest.fixture
    def unrelated(self, corpus):
        """A second provision whose text shares almost no words with v0."""
        provision = CodeEditionProvision.objects.create(
            edition=corpus["e2006"], provision_id="8.1.1.1.",
            level="article", division="B",
        )
        for n, body in enumerate((
            "<p>Every building shall be designed by a professional engineer.</p>",
            "<p>Excavation depth requires shoring approved under municipal bylaw.</p>",
        )):
            CodeEditionProvisionVersion.objects.create(
                provision=provision, version=n, title="Design",
                effective_date=date(2007 + n, 1, 1), html=body,
            )
        return provision

    def test_below_the_floor_it_falls_back_and_says_why(
        self, client: Client, corpus, unrelated, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/8.1.1.1./v0", "b": "OBC_2006/B/8.1.1.1./v1"},
        ).content.decode()
        assert "shown side by side" in body
        assert "Show the redline anyway" in body

    def test_the_reader_can_overrule_the_floor(
        self, client: Client, corpus, unrelated, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get(
            "/compare/",
            {
                "a": "OBC_2006/B/8.1.1.1./v0",
                "b": "OBC_2006/B/8.1.1.1./v1",
                "redline": "on",
            },
        ).content.decode()
        assert "Show the redline anyway" not in body
        assert "diff-old-unchanged" in body or "diff-new-unchanged" in body

    def test_a_close_pair_is_redlined(self, client: Client, corpus, settings):
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        ).content.decode()
        assert "shown side by side" not in body
        assert "diff-new-unchanged" in body


@pytest.mark.django_db
class TestVersionTimeline:
    """The axis that makes a prepared pair safe to offer."""

    def test_it_draws_every_version_once_per_side(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        timeline = version_timeline(
            corpus["versions"][0], corpus["versions"][1], edition_gate(AnonymousUser()),
        )
        assert [row.label for row in timeline.rows] == ["A", "B"]
        # Each row leaves out the one version it can never hold: the earlier
        # side cannot be the newest, the later side cannot be the oldest —
        # either would leave the other side nothing to be.
        assert [tick.version.version for tick in timeline.rows[0].ticks] == [0, 1]
        assert [tick.version.version for tick in timeline.rows[1].ticks] == [1, 2]
        assert [tick.state for tick in timeline.rows[0].ticks] == [
            "selected", "taken",
        ]
        assert [tick.state for tick in timeline.rows[1].ticks] == [
            "selected", "open",
        ]
        assert timeline.is_useful

    def test_the_row_you_click_in_is_the_pin_that_moves(
        self, client: Client, corpus, settings,
    ):
        """The reachability rule, and the reason there are two rows.

        "Move the nearer pin" could not reach a pair of ticks that are both
        nearer the same pin: each click replaced the one that had just moved,
        so the far pin never left.  Two rows have no rule to get wrong.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        # From (v0, v1): the B row moves B alone.
        row_b = version_timeline(
            corpus["versions"][0], corpus["versions"][1], edition_gate(AnonymousUser()),
        ).rows[1]
        assert row_b.ticks[-1].url == (
            "/compare/?a=OBC_2006/B/3.2.5.7./v0&b=OBC_2006/B/3.2.5.7./v2"
        )
        # And from there the A row moves A alone, reaching (v1, v2) — the pair
        # the old nearest-pin rule could never produce, because every click
        # replaced the pin that had just moved.
        row_a = version_timeline(
            corpus["versions"][0], corpus["versions"][2], edition_gate(AnonymousUser()),
        ).rows[0]
        assert row_a.ticks[1].url == (
            "/compare/?a=OBC_2006/B/3.2.5.7./v1&b=OBC_2006/B/3.2.5.7./v2"
        )

    def test_the_other_sides_pin_is_drawn_but_not_offered(
        self, client: Client, corpus, settings,
    ):
        """Leaving it out would make the two rows disagree about what exists."""
        settings.FREE_TIER_CODE_NAMES = FREE
        row_a = version_timeline(
            corpus["versions"][0], corpus["versions"][1], edition_gate(AnonymousUser()),
        ).rows[0]
        assert row_a.ticks[1].state == "taken"
        assert row_a.ticks[1].url == ""

    def test_a_row_omits_the_version_it_can_never_hold(
        self, client: Client, corpus, settings,
    ):
        """The earlier side cannot be the newest, nor the later side the oldest.

        Either would leave the other side nothing to be, so the mark is left
        out rather than drawn and refused.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        row_a, row_b = version_timeline(
            corpus["versions"][0], corpus["versions"][1], edition_gate(AnonymousUser()),
        ).rows
        assert 2 not in [tick.version.version for tick in row_a.ticks]
        assert 0 not in [tick.version.version for tick in row_b.ticks]
        # And the connector stops at the last mark the row draws, rather than
        # running on to promise a choice that is not there.
        assert row_a.line_end < 100.0
        assert row_b.line_start > 0.0

    def test_colliding_marks_stack_into_lanes(
        self, client: Client, corpus, settings,
    ):
        """Two amendments days apart are a real fact, not a drawing accident."""
        settings.FREE_TIER_CODE_NAMES = FREE
        corpus["versions"][1].effective_date = corpus["versions"][0].effective_date
        corpus["versions"][1].save()
        timeline = version_timeline(
            corpus["versions"][0], corpus["versions"][2], edition_gate(AnonymousUser()),
        )
        assert [tick.lane for tick in timeline.rows[0].ticks] == [0, 1]
        assert [tick.lane for tick in timeline.rows[1].ticks] == [1, 0]
        assert timeline.lanes == 2

    def test_each_rows_date_sits_at_its_own_pin(
        self, client: Client, corpus, settings,
    ):
        """A date at the end of a row labels the row, not the mark.

        The two rows differ only in where their pin is, so a reader has to be
        able to read each row's date off the position it names.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        timeline = version_timeline(
            corpus["versions"][0], corpus["versions"][2], edition_gate(AnonymousUser()),
        )
        row_a, row_b = timeline.rows
        assert row_a.pin_offset == 0.0
        assert row_b.pin_offset == 100.0
        assert row_a.version.effective_date != row_b.version.effective_date

    def test_the_offsets_are_dates_not_even_spacing(
        self, client: Client, corpus, settings,
    ):
        """The fixture's versions are two years apart, then two more.

        Even spacing would put the middle tick at 50 either way, so this is the
        assertion that the axis is a date axis.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        corpus["versions"][1].effective_date = date(2010, 7, 2)
        corpus["versions"][1].save()
        timeline = version_timeline(
            corpus["versions"][0], corpus["versions"][2], edition_gate(AnonymousUser()),
        )
        # Row A drops the newest version and row B the oldest, so the two ends
        # of the scale come from one row each.
        assert round(timeline.rows[0].ticks[0].offset) == 0
        assert round(timeline.rows[1].ticks[-1].offset) == 100
        assert round(timeline.rows[0].ticks[1].offset) != 50

    def test_a_locked_edition_is_left_off_the_axis(
        self, client: Client, corpus, settings,
    ):
        """A tick is a control, and a locked tick would fail on click."""
        settings.FREE_TIER_CODE_NAMES = FREE
        free = version_timeline(
            corpus["old_v0"], corpus["old_v0"], edition_gate(AnonymousUser()),
        )
        assert all(
            tick.version.provision.edition.code_name == "OBC_2006"
            for row in free.rows
            for tick in row.ticks
        )

    def test_the_page_omits_the_axis_when_it_would_draw_only_the_pins(
        self, client: Client, corpus, settings,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        lonely_old = CodeEditionProvision.objects.create(
            edition=corpus["e2006"], provision_id="2.2.2.2.",
            level="article", division="B",
        )
        pair = [
            CodeEditionProvisionVersion.objects.create(
                provision=lonely_old, version=n, title="Scope",
                effective_date=date(2007 + n, 1, 1),
                html=f"<p>Scope of the thing {n}.</p>",
            )
            for n in range(2)
        ]
        timeline = version_timeline(pair[0], pair[1], edition_gate(AnonymousUser()))
        assert not timeline.is_useful

        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/2.2.2.2./v0", "b": "OBC_2006/B/2.2.2.2./v1"},
        ).content.decode()
        assert "Every version" not in body

    def test_the_page_renders_the_axis(self, client: Client, corpus, settings):
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get(
            "/compare/",
            {"a": "OBC_2006/B/3.2.5.7./v0", "b": "OBC_2006/B/3.2.5.7./v1"},
        ).content.decode()
        assert "Every version" in body
        # A pin move replaces history: five nudges must not cost six back
        # presses to escape the page.
        assert "window.location.replace" in body
        assert (
            "/compare/?a=OBC_2006/B/3.2.5.7./v0&amp;b=OBC_2006/B/3.2.5.7./v2"
            in body
        )
        # The connector between the marks is faint and dotted, not a rule, and
        # the marks and dates knock it out behind them with the backdrop token
        # this box re-declares — never a named surface.
        assert "border-dotted" in body
        assert "--backdrop: var(--surface-2)" in body
        assert "tl-open" in body and "tl-date" in body


@pytest.mark.django_db
class TestCompareControl:
    """The button on the permalink rail."""

    def test_it_offers_the_prepared_pair(self, client: Client, corpus, settings):
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get("/provision/OBC_2006/B/3.2.5.7./v2/").content.decode()
        assert "Compare versions" in body
        assert "/compare/?a=OBC_2006/B/3.2.5.7./v1&amp;b=OBC_2006/B/3.2.5.7./v2" in body

    def test_the_narrow_layout_carries_the_control_too(
        self, client: Client, corpus, settings,
    ):
        """Below lg is a second tree, not a narrower rendering of the first.

        The page emits both and lets CSS pick one (`hidden lg:block` /
        `lg:hidden`), so a control added above lg is absent below it until the
        other call site asks for it as well.  Two occurrences is the assertion:
        one per breakpoint tree.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get("/provision/OBC_2006/B/3.2.5.7./v2/").content.decode()
        assert body.count("Compare versions") == 2

    def test_a_lone_version_gets_no_control(self, client: Client, corpus, settings):
        settings.FREE_TIER_CODE_NAMES = FREE
        lonely = CodeEditionProvision.objects.create(
            edition=corpus["e2006"], provision_id="1.1.1.1.",
            level="article", division="A",
        )
        CodeEditionProvisionVersion.objects.create(
            provision=lonely, version=0, title="Scope",
            effective_date=date(2006, 12, 31), html="<p>Scope.</p>",
        )
        body = client.get("/provision/OBC_2006/A/1.1.1.1./v0/").content.decode()
        assert "Compare versions" not in body

    def test_a_chain_row_links_to_the_comparison_page(
        self, client: Client, corpus, settings,
    ):
        """``?compare=`` is retired: the per-row link goes to /compare/.

        The earlier version takes the A side whichever row is clicked, so the
        page reads earlier-to-later without the reader choosing an order.
        """
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get("/provision/OBC_2006/B/3.2.5.7./v1/").content.decode()
        assert "?compare=" not in body
        assert (
            "/compare/?a=OBC_2006/B/3.2.5.7./v0&amp;b=OBC_2006/B/3.2.5.7./v1"
            in body
        )
        assert (
            "/compare/?a=OBC_2006/B/3.2.5.7./v1&amp;b=OBC_2006/B/3.2.5.7./v2"
            in body
        )

    def test_a_lineage_row_offers_its_own_cross_edition_comparison(
        self, client: Client, corpus, settings, pro,
    ):
        """The prepared pair takes the local comparison, so the row carries
        the cross-edition one — otherwise an amended-and-renumbered provision
        could not ask for it at all."""
        settings.FREE_TIER_CODE_NAMES = FREE
        client.force_login(pro)
        body = client.get("/provision/OBC_2006/B/9.10.18.6./v0/").content.decode()
        assert (
            "/compare/?a=OBC_2006/B/9.10.18.6./v0&amp;b=OBC_2012/B/9.10.18.7./v0"
            in body
        )

    def test_a_predecessor_row_puts_the_counterpart_on_the_earlier_side(
        self, client: Client, corpus, settings, pro,
    ):
        settings.FREE_TIER_CODE_NAMES = FREE
        client.force_login(pro)
        body = client.get("/provision/OBC_2012/B/9.10.18.7./v0/").content.decode()
        assert (
            "/compare/?a=OBC_2006/B/9.10.18.6./v0&amp;b=OBC_2012/B/9.10.18.7./v0"
            in body
        )

    def test_a_locked_lineage_row_offers_no_comparison(
        self, client: Client, corpus, settings,
    ):
        """The row already upsells; a second pricing link beside it is noise."""
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get("/provision/OBC_2006/B/9.10.18.6./v0/").content.decode()
        assert "/compare/?a=" not in body

    def test_a_locked_counterpart_upsells_instead_of_linking(
        self, client: Client, corpus, settings,
    ):
        """The only pair crosses into OBC 2012, which this reader cannot open."""
        settings.FREE_TIER_CODE_NAMES = FREE
        body = client.get("/provision/OBC_2006/B/9.10.18.6./v0/").content.decode()
        assert "Compare versions &mdash; Pro" in body or "Compare versions —" in body
        assert "/pricing/" in body
