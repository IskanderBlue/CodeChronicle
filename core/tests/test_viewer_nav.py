"""Viewer edition-nav partial (``viewer_edition_nav``) — lineage rows.

The endpoint renders the resolver's predecessor/successor rows for the
viewed provision: linked rows are in-viewer load buttons (the
``data-edition-result`` payload), marker states render as plain rows.
The free-tier locked branch is covered in ``test_access.py``.
"""

from datetime import date

import pytest
from django.test import Client

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EditionTransition,
    ProvisionDisposition,
    ProvisionMapping,
)

NAV_URL = "/viewer/edition-nav/"


def _provision(
    edition: CodeEdition, provision_id: str, division: str, title: str = ""
) -> CodeEditionProvision:
    prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id=provision_id, level="article", division=division,
    )
    CodeEditionProvisionVersion.objects.create(
        provision=prov, version=0, title=title,
        effective_date=edition.effective_date,
    )
    return prov


@pytest.fixture
def nav_fixtures(db):
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    e2006 = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006,
        effective_date=date(2006, 12, 31), ineffective_date=date(2014, 1, 1),
    )
    e2012 = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012,
        effective_date=date(2014, 1, 1),  # open-ended: the current edition
    )
    EditionTransition.objects.create(old_edition=e2006, new_edition=e2012)
    old = _provision(e2006, "9.10.18.6.", "B", title="Smoke Alarms (old)")
    new = _provision(e2012, "9.10.18.7.", "B", title="Smoke Alarms")
    ProvisionMapping.objects.create(
        old_provision=old, new_provision=new, mapping_type="renumbered",
    )
    # Identity carry: CCM's total mapping asserts the same-number
    # continuation with an explicit row (number equality alone never links).
    sameid_old = _provision(e2006, "4.2.2.2.", "B")
    sameid_new = _provision(e2012, "4.2.2.2.", "B")
    ProvisionMapping.objects.create(
        old_provision=sameid_old, new_provision=sameid_new,
        mapping_type="renumbered",
    )
    disc = _provision(e2006, "5.5.5.5.", "B")
    # One split verdict, two legs (the real 2006 B 12.3.4.6.): a row into
    # 2012 plus a not_processed disposition for the out-of-corpus leg.
    multi = _provision(e2006, "12.3.4.6.", "B")
    multi_new = _provision(e2012, "12.3.1.4.", "B", title="Hot Water Piping Insulation")
    ProvisionMapping.objects.create(
        old_provision=multi, new_provision=multi_new, mapping_type="split",
    )
    ProvisionDisposition.objects.create(
        provision=multi, new_edition=e2012,
        status=ProvisionDisposition.Status.NOT_PROCESSED,
        target_reference="SB-10",
    )
    return {
        "e2006": e2006, "e2012": e2012, "old": old, "new": new,
        "sameid_old": sameid_old, "sameid_new": sameid_new, "disc": disc,
    }


@pytest.mark.django_db
class TestViewerEditionNav:
    def test_mapped_successor_renders_load_button(self, client: Client, nav_fixtures):
        content = client.get(NAV_URL, {
            "code": "OBC_2006", "provision_id": "9.10.18.6.", "division": "B",
        }).content.decode()
        assert "renumbered to" in content
        assert "9.10.18.7." in content
        assert "data-edition-result" in content
        # Payload identifies the target, not the source.
        assert '"code":"OBC_2012"' in content
        assert '"title":"Smoke Alarms"' in content

    def test_mapped_predecessor_renders_load_button(self, client: Client, nav_fixtures):
        content = client.get(NAV_URL, {
            "code": "OBC_2012", "provision_id": "9.10.18.7.", "division": "B",
        }).content.decode()
        assert "renumbered from" in content
        assert '"code":"OBC_2006"' in content
        # 2012 is the open-ended newest edition → successor side is explicit
        # in the dedicated lineage box.
        assert "Current edition" in content

    def test_same_id_row_uses_continues_verb(self, client: Client, nav_fixtures):
        content = client.get(NAV_URL, {
            "code": "OBC_2006", "provision_id": "4.2.2.2.", "division": "B",
        }).content.decode()
        assert "continues as" in content
        # The verb carries the meaning; no "(same number)" suffix.
        assert "(same number)" not in content

    def test_outside_corpus_leg_renders_alongside_link(
        self, client: Client, nav_fixtures
    ):
        content = client.get(NAV_URL, {
            "code": "OBC_2006", "provision_id": "12.3.4.6.", "division": "B",
        }).content.decode()
        # Both legs of the split verdict: the in-corpus load button AND
        # the out-of-corpus marker row, naming the target document.
        assert "split into" in content
        assert "12.3.1.4." in content
        assert "data-edition-result" in content
        assert "Some content moved to SB-10, not yet covered" in content

    def test_discontinued_marker_no_button(self, client: Client, nav_fixtures):
        content = client.get(NAV_URL, {
            "code": "OBC_2006", "provision_id": "5.5.5.5.", "division": "B",
        }).content.decode()
        assert "Discontinued" in content
        assert "no OBC 2012 successor" in content
        assert "data-edition-result" not in content

    def test_uncovered_transition_reads_not_yet_mapped(
        self, client: Client, nav_fixtures
    ):
        # Predecessor side of 2006: nothing earlier is loaded.
        content = client.get(NAV_URL, {
            "code": "OBC_2006", "provision_id": "9.10.18.6.", "division": "B",
        }).content.decode()
        assert "Earlier editions not yet mapped" in content

    def test_unknown_provision_renders_fallback(self, client: Client, nav_fixtures):
        content = client.get(NAV_URL, {
            "code": "OBC_2006", "provision_id": "0.0.0.0.", "division": "B",
        }).content.decode()
        assert "No lineage is available" in content
