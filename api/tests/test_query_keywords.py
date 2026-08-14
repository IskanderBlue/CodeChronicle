"""The query's own words, read before the model sees it.

``config.query_keywords`` is a vendored copy of CCM's word pass.  Vendored, not
imported: CCM is a sibling clone that no deployment has, its module reaches
BeautifulSoup through an id pass this product does not want, and its
``STOPWORDS`` come from a third repository through a ``sys.path`` trampoline.

A copy can drift, so two guards run, and they fail on different things:

* ``CCM_SAMPLES`` are expectations recorded from a real CCM run.  They fail
  when **this copy** changes.
* ``TestNoDriftFromCCM`` runs the real function in CCM's own environment and
  compares.  It fails when **CCM** changes — the case the recorded samples
  cannot see, and the one that matters, because CCM's tokenizer writes the
  ``keyword_counts`` that this query has to match.  It skips where the sibling
  clone is absent, which is every deployment and may be CI.
"""

import json
import subprocess
from pathlib import Path

import pytest

from config.query_keywords import (
    KEYWORD_SET,
    STOPWORDS,
    plural_variants,
    tokenize,
    typed_keywords,
)

#: The sibling clone and the interpreter that can import it.  CCM's own venv is
#: used rather than this one: the point is to run the real function against its
#: real dependencies, and adding BeautifulSoup here to import it in-process
#: would make the test pass against a second-hand copy of the environment.
_CCM = Path(__file__).resolve().parents[2].parent / "CodeChronicleMapping"
_CCM_PYTHON = _CCM / "venv" / "Scripts" / "python.exe"
_CCM_POSIX_PYTHON = _CCM / "venv" / "bin" / "python"

#: query -> the terms CCM's tokenizer produces from it, with counts.
CCM_SAMPLES: dict[str, dict[str, int]] = {
    "guard height for a stair in a house": {
        "guard": 1, "height": 1, "stair": 1, "house": 1,
    },
    "fire safety for a house built in Toronto in 1995": {
        "fire": 1, "safety": 1, "house": 1, "built": 1, "toronto": 1,
    },
    "spruce-pine-fir joists and the F03-OS1.2 objective": {
        "spruce": 1, "pine": 1, "fir": 1, "joists": 1,
        "f03-os1.2": 1, "objective": 1,
    },
    "What stops fire spreading between units": {
        "stops": 1, "fire": 1, "spreading": 1, "units": 1,
    },
    "guards on stairs": {"guards": 1, "stairs": 1},
    "minimum ceiling height in a basement bedroom": {
        "ceiling": 1, "height": 1, "basement": 1, "bedroom": 1,
    },
}


#: Text with no provision or table id in it.  CCM's function also runs an id
#: pass, which this copy deliberately omits, so an id-bearing sample would
#: compare two different jobs.  The one intended difference is pinned on its
#: own, by ``test_the_id_pass_is_the_only_difference``.
_DRIFT_SAMPLES = tuple(CCM_SAMPLES) + (
    "spruce-pine-fir studs in an exterior wall",
    "the F03-OS1.2 objective and the F02-OP2.1 one",
    "MINIMUM height of a BUILDING guard",
    "smoke alarms, carbon-monoxide alarms and sprinklers",
    "a 1 070 mm guard around a landing",
    "wood-frame construction: joists, rafters and lintels",
)


def _counts(terms: list[str]) -> dict[str, int]:
    """The tokenizer's list as the term-frequency dict CCM returns."""
    counts: dict[str, int] = {}
    for term in terms:
        counts[term] = counts.get(term, 0) + 1
    return counts


def _ccm_python() -> Path | None:
    for candidate in (_CCM_PYTHON, _CCM_POSIX_PYTHON):
        if candidate.is_file():
            return candidate
    return None


def _run_ccm(samples: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """The real CCM tokenizer's answer for each sample."""
    python = _ccm_python()
    assert python is not None
    script = (
        "import sys, json; sys.path.insert(0, 'src');"
        "from chronicle_mapping.shared.keywords import extract_keyword_counts;"
        "print(json.dumps({s: extract_keyword_counts(s)"
        " for s in json.loads(sys.argv[1])}))"
    )
    done = subprocess.run(
        [str(python), "-c", script, json.dumps(list(samples))],
        cwd=str(_CCM),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


needs_ccm = pytest.mark.skipif(
    _ccm_python() is None,
    reason=f"CCM clone with a venv not found at {_CCM}",
)


@needs_ccm
class TestNoDriftFromCCM:
    """The vendored copy still answers what CCM answers.

    A failure here does **not** mean fix this repository to match. It means
    CCM's tokenizer changed, so the corpus will be re-tokenized at the next
    ``load_edition`` and the query side has to follow. Read the change there
    first, then port it, then re-record ``CCM_SAMPLES``.
    """

    @pytest.fixture(scope="class")
    def ccm(self) -> dict[str, dict[str, int]]:
        # One subprocess for the whole class: starting an interpreter per
        # sample would cost more than the comparison is worth.
        return _run_ccm(_DRIFT_SAMPLES)

    def test_the_word_pass_still_agrees(self, ccm) -> None:
        mine = {text: _counts(tokenize(text)) for text in _DRIFT_SAMPLES}
        assert mine == ccm

    def test_the_recorded_samples_are_still_what_ccm_says(self, ccm) -> None:
        # Otherwise CCM_SAMPLES silently becomes a record of history rather
        # than of CCM, and the cheap guard stops guarding anything.
        assert {text: ccm[text] for text in CCM_SAMPLES} == CCM_SAMPLES

    def test_the_id_pass_is_the_only_difference(self) -> None:
        # The deliberate divergence, stated as a fact about both sides rather
        # than left implicit. This product routes an id through
        # ``api.llm_parser``'s reference channel, which scores it against a
        # provision's number instead of its text, so a second copy of it here
        # would double-count.
        text = "guard height in 9.8.8.3."
        theirs = _run_ccm((text,))[text]
        assert theirs == {"guard": 1, "height": 1, "9.8.8.3.": 1}
        assert tokenize(text) == ["guard", "height"]


class TestTokenizerMatchesCCM:
    @pytest.mark.parametrize(("text", "expected"), CCM_SAMPLES.items())
    def test_it_produces_ccms_terms(self, text: str, expected: dict[str, int]) -> None:
        assert _counts(tokenize(text)) == expected

    def test_a_hyphen_is_a_token_boundary(self) -> None:
        # The index keys on whole-token equality, so a reader who types one
        # part of a compound could never reach a term that kept the compound.
        assert tokenize("spruce-pine-fir") == ["spruce", "pine", "fir"]

    def test_an_objective_code_stays_one_term(self) -> None:
        # The one hyphen that is part of an identifier rather than a boundary.
        assert tokenize("F03-OS1.2") == ["f03-os1.2"]

    def test_a_bare_number_is_not_a_term(self) -> None:
        # Ids reach the engine through the reference channel instead.
        assert tokenize("9.8.8.3. and 1995") == []


class TestTypedKeywords:
    def test_it_keeps_only_words_the_corpus_uses(self) -> None:
        terms = typed_keywords("guard height for a stair in a house")
        assert terms == ["guard", "height", "stair", "house"]
        assert all(term in KEYWORD_SET for term in terms)

    def test_it_keeps_the_order_the_reader_wrote(self) -> None:
        # A truncation anywhere downstream should spend what it has on the
        # words that came first, so the order is part of the contract.
        assert typed_keywords("stair guard") == ["stair", "guard"]

    def test_it_reports_a_repeated_word_once(self) -> None:
        assert typed_keywords("guard on a guard") == ["guard"]

    def test_a_stopword_is_dropped_even_though_it_reads_as_meaningful(self) -> None:
        # "building" looks like the most relevant word a reader could type.
        # The same filter ran over the corpus, so no provision's keyword_counts
        # holds it, and keeping it would produce a term that matches nothing.
        assert "building" in STOPWORDS
        assert "building" not in typed_keywords("height of a building")

    def test_a_query_the_corpus_has_no_word_for_yields_nothing(self) -> None:
        # Not a failure: this is the query the model exists to rescue, which is
        # why local extraction is a floor and never a gate.
        assert typed_keywords("how do I do this") == []


class TestPluralVariants:
    def test_it_supplies_the_partner_form(self) -> None:
        # CCM's tokenizer does no stemming, so a provision titled "Stairs" is
        # unreachable from a typed "stair" without this.
        assert "stairs" in plural_variants(["stair"])
        assert "stair" in plural_variants(["stairs"])

    def test_it_never_repeats_a_word_already_typed(self) -> None:
        assert plural_variants(["stair", "stairs"]) == []

    def test_it_offers_only_partners_the_corpus_has(self) -> None:
        assert all(term in KEYWORD_SET for term in plural_variants(["guard", "height"]))
