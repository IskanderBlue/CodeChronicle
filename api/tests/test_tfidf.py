"""Tests for TF-IDF keyword scoring in the search engine."""

from datetime import date

import pytest

from api.search.engine import _tf, compute_idf, score_versions
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvinceCode,
)


@pytest.fixture
def edition_with_provisions(db):
    """Create an edition with provisions for TF-IDF testing."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)
    edition = CodeEdition.objects.create(
        code=code, edition_id="2024", year=2024,
        effective_date=date(2024, 1, 1),
    )
    prov_a = CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.1.1.1.", level="article",
    )
    prov_b = CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.1.8.5.", level="article",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=prov_a, version=0,
        effective_date=date(2024, 1, 1),
        title="General Building",
        keyword_counts={"fire": 1, "building": 10},
    )
    CodeEditionProvisionVersion.objects.create(
        provision=prov_b, version=0,
        effective_date=date(2024, 1, 1),
        title="Fire Sprinkler Systems",
        keyword_counts={"fire": 8, "sprinkler": 3},
    )
    return edition


def test_tf_log_normalization():
    """TF function should use log-normalized term frequency."""
    counts = {"fire": 1, "sprinkler": 8, "building": 10}
    assert _tf("fire", counts) == pytest.approx(1.0)  # 1 + log(1) = 1.0
    assert _tf("sprinkler", counts) > _tf("fire", counts)  # log(8) > log(1)
    assert _tf("missing", counts) == 0.0


def test_tf_zero_for_missing_term():
    """TF returns 0 for terms not in the counts dict."""
    assert _tf("absent", {"fire": 5}) == 0.0
    assert _tf("anything", {}) == 0.0


@pytest.mark.django_db
def test_tfidf_ranks_rare_repeated_term_higher(edition_with_provisions):
    """A provision mentioning a rare term many times should rank higher."""
    edition = edition_with_provisions
    qs = CodeEditionProvisionVersion.objects.filter(
        provision__edition=edition,
    ).select_related("provision__edition__code").prefetch_related(
        "contributing_clauses__regulation",
    )

    idf_map = compute_idf(qs)
    results = score_versions("fire sprinkler", qs, idf_map)

    assert len(results) == 2
    # Provision B should rank higher: more "fire" mentions and has "sprinkler"
    assert results[0]["id"] == "3.1.8.5."
    assert results[1]["id"] == "3.1.1.1."


@pytest.mark.django_db
def test_tfidf_works_with_single_provision(edition_with_provisions):
    """Search should work when only one provision matches."""
    edition = edition_with_provisions

    qs = CodeEditionProvisionVersion.objects.filter(
        provision__edition=edition,
    ).select_related("provision__edition__code").prefetch_related(
        "contributing_clauses__regulation",
    )

    idf_map = compute_idf(qs)
    results = score_versions("sprinkler", qs, idf_map)

    assert len(results) == 1
    assert results[0]["id"] == "3.1.8.5."
    assert results[0]["score"] > 0


@pytest.mark.django_db
def test_compute_idf_returns_weights(edition_with_provisions):
    """compute_idf should return IDF weights for keywords in the corpus."""
    edition = edition_with_provisions

    qs = CodeEditionProvisionVersion.objects.filter(provision__edition=edition)
    idf_map = compute_idf(qs)

    # "fire" appears in both docs → lower IDF
    # "sprinkler" appears in one doc → higher IDF
    assert "fire" in idf_map
    assert "sprinkler" in idf_map
    assert idf_map["sprinkler"] > idf_map["fire"]


@pytest.mark.django_db
def test_compute_idf_empty_corpus():
    """compute_idf returns empty dict for empty queryset."""
    qs = CodeEditionProvisionVersion.objects.none()
    assert compute_idf(qs) == {}


@pytest.mark.django_db
def test_raw_query_splits_direct_from_llm_added_terms():
    """LLM-added keyword variants are classified indirect, not direct.

    Mirrors the "defined terms" case: the parser emits the family
    defined/definition/definitions/terms, but the user only typed two of them.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)
    edition = CodeEdition.objects.create(
        code=code, edition_id="2024", year=2024,
        effective_date=date(2024, 1, 1),
    )
    prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.4.1.", level="article",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=prov, version=0,
        effective_date=date(2024, 1, 1),
        title="Defined Terms",
        keyword_counts={"defined": 3, "definitions": 1, "terms": 4},
    )
    qs = CodeEditionProvisionVersion.objects.filter(provision__edition=edition)
    idf_map = compute_idf(qs)

    results = score_versions(
        "defined definitions terms", qs, idf_map, raw_query="defined terms",
    )

    assert len(results) == 1
    r = results[0]
    assert r["match_type"] == "exact"
    # Only the typed words are direct; the LLM-added plural is indirect.
    assert r["matched_terms"] == ["defined", "terms"]
    assert "definitions" in r["matched_terms_indirect"]
    assert "definitions" not in r["matched_terms"]


@pytest.mark.django_db
def test_full_typed_match_not_diluted_by_llm_variants():
    """A full match on the typed words scores ~1.0, not halved by extra variants.

    Without raw-query awareness the 4-term denominator would make a perfect
    'defined terms' match look like a 50% partial match.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)
    edition = CodeEdition.objects.create(
        code=code, edition_id="2024", year=2024,
        effective_date=date(2024, 1, 1),
    )
    prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.4.2.", level="article",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=prov, version=0,
        effective_date=date(2024, 1, 1),
        title="Defined Terms",
        keyword_counts={"defined": 1, "terms": 1},
    )
    qs = CodeEditionProvisionVersion.objects.filter(provision__edition=edition)
    idf_map = compute_idf(qs)

    raw_aware = score_versions(
        "defined definitions terms", qs, idf_map, raw_query="defined terms",
    )[0]["score"]
    # tf=1 for both typed terms → idf-weighted mean of tf == 1.0, undiluted.
    assert raw_aware == pytest.approx(1.0)
