"""Turn the reader's own words into terms the index can match.

The search used to learn its keywords only from the LLM, which *replaced* the
query with terms it inferred.  An inferred term can outrank every word the
reader typed: ``guard height for a stair in a house`` returned eight results
matching only ``residential`` — a word nobody typed — before the first result
matching ``guard``.  This module reads the query first, so the typed words are
always in the search.  The model then supplements the list; see
``search.llm.llm_parser``.

**The tokenizer is CCM's, not a new one.**  Every ``keyword_counts`` dict in
the corpus comes from ``chronicle_mapping.shared.keywords``, so that code
defines the vocabulary the index holds.  A second tokenizer would be a second
vocabulary, and a term the index cannot contain matches nothing.  The module is
vendored rather than imported for the same reason ``data.synonyms`` is: CCM
is a sibling clone that no deployment has, and CCM's own ``STOPWORDS`` reaches
one repository further still, through a ``sys.path`` trampoline into
``Canada_building_code_mcp``.

Two differences from the source, both deliberate:

* **No provision-id or table-id pass.**  CCM adds dotted ids as terms because a
  map file has no other channel for them.  This product has one:
  ``search.llm.llm_parser`` extracts ids with its own regexes and hands them to the
  engine as ``section_references``, which scores them against a provision's
  number rather than its text.  A second channel would double-count.
* **The result is a list, not a count.**  A term the reader typed twice is not
  twice the term.

Parity is held by tests in both repositories, and each fails in only one
direction:

* ``TestNoDriftFromCCM`` in ``tests/test_query_keywords.py`` runs the real
  CCM function in CCM's own venv and compares.  It fails when **CCM** changes,
  which is the case that matters — CCM's tokenizer writes the corpus's
  ``keyword_counts``, so a change there re-tokenizes the index at the next
  ``load_edition`` while this copy sits still.
* ``tests/test_keyword_parity_codechronicle.py`` in CCM runs *this* module in
  *this* venv and compares.  It fails when this copy changes.

Both skip where the sibling clone is absent.  Which one fires depends on which
repository somebody is working in, which is why both exist.  ``CCM_SAMPLES``,
recorded from a real CCM run, is the third and cheapest guard: it needs no
clone at all, and so it is the only one that runs in CI.
"""

import re

from data.keywords import VALID_KEYWORDS

#: The corpus vocabulary, as a set.  ``VALID_KEYWORDS`` is a 7 094-entry list
#: written by ``scripts/extract_keywords.py``, which overwrites that whole file
#: — so nothing derived can live beside it.
KEYWORD_SET = frozenset(VALID_KEYWORDS)

#: Vendored from ``chronicle_mapping.shared.mcp_imports``, which extends the
#: upstream MCP set with domain filler.  Several entries look wrong for a query
#: — ``building``, ``minimum``, ``code`` — but they are right: the same filter
#: ran over every provision, so no provision's ``keyword_counts`` holds them.
#: Keeping such a word would produce a term that matches nothing.
STOPWORDS = frozenset({
    'a', 'about', 'above', 'accordance', 'additional', 'after', 'align', 'all', 'also',
    'an', 'and', 'annex', 'annexes', 'any', 'appendices', 'appendix', 'applicable',
    'application', 'applied', 'applies', 'apply', 'are', 'article', 'articles', 'as',
    'at', 'based', 'be', 'been', 'before', 'being', 'below', 'between', 'black',
    'border', 'border-bottom', 'border-collapse', 'border-left', 'border-right',
    'border-top', 'both', 'building', 'buildings', 'but', 'by', 'can', 'cellpadding',
    'cellspacing', 'certain', 'classified', 'clause', 'clauses', 'code', 'collapse',
    'colspan', 'commentaries', 'commentary', 'compliance', 'comply', 'conform',
    'conformance', 'conforming', 'conforms', 'considered', 'constructed', 'contained',
    'could', 'described', 'design', 'designed', 'determined', 'did', 'division',
    'divisions', 'do', 'does', 'down', 'due', 'each', 'eight', 'entitled', 'every',
    'except', 'figure', 'figures', 'five', 'following', 'font-weight', 'for', 'forming',
    'found', 'four', 'from', 'general', 'given', 'greater', 'guide', 'had', 'has',
    'have', 'having', 'how', 'however', 'if', 'in', 'include', 'included', 'includes',
    'including', 'information', 'installation', 'installed', 'intended', 'into', 'is',
    'it', 'its', 'just', 'least', 'less', 'listed', 'located', 'location', 'made',
    'max', 'maximum', 'may', 'means', 'might', 'min', 'minimum', 'more', 'most', 'must',
    'nbc', 'need', 'nine', 'no', 'not', 'note', 'notes', 'nowrap', 'number', 'of',
    'off', 'on', 'one', 'only', 'or', 'other', 'out', 'over', 'own', 'padding', 'part',
    'parts', 'per', 'permitted', 'provide', 'provided', 'provision', 'provisions',
    'refer', 'reference', 'references', 'referred', 'required', 'requirement',
    'requirements', 'rowspan', 'same', 'scope', 'section', 'sections', 'see',
    'sentence', 'sentences', 'seven', 'shall', 'should', 'single', 'six', 'so', 'solid',
    'some', 'specified', 'standard', 'standards', 'style', 'sub', 'subsection',
    'subsections', 'such', 'sup', 'supported', 'table', 'tables', 'taken', 'tbody',
    'ten', 'text-align', 'than', 'that', 'the', 'thead', 'their', 'then', 'there',
    'these', 'they', 'this', 'those', 'three', 'through', 'to', 'total', 'two', 'type',
    'types', 'under', 'unless', 'up', 'use', 'used', 'using', 'valign', 'various',
    'was', 'were', 'what', 'when', 'where', 'whether', 'which', 'white-space', 'who',
    'whom', 'whose', 'why', 'will', 'with', 'within', 'without', 'would',
})

#: Letter-initial, so a bare number never becomes a term.  The ids a query
#: names travel the reference channel instead.
_WORD_RE = re.compile(r"[a-z][a-z0-9-]*[a-z0-9]|[a-z]")

#: An objective code (``F03-OS1.2``) carries a dot inside one identifier.  CCM
#: hides that dot before tokenizing and restores it after, so the code survives
#: as a single searchable term.
_OBJECTIVE_CODE_RE = re.compile(r"\b([A-Z]\d+-[A-Z]+\d+)\.(\d+)\b")
_DOT_MARKER = "-dot-"

#: Shortest term the tokenizer keeps.  CCM's rule, and the vocabulary was built
#: under it.
_MIN_LENGTH = 2


def _split_hyphenated(word: str) -> list[str]:
    """Split a hyphenated token into its parts.

    A dash is a token boundary for search: ``spruce-pine-fir`` is three
    concepts, and the index keys on whole-token equality, so a reader who types
    one part could never reach a compound term.

    An encoded objective code is the exception — its internal hyphen belongs to
    the identifier.
    """
    if _DOT_MARKER in word:
        return [word]
    if "-" in word:
        return [part for part in word.split("-") if part]
    return [word]


def tokenize(text: str) -> list[str]:
    """The terms *text* contributes to the index, in order, with repeats.

    This is CCM's **word pass**, and must stay identical to it.  It is not all
    of ``extract_keyword_counts``: that function also runs an id pass, so it
    answers ``{'9.8.8.3.': 1}`` where this answers ``[]``.  That difference is
    deliberate and is pinned by ``test_the_id_pass_is_the_only_difference``.

    Change this only to follow a change in CCM.
    """
    if not text or not text.strip():
        return []
    hidden = _OBJECTIVE_CODE_RE.sub(rf"\1{_DOT_MARKER}\2", text)
    words: list[str] = []
    for match in _WORD_RE.findall(hidden.lower()):
        words.extend(_split_hyphenated(match))
    return [
        word.replace(_DOT_MARKER, ".")
        for word in words
        if word not in STOPWORDS and len(word) > _MIN_LENGTH
    ]


def _unique(terms: list[str]) -> list[str]:
    """Drop repeats, keeping the order the reader wrote."""
    seen: set[str] = set()
    kept: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            kept.append(term)
    return kept


def typed_keywords(text: str) -> list[str]:
    """The words in *text* that the corpus actually uses.

    These are the search's **direct** terms.  They score at full weight, and
    nothing downstream may drop one — that is the whole point of reading the
    query before calling the model.
    """
    return _unique([term for term in tokenize(text) if term in KEYWORD_SET])


def plural_variants(terms: list[str]) -> list[str]:
    """The singular or plural partner of each term, where the corpus has one.

    CCM's tokenizer does no stemming, so ``stair`` and ``stairs`` are unrelated
    terms in the index and a provision titled "Stairs" is unreachable by the
    singular.  Both forms are in the vocabulary, so the partner is added here
    rather than left to the model, which is the component this work exists to
    stop depending on.

    The partner is an **indirect** term: the reader did not type it, and the
    0.9 weight is exactly the discount a variant should carry.  Only the
    regular ``-s`` pair is handled; an irregular plural is the model's job.
    """
    known = set(terms)
    partners = []
    for term in terms:
        partner = term[:-1] if term.endswith("s") else f"{term}s"
        if len(partner) > _MIN_LENGTH and partner in KEYWORD_SET and partner not in known:
            partners.append(partner)
            known.add(partner)
    return partners
