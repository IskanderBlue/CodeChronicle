"""Tests for the lineage resolver (``core.provision_lineage``).

Fixture corpus: three OBC editions — 1997 (division-less), 2006, 2012
(open-ended/current).  Only the 2006→2012 transition is covered by an
``EditionTransition``; 1997→2006 is deliberately unmapped so the
no-data-yet states are exercised on a *real* in-corpus boundary, not just
at the corpus edges.
"""

from datetime import date, timedelta
from typing import Any

import pytest

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EditionTransition,
    ProvisionMapping,
)
from core.provision_lineage import (
    DISCONTINUED,
    ENDPOINT,
    LINKED,
    NO_DATA_YET,
    resolve_lineage,
)


def _provision(
    edition: CodeEdition, provision_id: str, division: str, n_versions: int = 1
) -> CodeEditionProvision:
    prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id=provision_id,
        level="article", division=division,
    )
    for v in range(n_versions):
        CodeEditionProvisionVersion.objects.create(
            provision=prov, version=v,
            effective_date=edition.effective_date + timedelta(days=30 * v),
        )
    return prov


@pytest.fixture
def lineage_fixtures(db):
    code = Code.objects.create(
        code="OBC", display_name="Ontario Building Code",
        first_edition_date=date(1975, 12, 31),
    )
    e1997 = CodeEdition.objects.create(
        code=code, edition_id="1997", year=1997,
        effective_date=date(1998, 4, 6), ineffective_date=date(2006, 12, 31),
    )
    e2006 = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006,
        effective_date=date(2006, 12, 31), ineffective_date=date(2014, 1, 1),
    )
    e2012 = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012,
        effective_date=date(2014, 1, 1),  # open-ended: the current edition
    )
    # Search-metadata-only editions (no provisions) interleave the real ones
    # in code_editions — they must be invisible to lineage adjacency.  One
    # sits between 2006 and 2012, one after 2012; with these present, every
    # adjacency/endpoint assertion below exercises the provision-bearing
    # filter (e.g. 2006's neighbour must stay 2012, and the trailing stub
    # must not demote 2012's successor endpoint to "no data yet").
    CodeEdition.objects.create(
        code=code, edition_id="2006_v04", year=2006,
        effective_date=date(2007, 4, 2),
    )
    CodeEdition.objects.create(
        code=code, edition_id="2024", year=2024,
        effective_date=date(2025, 1, 1),
    )
    EditionTransition.objects.create(old_edition=e2006, new_edition=e2012)

    fx: dict[str, Any] = {
        "code": code, "e1997": e1997, "e2006": e2006, "e2012": e2012,
        # 1997 is division-less; same id exists in 2006 but the transition
        # is uncovered, so no same-id guess may be made.
        "p97_sameid": _provision(e1997, "4.2.2.2.", ""),
        # Cross-edition renumber (2 versions on the old side: link the last).
        "p06_renum_old": _provision(e2006, "9.10.18.6.", "B", n_versions=2),
        "p12_renum_new": _provision(e2012, "9.10.18.7.", "B"),
        # Split: one 2006 provision → two 2012 provisions across divisions.
        "p06_split": _provision(e2006, "3.1.1.1.", "B"),
        "p12_split_b": _provision(e2012, "3.1.1.2.", "B"),
        "p12_split_c": _provision(e2012, "3.1.1.3.", "C"),
        # Same-id continuation on the covered transition; the id also
        # exists in Division A of 2012 to exercise the division preference.
        "p06_sameid": _provision(e2006, "4.2.2.2.", "B"),
        "p12_sameid": _provision(e2012, "4.2.2.2.", "B"),
        "p12_sameid_a": _provision(e2012, "4.2.2.2.", "A"),
        # Discontinued after 2006 (covered, no row, no same-id in 2012).
        "p06_disc": _provision(e2006, "5.5.5.5.", "B"),
        # New in 2012 (covered, no row, no same-id in 2006).
        "p12_new": _provision(e2012, "8.8.8.8.", "B"),
        # Intra-edition renumber inside 2012: old id hands off to the new
        # id's v1, recorded as introduced_by_version.
        "p12_intra_old": _provision(e2012, "9.5.1.1.", "B"),
        "p12_intra_new": _provision(e2012, "9.5.2.1.", "B", n_versions=2),
    }

    ProvisionMapping.objects.create(
        old_provision=fx["p06_renum_old"], new_provision=fx["p12_renum_new"],
        mapping_type="renumbered",
    )
    ProvisionMapping.objects.create(
        old_provision=fx["p06_split"], new_provision=fx["p12_split_b"],
        mapping_type="split",
    )
    ProvisionMapping.objects.create(
        old_provision=fx["p06_split"], new_provision=fx["p12_split_c"],
        mapping_type="split",
    )
    ProvisionMapping.objects.create(
        old_provision=fx["p12_intra_old"], new_provision=fx["p12_intra_new"],
        mapping_type="renumbered",
        introduced_by_version=fx["p12_intra_new"].versions.get(version=1),
    )
    return fx


def _resolve_one(prov: CodeEditionProvision):
    return resolve_lineage([prov])[prov.pk]


@pytest.mark.django_db
class TestMappedLinks:
    def test_renumbered_successor_links_v0_of_new_provision(self, lineage_fixtures):
        lineage = _resolve_one(lineage_fixtures["p06_renum_old"])
        succ = lineage.successors
        assert succ.state == LINKED
        assert len(succ.links) == 1
        link = succ.links[0]
        assert link.provision == lineage_fixtures["p12_renum_new"]
        assert link.mapping_type == "renumbered"
        assert link.same_id is False
        assert link.same_edition is False
        assert link.version == 0  # birth in the new edition
        assert link.url == "/provision/OBC_2012/B/9.10.18.7./v0/"

    def test_renumbered_predecessor_links_last_version_of_old(self, lineage_fixtures):
        lineage = _resolve_one(lineage_fixtures["p12_renum_new"])
        pred = lineage.predecessors
        assert pred.state == LINKED
        assert len(pred.links) == 1
        link = pred.links[0]
        assert link.provision == lineage_fixtures["p06_renum_old"]
        assert link.version == 1  # the version that handed off
        assert link.url == "/provision/OBC_2006/B/9.10.18.6./v1/"

    def test_split_fans_out_to_multiple_links(self, lineage_fixtures):
        succ = _resolve_one(lineage_fixtures["p06_split"]).successors
        assert succ.state == LINKED
        # Sorted by (division, id) — and the second target crosses into
        # Division C, so the URL must carry the *target's* division.
        assert [li.provision for li in succ.links] == [
            lineage_fixtures["p12_split_b"], lineage_fixtures["p12_split_c"],
        ]
        assert succ.links[1].url == "/provision/OBC_2012/C/3.1.1.3./v0/"

    def test_intra_edition_renumber_is_a_successor_row(self, lineage_fixtures):
        succ = _resolve_one(lineage_fixtures["p12_intra_old"]).successors
        assert succ.state == LINKED
        link = succ.links[0]
        assert link.same_edition is True
        assert link.provision == lineage_fixtures["p12_intra_new"]
        # Targets the exact version that materialised the renumber.
        assert link.version == 1
        assert link.url == "/provision/OBC_2012/B/9.5.2.1./v1/"

    def test_intra_edition_renumber_back_link(self, lineage_fixtures):
        pred = _resolve_one(lineage_fixtures["p12_intra_new"]).predecessors
        assert pred.state == LINKED
        link = pred.links[0]
        assert link.same_edition is True
        assert link.provision == lineage_fixtures["p12_intra_old"]


@pytest.mark.django_db
class TestSameIdFallback:
    def test_same_id_continues_on_covered_transition(self, lineage_fixtures):
        succ = _resolve_one(lineage_fixtures["p06_sameid"]).successors
        assert succ.state == LINKED
        link = succ.links[0]
        assert link.same_id is True
        assert link.mapping_type == ""
        # Division preference: the source's own division (B) wins over the
        # Division A homonym.
        assert link.provision == lineage_fixtures["p12_sameid"]

    def test_same_id_back_link(self, lineage_fixtures):
        pred = _resolve_one(lineage_fixtures["p12_sameid"]).predecessors
        assert pred.state == LINKED
        assert pred.links[0].same_id is True
        assert pred.links[0].provision == lineage_fixtures["p06_sameid"]

    def test_same_id_not_trusted_on_uncovered_transition(self, lineage_fixtures):
        # "4.2.2.2." exists in 2006 too, but 1997→2006 is unmapped: the id
        # may have been renumbered away or reused, so never guess.
        succ = _resolve_one(lineage_fixtures["p97_sameid"]).successors
        assert succ.state == NO_DATA_YET
        assert succ.links == []
        assert succ.edition == lineage_fixtures["e2006"]


@pytest.mark.django_db
class TestMarkerStates:
    def test_discontinued_after_covered_transition(self, lineage_fixtures):
        succ = _resolve_one(lineage_fixtures["p06_disc"]).successors
        assert succ.state == DISCONTINUED
        assert succ.edition == lineage_fixtures["e2012"]

    def test_new_in_edition_is_discontinued_predecessor(self, lineage_fixtures):
        pred = _resolve_one(lineage_fixtures["p12_new"]).predecessors
        assert pred.state == DISCONTINUED
        assert pred.edition == lineage_fixtures["e2006"]

    def test_predecessor_no_data_on_uncovered_transition(self, lineage_fixtures):
        pred = _resolve_one(lineage_fixtures["p06_disc"]).predecessors
        assert pred.state == NO_DATA_YET
        assert pred.edition == lineage_fixtures["e1997"]


@pytest.mark.django_db
class TestEndpoints:
    def test_open_ended_newest_edition_is_successor_endpoint(self, lineage_fixtures):
        succ = _resolve_one(lineage_fixtures["p12_new"]).successors
        assert succ.state == ENDPOINT
        assert succ.edition is None

    def test_closed_newest_edition_means_unmapped_successor(self, lineage_fixtures):
        # A closed newest edition means a real successor exists that we
        # haven't loaded — the corpus edge is just an uncovered transition.
        e2012 = lineage_fixtures["e2012"]
        e2012.ineffective_date = date(2025, 1, 1)
        e2012.save()
        succ = _resolve_one(lineage_fixtures["p12_new"]).successors
        assert succ.state == NO_DATA_YET

    def test_earliest_edition_defaults_to_no_data(self, lineage_fixtures):
        # OBC's real first edition (1975) predates the corpus, so the
        # earliest *loaded* edition is not a predecessor endpoint.
        pred = _resolve_one(lineage_fixtures["p97_sameid"]).predecessors
        assert pred.state == NO_DATA_YET

    def test_first_edition_ever_is_predecessor_endpoint(self, lineage_fixtures):
        code = lineage_fixtures["code"]
        code.first_edition_date = lineage_fixtures["e1997"].effective_date
        code.save()
        pred = _resolve_one(lineage_fixtures["p97_sameid"]).predecessors
        assert pred.state == ENDPOINT
        assert pred.edition is None

    def test_unseeded_first_edition_date_stays_honest(self, lineage_fixtures):
        code = lineage_fixtures["code"]
        code.first_edition_date = None
        code.save()
        pred = _resolve_one(lineage_fixtures["p97_sameid"]).predecessors
        assert pred.state == NO_DATA_YET


@pytest.mark.django_db
class TestBatching:
    def test_empty_input(self):
        assert resolve_lineage([]) == {}

    def test_whole_corpus_in_bounded_queries(
        self, lineage_fixtures, django_assert_max_num_queries
    ):
        provisions = list(CodeEditionProvision.objects.all())
        # editions' code ids + edition chains + coverage + mappings +
        # same-id candidates + version bounds = 6, independent of N.
        with django_assert_max_num_queries(6):
            lineage = resolve_lineage(provisions)
        assert set(lineage) == {p.pk for p in provisions}
