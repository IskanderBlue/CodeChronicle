"""
Claude-based query parser to extract structured search parameters from natural language.
"""

import re
from datetime import date
from typing import Any, Dict, cast

import anthropic
from django.conf import settings

from config.keywords import VALID_KEYWORDS
from config.part_applicability import OCCUPANCIES
from config.query_keywords import KEYWORD_SET, plural_variants, typed_keywords

SECTION_REF_RE = re.compile(
    r"\b((?:(?:table|[a-z])-)?\d{1,2}(?:\.\d{1,2}){1,4}\.?(?:\(\d+(?:-\d+|(?:,\d+)*)\))?)(?=\s|$|[,;:!\?)\]])",
    re.IGNORECASE,
)

# Table references the provision regex above can't see.  Appendix tables are
# letter-numbered ("Table A-1" .. "Table A-37") with no dotted core, so the
# `\d+.\d+` shape never matches them; the space form ("Table 9.10.14.1", no
# hyphen) would also drop its "table" flag and degrade to a bare provision id.
# The captured token keeps the "Table" word — exactly the marker the engine's
# ``_ref_parts`` reads to route a reference against a provision's tables rather
# than its id.
TABLE_REF_RE = re.compile(
    r"\btable[\s\-.]+"
    r"(?:[a-z]-?\d{1,3}\.?"  # appendix form: A-1, A-37, A1
    r"|\d{1,2}(?:\.\d{1,2}){1,4}[a-z]?\.?(?:\(\d+(?:-\d+|(?:,\d+)*)\))?)"  # dotted form
    r"(?=\s|$|[,;:!\?)\]])",
    re.IGNORECASE,
)


def extract_section_references(query: str) -> list[str]:
    return SECTION_REF_RE.findall(query)


def strip_section_references(query: str) -> str:
    return SECTION_REF_RE.sub("", query).strip()


def extract_table_references(query: str) -> list[str]:
    return TABLE_REF_RE.findall(query)


def strip_table_references(query: str) -> str:
    return TABLE_REF_RE.sub("", query).strip()


def _as_table_ref(ref: str) -> str:
    """Coerce an LLM-supplied table id into a marker the engine recognizes.

    ``_ref_parts`` flags a reference as a table only when it starts with a
    ``table`` marker, so a bare id the model returns ("A-1", "9.10.14.1") is
    prefixed; an already-prefixed "Table A-1" passes through untouched.
    """
    r = ref.strip()
    return r if re.match(r"table[\s\-.]+", r, re.IGNORECASE) else f"Table-{r}"


def _merge_refs(existing: list[str], extra: list[str]) -> list[str]:
    """Append ``extra`` refs not already present (case-insensitive), order-stable."""
    seen = {r.lower() for r in existing}
    return existing + [r for r in extra if r.lower() not in seen]


def _merge_keywords(*groups: list[str]) -> list[str]:
    """One order-stable, de-duplicated list from several keyword groups.

    The reader's own words come first, so a truncation anywhere downstream
    spends what it has on them rather than on the model's additions.
    """
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for keyword in group:
            term = keyword.lower()
            if term not in seen:
                seen.add(term)
                merged.append(term)
    return merged


# Tool definition for Claude
PARSE_QUERY_TOOL = {
    "name": "parse_building_code_query",
    "description": "Extract search parameters from natural language building code question",
    "input_schema": {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "format": "date",
                "description": "Date of construction or renovation (YYYY-MM-DD). Use today's date if not mentioned.",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The words already found in the query, plus any you add. "
                    "Only use terms from the master keyword list provided in "
                    "the system prompt. Never omit a word you were given."
                ),
            },
            "province": {
                "type": "string",
                "enum": [
                    "ON",
                    "BC",
                    "AB",
                    "QC",
                    "MB",
                    "SK",
                    "NS",
                    "NB",
                    "NL",
                    "PE",
                    "YT",
                    "NT",
                    "NU",
                ],
                "description": "Canadian province (default: ON)",
            },
            "occupancy": {
                "type": "string",
                "enum": list(OCCUPANCIES),
                "description": (
                    "The building code's major occupancy classification for the "
                    "building the user is asking about, when the query names a "
                    "kind of building (house -> residential, office -> business, "
                    "shop -> mercantile, school or restaurant -> assembly, "
                    "hospital or nursing home -> care-or-detention, warehouse -> "
                    "low-hazard-industrial). Omit when the query names no "
                    "building. This is NOT a keyword and never enters the "
                    "keyword list."
                ),
            },
            "table_references": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Building-code table identifiers the user explicitly names, "
                    "each as 'Table <id>' (e.g. 'Table A-1', 'Table 9.10.14.1'). "
                    "Only include a table the user directly refers to; omit otherwise."
                ),
            },
        },
        "required": ["date", "keywords"],
    },
}

SYSTEM_PROMPT = f"""You are a building code query parser.

Extract from user query:
1. Date (when was building constructed/renovated? format YYYY-MM-DD)
2. Keywords. See the rules below.
3. Province (if mentioned, default ON)
4. Table references (only if the user explicitly names a code table, e.g.
   "Table A-1" or "Table 9.10.14.1"). Return each as "Table <id>". Omit when
   the user names no table.
5. Occupancy (only if the query names a kind of building). This is the code's
   own classification of the building, not a keyword — see below.

OCCUPANCY: classify the building the user is asking about into one major
occupancy. That is a language task, and it is the ONLY thing you may say about
their building.

- NEVER report a size. You cannot know how many storeys the building has or
  how large it is, and a guess there is silently wrong: a four-storey
  townhouse is a house and is not a Part 9 building.
- Omit the field when the query names no building ("what is a mezzanine").
- A building the user describes two ways gets the occupancy of the space they
  are asking about.

KEYWORDS: the query has already been read for you. The user message gives you
"Words in the query" — the words the user wrote that the building code itself
uses. Your job is to SUPPLEMENT that list, never to replace it.

- Return every word you were given, then add your own.
- Add: other forms of a given word, close synonyms, and the code topics the
  question is about.
- Prefer the word the user wrote over a word that describes the user. Do NOT
  add "residential" because the user wrote "house". A word nobody typed can
  outrank every word they did.
- When you are given no words, supply the keywords yourself.

CRITICAL: Keywords must ONLY come from this master list:
{", ".join(VALID_KEYWORDS)}

Do NOT use keywords outside this list.
If the user mentions a year but not a specific date, assume January 1st of that year (YYYY-01-01).
If no date or year is mentioned, use today's date (provided in the user message)."""


def get_prompt_hash(content: str) -> str:
    """Generate SHA-256 hash of the prompt content."""
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_query_hash(query: str) -> str:
    """Generate SHA-256 hash of the normalized query."""
    import hashlib

    # Normalize: lowercase, strip whitespace
    normalized = query.lower().strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_is_stale(cached: Any) -> bool:
    """Whether a cached parse can no longer be trusted today.

    Only *relative* parses expire.  ``date_is_relative`` marks a row whose
    ``date`` was the LLM's "no date mentioned -> use today" default — valid only
    for the day it was computed.  Because that default *is* the stored date, the
    row is stale exactly when the stored date no longer equals today.  Explicit
    or historical dates are stable and never go stale.
    """
    if not cached.date_is_relative:
        return False
    return cached.parsed_params.get("date") != date.today().isoformat()


def parse_user_query(query: str) -> Dict[str, Any]:
    """
    Parse natural language query into structured parameters using Claude.
    Section references (e.g. "9.10.14.5") are extracted via regex first.
    If the query is *only* section references, the LLM call is skipped entirely.
    Checks QueryCache before calling API.
    """
    from core.models import QueryCache, QueryPrompt

    # Tables first: strip the table forms, then run the provision regex on what
    # remains, so "Table 9.10.14.1" is one table reference and not also a bare
    # "9.10.14.1" provision hit. Both lists feed the single ``section_references``
    # channel the engine consumes; ``_ref_parts`` re-derives table-vs-provision
    # from each token's own marker.
    table_refs = extract_table_references(query)
    q_no_tables = strip_table_references(query)
    section_refs = extract_section_references(q_no_tables)
    references = table_refs + section_refs
    remaining_query = strip_section_references(q_no_tables) if references else query

    if references and not remaining_query:
        return {
            "date": date.today().isoformat(),
            "keywords": [],
            "direct_keywords": [],
            "section_references": references,
            "province": "ON",
        }

    # Read the query before the model does.  These are the words the reader
    # actually wrote that the code also uses, and nothing below may drop one.
    # ``remaining_query`` is used, not ``query``: any id the reader named has
    # already left through the reference channel.
    direct = typed_keywords(remaining_query)
    variants = plural_variants(direct)

    # 0. Prepare hashes
    # The cache is keyed on the bare query.  Whether a parse depends on "today"
    # is decided from the LLM's actual answer (see ``date_is_relative`` below and
    # ``_parse_is_stale``), not from a pre-LLM guess at whether the text names a
    # date — a regex can't tell a construction year from an edition label
    # ("OBC 2012") or a measurement ("1900 mm").
    query_hash = get_query_hash(query)
    prompt_content = SYSTEM_PROMPT + str(PARSE_QUERY_TOOL)
    prompt_hash = get_prompt_hash(prompt_content)

    # 1. Check Cache
    cached = QueryCache.objects.filter(
        query_hash=query_hash, prompt__prompt_hash=prompt_hash
    ).first()

    if cached and not _parse_is_stale(cached):
        cached.hits += 1
        cached.save(update_fields=["hits"])
        params = cached.parsed_params
        # Merge, don't overwrite: the cached parse may already carry LLM-extracted
        # table references that the regex doesn't reproduce. Re-applying the regex
        # refs (deterministic from this same query) is idempotent.
        merged = _merge_refs(params.get("section_references", []), references)
        if merged:
            params["section_references"] = merged
        return params

    # 2. Cache Miss - Call API
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not configured.")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        # The extracted words go to the model as a list to build on.  "none
        # found" is said in words rather than left blank, because a blank line
        # reads as a formatting fault and invites the model to ignore the rule.
        found = ", ".join(direct) if direct else "none found"
        user_message = (
            f"Today's date: {date.today().isoformat()}\n"
            f"Words in the query: {found}\n\n"
            f"{remaining_query}"
        )
        # The inline dicts are correct at runtime but don't match anthropic's
        # exact TypedDict param types (e.g. "role" infers str, not the SDK's
        # Literal). cast(Any) tells both checkers "trust these shapes" without
        # importing the SDK's param types or pinning model literals.
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1000,
            tools=cast(Any, [PARSE_QUERY_TOOL]),
            tool_choice=cast(Any, {"type": "tool", "name": "parse_building_code_query"}),
            system=SYSTEM_PROMPT,
            messages=cast(Any, [{"role": "user", "content": user_message}]),
        )
    except anthropic.AuthenticationError:
        raise ValueError(
            "Invalid Anthropic API Key. Please verify the ANTHROPIC_API_KEY in your .env file."
        )
    except Exception as e:
        raise ValueError(f"LLM parsing failed: {str(e)}")

    # Extract tool use
    for block in response.content:
        if block.type == "tool_use":
            # tool_use input is JSON typed as ``object`` by the SDK; it is a
            # dict by construction of our tool schema.
            params = cast(dict[str, Any], block.input)

            # Validate the model's keywords against the master list, then put
            # the reader's own words back in front of them.  The union is what
            # makes "supplement, never replace" a property of the code rather
            # than a request the model may or may not honour: a model that
            # returns nothing still leaves the typed words searched.
            keywords = params.get("keywords", [])
            valid_keywords = _merge_keywords(
                direct,
                variants,
                [k for k in keywords if k.lower() in KEYWORD_SET],
            )

            # Fold the LLM's table picks into the regex-extracted references and
            # drop the raw field — downstream only ever reads section_references.
            # The model sees the table-stripped query, so it only adds tables the
            # regex missed (descriptive phrasing, odd spacing); duplicates of a
            # regex hit are de-duped by _merge_refs.
            llm_table_refs = [
                _as_table_ref(r) for r in (params.pop("table_references", None) or [])
            ]
            references = _merge_refs(references, llm_table_refs)

            if not valid_keywords and not references:
                raise ValueError(
                    "Query does not contain recognized building code keywords. "
                    "Try terms like: fire safety, structural, plumbing, electrical."
                )

            params["keywords"] = valid_keywords
            # The direct/indirect split, stated rather than re-derived.  The
            # engine used to recover it by testing each keyword against the
            # raw query text, which is right for a whole word and wrong for a
            # hyphenated one: a typed "spruce-pine-fir" extracts as three
            # terms, none of which appears verbatim, so all three were filed
            # as the model's guesses.
            params["direct_keywords"] = direct
            if references:
                params["section_references"] = references
            if "province" not in params:
                params["province"] = "ON"

            # 3. Save to Cache
            prompt_obj, _ = QueryPrompt.objects.get_or_create(
                prompt_hash=prompt_hash, defaults={"content": prompt_content}
            )

            QueryCache.objects.update_or_create(
                query_hash=query_hash,
                defaults={
                    "raw_query": query,
                    "parsed_params": params,
                    "llm_model": settings.CLAUDE_MODEL,
                    "prompt": prompt_obj,
                    # The parse is time-relative iff its date is today's date
                    # (the LLM's default when the query names no date).
                    "date_is_relative": (
                        params.get("date") == date.today().isoformat()
                    ),
                },
            )

            return params

    raise ValueError("Could not parse query parameters.")
