"""Tests for BM25 keyword scoring in the search engine."""

from datetime import date

import pytest

from api.search.engine import (
    BM25_K1,
    BM25F_TITLE_WEIGHT,
    CorpusStats,
    _bm25_saturate,
    _bm25f_tf,
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


def _body_tf(term: str, counts: dict, norm: float) -> float:
    """``_bm25f_tf`` with no title field — the body-only case."""
    return _bm25f_tf(term, counts, {}, body_norm=norm, title_norm=1.0)


def test_bm25_tf_anchors_at_one():
    """A single occurrence at corpus-average length scores exactly 1.0.

    Same anchor as the old ``1 + log(tf)`` scheme, so a perfect match on the
    typed words still lands at ~1.0 after query-side normalization.
    """
    assert _body_tf("fire", {"fire": 1}, norm=1.0) == pytest.approx(1.0)


def test_bm25_tf_saturates_below_ceiling():
    """Repetition helps less and less and never exceeds k1 + 1."""
    low = _body_tf("fire", {"fire": 2}, norm=1.0)
    mid = _body_tf("fire", {"fire": 8}, norm=1.0)
    high = _body_tf("fire", {"fire": 269}, norm=1.0)
    assert 1.0 < low < mid < high < BM25_K1 + 1
    # The 8th-to-269th occurrences buy less than the 1st-to-8th did.
    assert (high - mid) < (mid - low)


def test_bm25_tf_penalizes_long_documents():
    """The same count is worth less in a document far above average length."""
    counts = {"fire": 8}
    at_avg = _body_tf("fire", counts, norm=1.0)
    long_doc = _body_tf("fire", counts, norm=10.0)
    short_doc = _body_tf("fire", counts, norm=0.5)
    assert long_doc < at_avg < short_doc


def test_bm25_tf_zero_for_missing_term():
    """TF returns 0 for terms not in the counts dict."""
    assert _body_tf("absent", {"fire": 5}, norm=1.0) == 0.0
    assert _body_tf("anything", {}, norm=1.0) == 0.0


@pytest.mark.parametrize("raw", [1, 2, 8, 269])
@pytest.mark.parametrize("norm", [0.5, 1.0, 2.5, 10.0])
def test_bm25f_reduces_exactly_to_single_field_bm25(raw, norm):
    """With no title counts, BM25F *is* the scorer's previous formula.

    This is what makes the field split safe to deploy ahead of a CCM reload:
    editions whose ``title_keyword_counts`` are still NULL rank exactly as they
    did, rather than ranking differently for a reason nobody chose.  Reference
    implementation below is the old ``_bm25_tf`` body, verbatim.
    """
    classic = raw * (BM25_K1 + 1) / (raw + BM25_K1 * norm)
    assert _body_tf("fire", {"fire": raw}, norm=norm) == pytest.approx(classic)


def test_bm25f_title_hit_outweighs_body_hit():
    """One occurrence in the title beats one in the body, by the field weight."""
    body_only = _bm25f_tf("fire", {"fire": 1}, {}, body_norm=1.0, title_norm=1.0)
    title_only = _bm25f_tf(
        "fire", {"fire": 1}, {"fire": 1}, body_norm=1.0, title_norm=1.0,
    )
    assert title_only > body_only
    # The accumulated frequency is the weight itself, then saturated.
    assert title_only == pytest.approx(_bm25_saturate(BM25F_TITLE_WEIGHT))


def test_bm25f_saturates_once_across_both_fields():
    """Matching in both fields must not collect two near-full ceilings.

    Saturating per field and summing is the classic BM25F mistake; it lets a
    long body plus a matching title roughly double the intended ceiling.
    """
    both = _bm25f_tf(
        "fire", {"fire": 50}, {"fire": 2}, body_norm=1.0, title_norm=1.0,
    )
    assert both < BM25_K1 + 1


def test_bm25f_body_count_excludes_the_title():
    """``keyword_counts`` is the union, so the title's share is subtracted.

    Without this the title's terms would be counted twice — once in the body
    field they were folded into at ingest, once in the title field.
    """
    # Union of 3, of which 2 came from the title -> body contributes 1.
    split = _bm25f_tf(
        "fire", {"fire": 3}, {"fire": 2}, body_norm=1.0, title_norm=1.0,
    )
    expected = _bm25_saturate(1 / 1.0 + BM25F_TITLE_WEIGHT * 2 / 1.0)
    assert split == pytest.approx(expected)


def test_bm25f_tolerates_title_term_missing_from_union():
    """CCM truncates ``keyword_counts`` at 1000 terms; the title's is exact.

    A rare title word on a mega-provision can therefore be present in the title
    counts and absent from the union.  The body share floors at zero rather
    than going negative and cancelling the title's contribution.
    """
    scored = _bm25f_tf("fire", {}, {"fire": 1}, body_norm=1.0, title_norm=1.0)
    assert scored == pytest.approx(_bm25_saturate(BM25F_TITLE_WEIGHT))
    assert scored > 0


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
    # Body lengths are 11 tokens each (1+10 and 8+3); no title counts loaded,
    # so the whole union counts as body and the title field is inert.
    assert corpus_stats.avg_body_len == pytest.approx(11.0)
    assert corpus_stats.avg_title_len == 0.0


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


# ── Title field (BM25F) ──────────────────────────────────────────────


@pytest.fixture
def maintenance_corpus(db):
    """A long provision *titled* for the query, against a body-only rival.

    Models the reported miss: OBC 2006 ``1.10.2.3. Maintenance Inspection
    Program`` scored 0.391 on "when must a maintenance inspection be
    conducted" and fell below the relevance floor, despite its title being
    almost exactly the query.  It is a long provision, and ``BM25_B`` at 0.75
    — set that high to suppress the Part 11 mega-tables — cannot tell a long
    document that is *about* the topic from one that merely mentions it.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)
    edition = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006,
        effective_date=date(2006, 12, 31),
    )

    def make(provision_id, title, counts, title_counts=None):
        prov = CodeEditionProvision.objects.create(
            edition=edition, provision_id=provision_id, level="article",
        )
        return CodeEditionProvisionVersion.objects.create(
            provision=prov, version=0,
            effective_date=date(2006, 12, 31),
            title=title,
            keyword_counts=counts,
            title_keyword_counts=title_counts,
        )

    # The wanted provision: title is the query, body is long and says the
    # terms only a couple of times each.  Its union includes the title's own
    # tokens, exactly as CCM ships it.
    make(
        "1.10.2.3.",
        "Maintenance Inspection Program",
        {"maintenance": 3, "inspection": 3, "program": 4, "filler": 900},
        {"maintenance": 1, "inspection": 1, "program": 1},
    )
    # A rival that mentions the terms more often in a shorter body but is not
    # about them — no title match.
    make(
        "3.2.4.9.",
        "Standby Power Equipment",
        {"maintenance": 6, "inspection": 5, "power": 20, "filler": 200},
        {"standby": 1, "power": 1, "equipment": 1},
    )
    # Background corpus of ordinary short provisions, so the two above read as
    # long relative to the average rather than being the average.
    for i in range(30):
        make(
            f"4.1.{i + 1}.1.", f"Ordinary Provision {i + 1}",
            {"loads": 10, "structural": 10, "design": 10},
            {"ordinary": 1, "provision": 1},
        )
    return edition


def _versions(edition):
    return CodeEditionProvisionVersion.objects.filter(provision__edition=edition)


@pytest.mark.django_db
def test_title_match_lifts_a_long_provision_over_a_body_only_rival(
    maintenance_corpus,
):
    """The reported miss, fixed: being *titled* for the query wins."""
    qs = _versions(maintenance_corpus)
    results = score_versions(
        "maintenance inspection", qs, compute_corpus_stats(qs),
        raw_query="when must a maintenance inspection be conducted",
    )

    assert results[0]["id"] == "1.10.2.3."
    assert results[1]["id"] == "3.2.4.9."


@pytest.mark.django_db
def test_without_title_counts_the_long_provision_stays_buried(
    maintenance_corpus,
):
    """The same corpus, title counts stripped, reproduces the old ranking.

    Pins the *cause*: it is the title field doing the work above, not some
    incidental property of the fixture.  This is also the state of any edition
    loaded before CCM began emitting ``title_keyword_counts``.
    """
    qs = _versions(maintenance_corpus)
    qs.update(title_keyword_counts=None)

    results = score_versions(
        "maintenance inspection", qs, compute_corpus_stats(qs),
        raw_query="when must a maintenance inspection be conducted",
    )

    assert results[0]["id"] == "3.2.4.9."
    assert results[1]["id"] == "1.10.2.3."


@pytest.mark.django_db
def test_title_field_does_not_resurrect_the_mega_table(maintenance_corpus):
    """The title field must not undo the length normalization it relieves.

    A mega-provision that mentions the query terms still has a generic title,
    so it gains nothing from the new field — which is exactly why the title
    can carry topicality that ``BM25_B`` cannot.

    Only the mega-provision's own placement is asserted.  Adding a 6,400-token
    document to a 33-document fixture quadruples ``avg_body_len``, which
    reshuffles everything else by flipping shorter provisions from
    above-average to below-average length; that is an artifact of a tiny
    corpus, and the ordering it disturbs is pinned on a stable corpus by
    ``test_title_match_lifts_a_long_provision_over_a_body_only_rival``.
    """
    edition = maintenance_corpus
    prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id="11.5.1.1.", level="article",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=prov, version=0,
        effective_date=date(2006, 12, 31),
        title="Compliance Alternatives",
        keyword_counts={"maintenance": 20, "inspection": 15, "filler": 6400},
        title_keyword_counts={"compliance": 1, "alternatives": 1},
    )

    qs = _versions(edition)
    results = score_versions(
        "maintenance inspection", qs, compute_corpus_stats(qs),
        raw_query="when must a maintenance inspection be conducted",
    )

    ids = [r["id"] for r in results]
    assert ids[0] != "11.5.1.1."
    # The titled provision beats it despite being the longer *match*.
    assert ids.index("11.5.1.1.") > ids.index("1.10.2.3.")


@pytest.mark.django_db
def test_untitled_versions_do_not_shrink_the_title_weight(maintenance_corpus):
    """A title-less version is excluded from the title-length average.

    Averaging over the whole corpus would let a run of untitled versions drag
    ``avg_title_len`` toward zero, making every real title look long and
    quietly shrinking the boost for the provisions the field exists to help.
    """
    edition = maintenance_corpus
    before = compute_corpus_stats(_versions(edition)).avg_title_len

    for i in range(50):
        prov = CodeEditionProvision.objects.create(
            edition=edition, provision_id=f"A-{i}.1.1.1.", level="article",
        )
        CodeEditionProvisionVersion.objects.create(
            provision=prov, version=0,
            effective_date=date(2006, 12, 31),
            title="", keyword_counts={"note": 5}, title_keyword_counts={},
        )

    assert compute_corpus_stats(_versions(edition)).avg_title_len == before
