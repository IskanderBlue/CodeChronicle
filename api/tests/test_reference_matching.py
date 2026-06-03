"""Tests for segment-aware provision/table reference matching in the engine.

These cover the unified reference check that replaced the old
substring-based provision_ref + exact_id branches.
"""

from datetime import date

import pytest

from api.search.engine import _match_reference, _ref_parts, score_versions
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvinceCode,
    ProvisionVersionTable,
)


class TestRefParts:
    """Normalization of references and table ids into segment tuples."""

    def test_plain_provision_with_trailing_dot(self):
        assert _ref_parts("9.10.14.") == (False, ("9", "10", "14"))

    def test_table_hyphen_prefix(self):
        assert _ref_parts("Table-3.1.4.7.") == (True, ("3", "1", "4", "7"))

    def test_table_space_prefix(self):
        assert _ref_parts("Table 3.1.4.7") == (True, ("3", "1", "4", "7"))

    def test_division_letter_prefix_is_dropped(self):
        assert _ref_parts("A-3.1.2") == (False, ("3", "1", "2"))

    def test_trailing_clause_suffix_is_stripped(self):
        assert _ref_parts("3.2.1(1)") == (False, ("3", "2", "1"))


class TestMatchReference:
    """The single segment-aware matcher."""

    def test_exact_is_highest(self):
        assert _match_reference("3.2.7.1", "3.2.7.1.", []) == (3.0, "exact_id")

    def test_resolved_table_equals_exact(self):
        table_segs = [("3", "1", "4", "7")]
        assert _match_reference("table-3.1.4.7", "9.9.9.", table_segs) == (3.0, "table_ref")

    def test_table_reference_misses_when_table_absent(self):
        assert _match_reference("table-9.9.9", "3.1.4.7.", [("3", "1", "4", "7")]) is None

    def test_ancestor_matches_descendant_and_decays(self):
        near = _match_reference("3.2", "3.2.9.", [])
        far = _match_reference("3.2", "3.2.9.1.", [])
        # Same parent reference, deeper descendant scores lower (2.0 > 1.75).
        assert near == (2.0, "ancestor_id")
        assert far == (1.75, "ancestor_id")

    def test_segment_boundaries_are_respected(self):
        # The substring bug these replace: "1." used to match "11.2.1".
        assert _match_reference("1.2", "11.2.1.", []) is None
        assert _match_reference("1.2", "1.21.", []) is None
        assert _match_reference("2", "1.2.1.", []) is None

    def test_bare_id_does_not_match_a_table(self):
        # Only a "table-"/"Table " prefixed reference resolves against tables.
        assert _match_reference("3.1.4.7", "9.9.9.", [("3", "1", "4", "7")]) is None


@pytest.fixture
def edition_with_table(db):
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)
    edition = CodeEdition.objects.create(
        code=code, edition_id="2024", year=2024,
        effective_date=date(2024, 1, 1),
    )
    provision = CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.1.4.", level="article",
    )
    version = CodeEditionProvisionVersion.objects.create(
        provision=provision, version=0,
        effective_date=date(2024, 1, 1),
        title="Spatial Separation",
        keyword_counts={"fire": 1},
    )
    ProvisionVersionTable.objects.create(
        version=version, table_id="Table-3.1.4.7.", order=0,
    )
    return edition


@pytest.mark.django_db
def test_table_reference_resolves_through_score_versions(edition_with_table):
    """A 'Table-...' reference surfaces the owning provision at the top score."""
    qs = CodeEditionProvisionVersion.objects.filter(
        provision__edition=edition_with_table,
    ).select_related("provision__edition__code")

    results = score_versions(
        "", qs, {}, provision_references=["table-3.1.4.7"],
    )

    assert len(results) == 1
    assert results[0]["id"] == "3.1.4."
    assert results[0]["score"] == 3.0
    assert results[0]["match_type"] == "table_ref"


@pytest.mark.django_db
def test_refs_only_all_unparseable_returns_empty_without_scanning(
    edition_with_table, django_assert_num_queries
):
    """A refs-only query whose references all normalize to no segments must
    return [] without touching the DB.  Before the early-return guard, the
    empty Q matched the entire corpus and every in-force version was fetched
    and scored only to be discarded."""
    qs = CodeEditionProvisionVersion.objects.all()
    # "A-" -> (False, ()) : a division prefix with no dotted core, so the
    # engine skips it and the filter Q stays empty.
    with django_assert_num_queries(0):
        results = score_versions("", qs, {}, provision_references=["A-"])
    assert results == []
