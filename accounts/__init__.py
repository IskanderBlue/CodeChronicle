"""Who the reader is, what they may open, and what they pay.

``accounts`` and ``telemetry`` sit at the same height and neither imports the
other. That is why the guard checks the graph for a cycle rather than against
rank numbers: a number would claim an order between them that does not
exist.
"""

#: The packages this one may import. The guard in
#: ``tests/structure/test_import_manifests.py`` reads it, and fails on an
#: import that is not listed AND on a listed package nothing imports.
ALLOWED_IMPORTS = (
    "shared",
    "core",
)
