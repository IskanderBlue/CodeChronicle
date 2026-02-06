import glob
import json
import os


def extract_keywords():
    # Path to the neighboring building-code-mcp repo
    mcp_repo_path = os.path.abspath(os.path.join("..", "Canada_building_code_mcp"))
    maps_pattern = os.path.join(mcp_repo_path, "maps", "*.json")
    map_files = glob.glob(maps_pattern)

    # Derive synonyms dynamically from the mcp_server.py
    import sys

    sys.path.append(os.path.join(mcp_repo_path))
    try:
        from building_code_mcp.mcp_server import SYNONYMS

        common_synonyms = set()
        for key, vals in SYNONYMS.items():
            common_synonyms.add(key.lower())
            for v in vals:
                common_synonyms.add(v.lower())
    except ImportError:
        print("Warning: Could not import SYNONYMS from building_code_mcp. Falling back to empty.")
        common_synonyms = set()

    keywords = set(common_synonyms)

    print(f"Processing {len(map_files)} map files...")

    for map_file in map_files:
        try:
            with open(map_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for section in data.get("sections", []):
                    section_keywords = section.get("keywords", [])
                    if isinstance(section_keywords, list):
                        for kw in section_keywords:
                            if isinstance(kw, str) and len(kw) > 2:
                                keywords.add(kw.lower())
        except Exception as e:
            print(f"Error processing {map_file}: {e}")

    # Filter keywords (only alphabetic, no numbers unless common like 'Part 3')
    # and remove extremely common words if they are too noisy
    filtered_keywords = sorted([kw for kw in keywords if kw.isalpha() or " " in kw])

    # Write to config/keywords.py
    output_path = os.path.join("config", "keywords.py")
    os.makedirs("config", exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('"""\nAuto-generated building code keywords derived from map files.\n"""\n\n')
        f.write("VALID_KEYWORDS = [\n")
        for kw in filtered_keywords:
            f.write(f"    {repr(kw)},\n")
        f.write("]\n")

    print(f"Extracted {len(filtered_keywords)} keywords to {output_path}")


if __name__ == "__main__":
    extract_keywords()
