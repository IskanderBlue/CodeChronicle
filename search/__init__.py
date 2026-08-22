"""The search pipeline, from a question in words to the cards on the page.

The edge up to ``accounts`` is the tier split, which runs before the display
limit so a gated searcher's cards are filled from editions they can open.
"""

#: The packages this one may import. The guard in
#: ``tests/structure/test_import_manifests.py`` reads it, and fails on an
#: import that is not listed AND on a listed package nothing imports.
ALLOWED_IMPORTS = (
    "shared",
    "data",
    "core",
    "accounts",
    "corpus",
)
