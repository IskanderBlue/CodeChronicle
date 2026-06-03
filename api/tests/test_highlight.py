"""Tests for matched-term highlighting in provision HTML."""

from api.formatters import highlight_terms

MARK_OPEN = '<mark class="match-highlight">'
MARK_CLOSE = "</mark>"


def test_no_terms_returns_html_unchanged():
    html = "<p>fire separation rating</p>"
    assert highlight_terms(html, []) == html
    assert highlight_terms(html, None or []) == html


def test_empty_html_returns_unchanged():
    assert highlight_terms("", ["fire"]) == ""


def test_wraps_a_matched_term():
    out = highlight_terms("<p>a fire separation here</p>", ["fire separation"])
    assert f"{MARK_OPEN}fire separation{MARK_CLOSE}" in out


def test_is_case_insensitive_and_preserves_original_case():
    out = highlight_terms("<p>Fire Separation</p>", ["fire separation"])
    assert f"{MARK_OPEN}Fire Separation{MARK_CLOSE}" in out


def test_does_not_touch_tag_attributes():
    # 'span' appears in a tag name/attr; must never be wrapped.
    html = '<span class="fire">fire</span>'
    out = highlight_terms(html, ["fire"])
    assert '<span class="fire">' in out  # attribute intact
    assert f'{MARK_OPEN}fire{MARK_CLOSE}</span>' in out  # only the text node


def test_longer_term_wins_no_nested_marks():
    out = highlight_terms("<p>fire-resistance rating</p>", ["rating", "fire-resistance rating"])
    assert f"{MARK_OPEN}fire-resistance rating{MARK_CLOSE}" in out
    # the inner 'rating' must not be separately wrapped (no nested marks)
    assert out.count(MARK_OPEN) == 1


def test_word_boundaries_avoid_partial_matches():
    out = highlight_terms("<p>refire firefighter</p>", ["fire"])
    # 'fire' inside 'refire'/'firefighter' should not be highlighted
    assert MARK_OPEN not in out


def test_multiple_distinct_terms():
    out = highlight_terms("<p>fire separation and exit</p>", ["fire separation", "exit"])
    assert out.count(MARK_OPEN) == 2
