"""Tests for BM25 keyword scoring in the search engine."""

from datetime import date

import pytest

from api.search.engine import (
    BM25_K1,
    CorpusStats,
    _bm25_tf,
    compute_corpus_stats,
    score_versions,
)
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvinceCode,
)


@pytest.fixture
def edition_with_provisions(db):
    """Create an edition with provisions for BM25 scoring tests."""
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


def test_bm25_tf_anchors_at_one():
    """A single occurrence at corpus-average length scores exactly 1.0.

    Same anchor as the old ``1 + log(tf)`` scheme, so a perfect match on the
    typed words still lands at ~1.0 after query-side normalization.
    """
    assert _bm25_tf("fire", {"fire": 1}, length_norm=1.0) == pytest.approx(1.0)


def test_bm25_tf_saturates_below_ceiling():
    """Repetition helps less and less and never exceeds k1 + 1."""
    low = _bm25_tf("fire", {"fire": 2}, length_norm=1.0)
    mid = _bm25_tf("fire", {"fire": 8}, length_norm=1.0)
    high = _bm25_tf("fire", {"fire": 269}, length_norm=1.0)
    assert 1.0 < low < mid < high < BM25_K1 + 1
    # The 8th-to-269th occurrences buy less than the 1st-to-8th did.
    assert (high - mid) < (mid - low)


def test_bm25_tf_penalizes_long_documents():
    """The same count is worth less in a document far above average length."""
    counts = {"fire": 8}
    at_avg = _bm25_tf("fire", counts, length_norm=1.0)
    long_doc = _bm25_tf("fire", counts, length_norm=10.0)
    short_doc = _bm25_tf("fire", counts, length_norm=0.5)
    assert long_doc < at_avg < short_doc


def test_bm25_tf_zero_for_missing_term():
    """TF returns 0 for terms not in the counts dict."""
    assert _bm25_tf("absent", {"fire": 5}, length_norm=1.0) == 0.0
    assert _bm25_tf("anything", {}, length_norm=1.0) == 0.0


@pytest.mark.django_db
def test_bm25_ranks_rare_repeated_term_higher(edition_with_provisions):
    """A provision mentioning a rare term many times should rank higher."""
    edition = edition_with_provisions
    qs = CodeEditionProvisionVersion.objects.filter(
        provision__edition=edition,
    ).select_related("provision__edition__code").prefetch_related(
        "contributing_clauses__regulation",
    )

    corpus_stats = compute_corpus_stats(qs)
    results = score_versions("fire sprinkler", qs, corpus_stats)

    assert len(results) == 2
    # Provision B should rank higher: more "fire" mentions and has "sprinkler"
    assert results[0]["id"] == "3.1.8.5."
    assert results[1]["id"] == "3.1.1.1."


@pytest.mark.django_db
def test_bm25_works_with_single_provision(edition_with_provisions):
    """Search should work when only one provision matches."""
    edition = edition_with_provisions

    qs = CodeEditionProvisionVersion.objects.filter(
        provision__edition=edition,
    ).select_related("provision__edition__code").prefetch_related(
        "contributing_clauses__regulation",
    )

    corpus_stats = compute_corpus_stats(qs)
    results = score_versions("sprinkler", qs, corpus_stats)

    assert len(results) == 1
    assert results[0]["id"] == "3.1.8.5."
    assert results[0]["score"] > 0


@pytest.mark.django_db
def test_compute_corpus_stats_returns_weights(edition_with_provisions):
    """compute_corpus_stats returns IDF weights and the average doc length."""
    edition = edition_with_provisions

    qs = CodeEditionProvisionVersion.objects.filter(provision__edition=edition)
    corpus_stats = compute_corpus_stats(qs)

    # "fire" appears in both docs → lower IDF
    # "sprinkler" appears in one doc → higher IDF
    assert "fire" in corpus_stats.idf
    assert "sprinkler" in corpus_stats.idf
    assert corpus_stats.idf["sprinkler"] > corpus_stats.idf["fire"]
    # Doc lengths are 11 tokens each (1+10 and 8+3).
    assert corpus_stats.avg_doc_len == pytest.approx(11.0)


@pytest.mark.django_db
def test_compute_corpus_stats_empty_corpus():
    """compute_corpus_stats returns empty stats for an empty queryset."""
    qs = CodeEditionProvisionVersion.objects.none()
    assert compute_corpus_stats(qs) == CorpusStats()


@pytest.mark.django_db
def test_kitchen_sink_provision_does_not_outrank_focused_one():
    """Regression: an index-like mega-provision must not win every query.

    Models OBC 11.5.1.1 "Compliance Alternatives" — ~6,900 tokens mentioning
    every topic in the code at high counts — versus a short article actually
    about the queried topic.  Under unnormalized 1+log(tf) the mega-provision
    top-ranked any query; BM25's length factor makes it need proportionally
    more evidence than the focused article.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)
    edition = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012,
        effective_date=date(2014, 1, 1),
    )

    def make_version(provision_id: str, title: str, counts: dict[str, int]):
        prov = CodeEditionProvision.objects.create(
            edition=edition, provision_id=provision_id, level="article",
        )
        CodeEditionProvisionVersion.objects.create(
            provision=prov, version=0,
            effective_date=date(2014, 1, 1),
            title=title, keyword_counts=counts,
        )

    # Real 11.5.1.1 proportions: the query terms at high counts inside a
    # ~6,900-token document.
    make_version("11.5.1.1.", "Compliance Alternatives", {
        "fire": 269, "separation": 86, "dwelling": 59, "units": 42,
        "filler": 6444,
    })
    # The provision a user asking about dwelling-unit fire separations wants.
    make_version("9.10.9.14.", "Fire Separations between Dwelling Units", {
        "fire": 5, "separation": 4, "dwelling": 2, "units": 2, "rating": 3,
    })
    # Background corpus of ordinary short provisions: anchors avg_doc_len at
    # realistic levels (most provisions are short; the mega-table is the
    # outlier) without matching the query themselves.
    for i in range(30):
        make_version(f"4.1.{i + 1}.1.", f"Ordinary Provision {i + 1}", {
            "loads": 10, "structural": 10, "design": 10,
        })

    qs = CodeEditionProvisionVersion.objects.filter(provision__edition=edition)
    corpus_stats = compute_corpus_stats(qs)
    results = score_versions("fire separation dwelling units", qs, corpus_stats)

    assert [r["id"] for r in results[:2]] == ["9.10.9.14.", "11.5.1.1."]


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
    corpus_stats = compute_corpus_stats(qs)

    results = score_versions(
        "defined definitions terms", qs, corpus_stats, raw_query="defined terms",
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
    corpus_stats = compute_corpus_stats(qs)

    raw_aware = score_versions(
        "defined definitions terms", qs, corpus_stats, raw_query="defined terms",
    )[0]["score"]
    # tf=1 for both typed terms in the (single, hence average-length) doc →
    # idf-weighted mean of tf == 1.0, undiluted by the LLM's extra variant.
    assert raw_aware == pytest.approx(1.0)
