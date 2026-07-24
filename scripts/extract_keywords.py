import glob
import json
import os

from coloured_logger import Logger

logger = Logger(__name__)


def is_searchable_keyword(kw: str) -> bool:
    """Vocabulary admission policy for a producer-emitted keyword key.

    Plain words must be purely alphabetic (drops bare numbers and page/figure
    noise like ``12a``).  Hyphenated keys are admitted when every hyphen-joined
    part is alphanumeric and at least one letter appears anywhere — this is
    what lets objective codes and standard designations (``a101-m``,
    ``f03-os1-dot-2``, appendix refs like ``a-1``) into VALID_KEYWORDS so the
    parser can emit them and ``has_key`` can match them exactly, per the
    decision in tasks/complete/keyword-vocabulary-hyphen-filter.md.  Producer
    keys never contain spaces (the CCM tokenizer splits on every
    non-``[a-z0-9-]`` character), so no phrase branch exists.
    """
    if "-" in kw:
        parts = kw.split("-")
        return all(p.isalnum() for p in parts) and any(c.isalpha() for c in kw)
    return kw.isalpha()


def extract_keywords():
    # Path to the neighboring CodeChronicleMapping repo
    maps_dir = os.path.abspath(os.path.join("..", "CodeChronicleMapping", "data", "outputs"))
    map_files = glob.glob(os.path.join(maps_dir, "*.json"))

    # Derive synonyms dynamically from the mcp_server.py
    try:
        from building_code_mcp.mcp_server import SYNONYMS

        common_synonyms = set()
        for key, vals in SYNONYMS.items():
            common_synonyms.add(key.lower())
            for v in vals:
                common_synonyms.add(v.lower())
    except ImportError:
        logger.warning("Could not import SYNONYMS from building_code_mcp. Falling back to empty.")
        common_synonyms = set()

    keywords = set(common_synonyms)

    logger.info("Processing %d map files...", len(map_files))

    for map_file in map_files:
        try:
            with open(map_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # keyword_counts lives on each provision *version* (tables carry
            # none) — the same per-version dicts the search engine's has_key
            # filter queries, so the vocabulary and the index can't skew.
            for provision in data.get("provisions", []):
                for version in provision.get("versions", []):
                    for kw in version.get("keyword_counts") or {}:
                        if isinstance(kw, str) and len(kw) > 2:
                            keywords.add(kw.lower())
        except Exception as e:
            logger.error("Error processing %s: %s", map_file, e)

    filtered_keywords = sorted(kw for kw in keywords if is_searchable_keyword(kw))

    # Write to config/keywords.py
    output_path = os.path.join("config", "keywords.py")
    os.makedirs("config", exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('"""\nAuto-generated building code keywords derived from map files.\n"""\n\n')
        f.write("VALID_KEYWORDS = [\n")
        for kw in filtered_keywords:
            f.write(f"    {repr(kw)},\n")
        f.write("]\n")

    logger.info("Extracted %d keywords to %s", len(filtered_keywords), output_path)


if __name__ == "__main__":
    extract_keywords()
