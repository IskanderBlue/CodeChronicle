"""What the product records about its own use, and what it reports back.

It never decides anything. ``/insights/`` reports the coverage a key has taken;
a person acts on it. See "Bulk extraction" in CLAUDE.md.
"""

#: The packages this one may import. The guard in
#: ``tests/structure/test_import_manifests.py`` reads it, and fails on an
#: import that is not listed AND on a listed package nothing imports.
ALLOWED_IMPORTS = (
    "shared",
    "data",
    "core",
)
