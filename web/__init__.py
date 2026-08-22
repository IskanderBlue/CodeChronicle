"""Delivery: the URLs, the views, the API and the middleware.

The top of the tree. Nothing imports ``web``, so every upward import in the
product ends here.
"""

#: The packages this one may import. The guard in
#: ``tests/structure/test_import_manifests.py`` reads it, and fails on an
#: import that is not listed AND on a listed package nothing imports.
ALLOWED_IMPORTS = (
    "shared",
    "data",
    "core",
    "accounts",
    "telemetry",
    "corpus",
    "search",
)
