"""The code text itself: its provenance, its addresses and its exhibits.

The one edge up to ``accounts`` is ``sitemaps.py``: the sitemap is free-tier
scoped, so it must ask what a free reader may open. The rest of this package
takes the gate as a ``Callable[[str], bool]`` and never learns what a tier
is.
"""

#: The packages this one may import. The guard in
#: ``tests/structure/test_import_manifests.py`` reads it, and fails on an
#: import that is not listed AND on a listed package nothing imports.
ALLOWED_IMPORTS = (
    "shared",
    "data",
    "core",
    "accounts",
)
