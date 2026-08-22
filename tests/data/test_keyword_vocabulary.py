"""
Pin the keyword-vocabulary admission policy (scripts/extract_keywords.py).

Decision (2026-07-23, tasks/complete/keyword-vocabulary-hyphen-filter.md):
hyphenated-but-otherwise-wordlike keys — objective codes and standard
designations like ``a101-m`` — ARE admitted into VALID_KEYWORDS, so the LLM
parser can emit them and the ``keyword_counts__has_key`` filter can match
them exactly.  Plain (unhyphenated) keys must still be purely alphabetic.
These tests exist so the policy is legible in code rather than emergent
from a filter expression.
"""

import pytest

from data.keywords import VALID_KEYWORDS
from scripts.extract_keywords import is_searchable_keyword


class TestIsSearchableKeyword:
    @pytest.mark.parametrize(
        "kw",
        [
            "fire",  # plain word
            "spruce",  # component of a producer-split compound
            "a101-m",  # CSA/ASTM standard designation
            "f03-os1-dot-2",  # encoded objective code
            "a-1",  # appendix reference
            "spruce-pine-fir",  # species compound (pre-split editions)
        ],
    )
    def test_admitted(self, kw):
        assert is_searchable_keyword(kw)

    @pytest.mark.parametrize(
        "kw",
        [
            "123",  # bare number
            "12a",  # unhyphenated alphanumeric noise
            "3-2",  # hyphenated but no letter anywhere
            "a101-m.2",  # part contains a non-alphanumeric character
            "fire-",  # empty hyphen part
            "-fire",
            "fire resistance",  # producer keys never contain spaces
            "",
        ],
    )
    def test_dropped(self, kw):
        assert not is_searchable_keyword(kw)


def test_generated_vocabulary_satisfies_the_policy():
    """Every shipped VALID_KEYWORDS entry passes the admission predicate —
    catches a hand-edit of data/keywords.py or a stale regeneration after
    the policy changes."""
    offenders = [kw for kw in VALID_KEYWORDS if not is_searchable_keyword(kw)]
    assert offenders == []
