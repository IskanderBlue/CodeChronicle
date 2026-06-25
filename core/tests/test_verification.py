"""Tests for ``core.verification.derive_status`` — the per-(provision, date) rank.

Each test builds a real provision version timeline + ``Consolidation`` rows
and asserts the derived rank, the surfaced consolidations, and the
``reconstructed_from`` flag (the ``From`` ring). Two calendar shapes appear: a
back-to-back **closed** e-Laws period (positive-width intervals) and **zero-range
point** reprints (a periodic publisher), since the rank logic must handle both.
"""

from datetime import date

import pytest
from django.template.loader import render_to_string

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    Consolidation,
)
from core.verification import BaseInput, build_rail, derive_status

# A fixed "today" so the open-tail window end is deterministic in geometry tests.
_TODAY = date(2026, 6, 18)


@pytest.fixture
def edition(db) -> CodeEdition:
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    return CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012, effective_date=date(2014, 1, 1)
    )


@pytest.fixture
def provision(edition: CodeEdition) -> CodeEditionProvision:
    return CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.1.1.1.", level=CodeEditionProvision.Level.ARTICLE
    )


def _version(
    provision: CodeEditionProvision, num: int, frm: date, until: date | None
) -> CodeEditionProvisionVersion:
    return CodeEditionProvisionVersion.objects.create(
        provision=provision, version=num, effective_date=frm, ineffective_date=until
    )


def _cons(edition: CodeEdition, num: int, frm: date, to: date) -> None:
    Consolidation.objects.create(
        edition=edition,
        version=num,
        url=f"https://www.ontario.ca/laws/regulation/120332/v{num}",
        effective_from=frm,
        effective_to=to,
    )


class TestCovered:
    def test_query_inside_a_closed_period_is_rank_1(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        v = _version(provision, 1, date(2014, 1, 1), None)
        _cons(edition, 5, date(2014, 1, 1), date(2014, 9, 22))
        status = derive_status(v, date(2014, 5, 1))
        assert status is not None
        assert status["rank"] == 1
        assert status["reconstructed_from"] is False
        assert [c["role"] for c in status["consolidations"]] == ["covering"]
        assert status["in_force"] == {"from": date(2014, 1, 1), "until": None}


class TestBracketed:
    def test_unchanged_between_two_points_is_rank_2(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        # One version spanning both zero-range reprints, started before the prior.
        v = _version(provision, 1, date(2014, 6, 1), None)
        _cons(edition, 5, date(2015, 1, 1), date(2015, 1, 1))
        _cons(edition, 6, date(2016, 1, 1), date(2016, 1, 1))
        status = derive_status(v, date(2015, 6, 1))
        assert status is not None
        assert status["rank"] == 2
        assert status["reconstructed_from"] is False
        assert [c["role"] for c in status["consolidations"]] == ["prior", "following"]

    def test_version_starting_inside_the_bracket_is_rank_3(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        _version(provision, 1, date(2014, 6, 1), date(2015, 7, 1))
        v = _version(provision, 2, date(2015, 7, 1), None)
        _cons(edition, 5, date(2015, 1, 1), date(2015, 1, 1))
        _cons(edition, 6, date(2016, 1, 1), date(2016, 1, 1))
        status = derive_status(v, date(2015, 9, 1))
        assert status is not None
        assert status["rank"] == 3
        assert status["reconstructed_from"] is True
        assert [c["role"] for c in status["consolidations"]] == ["prior", "following"]


class TestOpenTail:
    def test_unchanged_tail_past_last_consolidation_is_rank_4(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        v = _version(provision, 1, date(2014, 1, 1), None)
        _cons(edition, 5, date(2014, 1, 1), date(2014, 12, 31))
        status = derive_status(v, date(2015, 6, 1))
        assert status is not None
        assert status["rank"] == 4
        assert status["reconstructed_from"] is False
        assert [c["role"] for c in status["consolidations"]] == ["prior"]
        # The prior interval lies within the in-force window — not off-line.
        assert status["consolidations"][0]["off_line"] is None

    def test_reconstructed_tail_is_rank_5_with_off_line_prior(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        _version(provision, 1, date(2014, 1, 1), date(2015, 3, 1))
        v = _version(provision, 2, date(2015, 3, 1), None)
        _cons(edition, 5, date(2014, 1, 1), date(2014, 12, 31))
        status = derive_status(v, date(2015, 6, 1))
        assert status is not None
        assert status["rank"] == 5
        assert status["reconstructed_from"] is True
        # The prior consolidation predates this version's commencement → off-line.
        assert status["consolidations"][0]["off_line"] == "left"


class TestUnconfirmed:
    def test_new_provision_after_all_consolidations(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        # Provision introduced by amendment in 2020; calendar stops in 2014.
        v = _version(provision, 1, date(2020, 1, 1), None)
        _cons(edition, 5, date(2014, 1, 1), date(2014, 12, 31))
        status = derive_status(v, date(2020, 6, 1))
        assert status is not None
        assert status["rank"] == "unconfirmed"
        assert status["reconstructed_from"] is True
        # No consolidation existed while the provision did → none surfaced.
        assert status["consolidations"] == []

    def test_no_backward_extrapolation_before_first_consolidation(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        # Provision exists from edition start, but the calendar begins later. A
        # date before the first consolidation is unconfirmed, with the following
        # one surfaced (never extrapolated backward into a low rank).
        v = _version(provision, 1, date(2014, 1, 1), None)
        _cons(edition, 5, date(2015, 1, 1), date(2015, 1, 1))
        _cons(edition, 6, date(2016, 1, 1), date(2016, 1, 1))
        status = derive_status(v, date(2014, 6, 1))
        assert status is not None
        assert status["rank"] == "unconfirmed"
        assert [c["role"] for c in status["consolidations"]] == ["following"]


class TestSuppression:
    def test_no_query_date_returns_none(
        self, provision: CodeEditionProvision
    ) -> None:
        v = _version(provision, 1, date(2014, 1, 1), None)
        assert derive_status(v, None) is None

    def test_never_in_force_version_returns_none(
        self, provision: CodeEditionProvision
    ) -> None:
        # Zero-width window (superseded the day it filed) → no rail.
        v = _version(provision, 1, date(2014, 1, 1), date(2014, 1, 1))
        assert derive_status(v, date(2014, 6, 1)) is None


class TestGeometry:
    """``rail_geometry`` positions, checked against the settled v8 mock numbers."""

    def test_covered_splits_the_line_solid_over_the_interval(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        v = _version(provision, 1, date(2012, 1, 1), date(2014, 1, 1))
        _cons(edition, 1, date(2012, 6, 1), date(2013, 9, 1))
        rail = build_rail(v, date(2013, 3, 1), _TODAY)
        assert rail is not None
        assert rail["rank"] == 1 and rail["rank_class"] == "r-cov"
        solids = [s for s in rail["segments"] if s["cls"] == "line-solid"]
        dashes = [s for s in rail["segments"] if s["cls"] == "line-dash"]
        assert len(solids) == 1 and len(dashes) == 2  # dashed flanks, solid middle
        assert 30 < solids[0]["left"] < 33  # ~31% (mock)
        assert 38 < solids[0]["width"] < 42  # ~40%
        assert rail["ring"] is None
        assert 54 < rail["qmark"] < 57  # ~55%
        assert rail["dividers"] == []

    def test_bracketed_is_fully_dashed_with_two_diamonds(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        v = _version(provision, 1, date(2014, 1, 1), date(2020, 1, 1))
        _cons(edition, 1, date(2015, 1, 1), date(2015, 1, 1))
        _cons(edition, 2, date(2018, 1, 1), date(2018, 1, 1))
        rail = build_rail(v, date(2016, 6, 1), _TODAY)
        assert rail is not None
        assert rail["rank"] == 2
        assert [s["cls"] for s in rail["segments"]] == ["line-dash"]
        # Two in-window zero-range points ⇒ two ◆ diamonds = four heads.
        assert len(rail["heads"]) == 4
        assert rail["ring"] is None

    def test_bracketed_reconstructed_parks_both_points_off_line(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        _version(provision, 1, date(2014, 6, 1), date(2015, 3, 1))
        v = _version(provision, 2, date(2015, 3, 1), date(2017, 1, 1))
        # A successor keeps the provision alive past the off-line following, so
        # the existence rule doesn't drop it (otherwise this collapses to rank 5).
        _version(provision, 3, date(2017, 1, 1), None)
        _cons(edition, 1, date(2015, 1, 1), date(2015, 1, 1))
        _cons(edition, 2, date(2018, 1, 1), date(2018, 1, 1))
        rail = build_rail(v, date(2016, 6, 1), _TODAY)
        assert rail is not None
        assert rail["rank"] == 3 and rail["rank_class"] == "r-rec"
        assert rail["ring"] == 18.0  # reconstructed From at the window start
        assert sorted(rail["dividers"]) == [12.0, 88.0]  # both gutters ruled off

    def test_open_tail_reconstructed_has_one_off_line_prior(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        _version(provision, 1, date(2014, 1, 1), date(2015, 3, 1))
        v = _version(provision, 2, date(2015, 3, 1), None)
        _cons(edition, 1, date(2014, 1, 1), date(2014, 12, 31))
        rail = build_rail(v, date(2026, 6, 17), _TODAY)
        assert rail is not None
        assert rail["rank"] == 5
        assert rail["ring"] == 18.0
        assert rail["dividers"] == [12.0]  # only the left gutter
        # The lone off-line prior is a single inward head, not a diamond.
        assert [h["cls"] for h in rail["heads"]] == ["cend"]


def _base(d: date, label: str = "O. Reg. 350/06") -> BaseInput:
    return {"date": d, "label": label, "url": "https://www.ontario.ca/laws/regulation/060350"}


class TestBaseRegulation:
    """The base regulation as a zero-range attestation candidate (the 'first
    consolidation'): it competes for covering/prior/following and renders — with a
    square glyph — only when selected, never as an always-on origin."""

    def test_base_version_at_enactment_is_verified_by_the_enacting_reg(
        self, provision: CodeEditionProvision
    ) -> None:
        v = _version(provision, 1, date(2012, 1, 1), None)  # base version
        status = derive_status(v, date(2012, 1, 1), base=_base(date(2012, 1, 1)))
        assert status is not None
        assert status["rank"] == 1
        assert status["reconstructed_from"] is False
        # The base reg is the covering attestation (zero-range, hit exactly).
        assert [(c["kind"], c["role"]) for c in status["consolidations"]] == [
            ("base", "covering")
        ]
        assert "enacting regulation" in status["status_text"]

    def test_base_version_past_enactment_is_open_tail_not_force_verified(
        self, provision: CodeEditionProvision
    ) -> None:
        # The enactment is a *point* attestation, so a later date with no consolidation
        # reads rank-4 open tail (honest: a missed amendment could have shortened it).
        v = _version(provision, 1, date(2012, 1, 1), None)  # base version, no e-Laws
        status = derive_status(v, date(2013, 6, 1), base=_base(date(2012, 1, 1)))
        assert status is not None
        assert status["rank"] == 4
        assert status["reconstructed_from"] is False
        assert [(c["kind"], c["role"]) for c in status["consolidations"]] == [
            ("base", "prior")
        ]
        assert "Enacted" in status["status_text"]

    def test_amended_version_with_later_prior_does_not_show_the_base(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        # A later e-Laws consolidation wins the "prior" slot, so the base reg — an
        # earlier candidate — is simply not selected and never renders. No overlap.
        _version(provision, 1, date(2012, 1, 1), date(2015, 1, 1))  # base version
        v = _version(provision, 2, date(2015, 1, 1), date(2020, 1, 1))  # amended
        _cons(edition, 1, date(2016, 1, 1), date(2016, 1, 1))
        _cons(edition, 2, date(2018, 1, 1), date(2018, 1, 1))
        status = derive_status(v, date(2017, 1, 1), base=_base(date(2012, 1, 1)))
        assert status is not None
        assert status["rank"] == 2
        assert all(c["kind"] == "consolidation" for c in status["consolidations"])
        assert {c["role"] for c in status["consolidations"]} == {"prior", "following"}

    def test_amended_version_no_elaws_shows_base_as_reconstructed_prior(
        self, provision: CodeEditionProvision
    ) -> None:
        # No e-Laws at all → the base reg is the only prior; it attests an *earlier*
        # version, so the date is rank-5 reconstructed, with the base shown off-line.
        _version(provision, 1, date(2012, 1, 1), date(2015, 1, 1))  # base version
        v = _version(provision, 2, date(2015, 1, 1), None)  # amended, current
        status = derive_status(v, date(2018, 1, 1), base=_base(date(2012, 1, 1)))
        assert status is not None
        assert status["rank"] == 5
        assert status["reconstructed_from"] is True
        assert [(c["kind"], c["role"]) for c in status["consolidations"]] == [
            ("base", "prior")
        ]
        assert status["consolidations"][0]["off_line"] == "left"

    def test_base_point_predating_the_provision_is_dropped(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        # The existence-rule guard: a base point dated before the provision
        # existed (here a 2012 edition base fed for a provision introduced 2020)
        # is dropped entirely. Production no longer feeds a stale edition base for
        # an added provision — the formatter passes the provision's own origin reg
        # (see test_added_provision_attested_by_its_origin_reg) — but the guard
        # still protects against a predating point however it arrives.
        v = _version(provision, 1, date(2020, 1, 1), None)
        _cons(edition, 1, date(2021, 1, 1), date(2021, 1, 1))
        status = derive_status(v, date(2020, 6, 1), base=_base(date(2012, 1, 1)))
        assert status is not None
        assert status["rank"] == "unconfirmed"
        assert all(c["kind"] == "consolidation" for c in status["consolidations"])

    def test_added_provision_attested_by_its_origin_reg(
        self, provision: CodeEditionProvision
    ) -> None:
        # An amend-add-created provision now receives its *own* introducing reg as
        # the base point (date == its enactment), so the existence rule keeps it
        # and it reads as an "Enacted by" open tail — the same shape a base
        # original gets from the edition base reg, not "unconfirmed".
        v = _version(provision, 0, date(2020, 1, 1), None)
        status = derive_status(
            v, date(2020, 6, 1), base=_base(date(2020, 1, 1), label="O. Reg. 593/99")
        )
        assert status is not None
        assert status["rank"] == 4
        assert status["reconstructed_from"] is False
        assert [(c["kind"], c["role"]) for c in status["consolidations"]] == [
            ("base", "prior")
        ]
        assert "Enacted by O. Reg. 593/99" in status["status_text"]

    def test_geometry_base_version_open_tail_square_dashed_no_ring(
        self, provision: CodeEditionProvision
    ) -> None:
        v = _version(provision, 1, date(2012, 1, 1), None)
        rail = build_rail(v, date(2013, 6, 1), _TODAY, base=_base(date(2012, 1, 1)))
        assert rail is not None
        assert rail["ring"] is None
        # A base square at From; the tail is dashed (the point attests only the instant).
        assert any(h["cls"] == "cbase" and h["left"] == 18.0 for h in rail["heads"])
        assert any(s["cls"] == "line-dash" for s in rail["segments"])

    def test_geometry_off_line_base_square_and_divider(
        self, provision: CodeEditionProvision
    ) -> None:
        # Amended version, no e-Laws → the base is the off-line-left reconstructed prior.
        _version(provision, 1, date(2012, 1, 1), date(2015, 1, 1))
        v = _version(provision, 2, date(2015, 1, 1), None)
        rail = build_rail(v, date(2018, 1, 1), _TODAY, base=_base(date(2012, 1, 1)))
        assert rail is not None
        assert any(h["cls"] == "cbase" and h["left"] == 6.0 for h in rail["heads"])
        assert 12.0 in rail["dividers"]
        assert rail["ring"] == 18.0  # reconstructed From


class TestRailTemplate:
    """The real _attestation_rail.html partial renders for the states (P2.5)."""

    def _render(self, rail: dict, from_commencement: object) -> str:
        return render_to_string(
            "partials/_attestation_rail.html",
            {"result": {"rail": rail, "from_commencement": from_commencement}},
        )

    def test_covered_renders_solid_line_chip_and_link(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        v = _version(provision, 1, date(2012, 1, 1), date(2014, 1, 1))
        _cons(edition, 1, date(2012, 6, 1), date(2013, 9, 1))
        rail = build_rail(v, date(2013, 3, 1), _TODAY)
        assert rail is not None
        html = self._render(rail, None)
        assert "vr-chip r-cov" in html
        assert "line-solid" in html
        assert "mk-ring" not in html  # covered is not reconstructed → no ring
        assert "120332/v1" in html  # the covering consolidation is a link

    def test_reconstructed_renders_ring_and_start(
        self, edition: CodeEdition, provision: CodeEditionProvision
    ) -> None:
        _version(provision, 1, date(2014, 1, 1), date(2015, 3, 1))
        v = _version(provision, 2, date(2015, 3, 1), None)
        _cons(edition, 1, date(2014, 1, 1), date(2014, 12, 31))
        rail = build_rail(v, date(2026, 6, 17), _TODAY)
        assert rail is not None
        html = self._render(rail, {"stub": True})  # truthy from_commencement
        assert "vr-chip r-rec" in html
        assert "mk-ring" in html
        assert "Start" in html  # the in-force-start commencement drill-down shows
