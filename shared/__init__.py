"""Small helpers with no knowledge of this product: an IP, an address, a tag.

The bottom of the tree, with ``data``. It imports nothing local, which is what
makes it safe for anything above to import.
"""

#: The packages this one may import. The guard in
#: ``tests/structure/test_import_manifests.py`` reads it, and fails on an
#: import that is not listed AND on a listed package nothing imports.
ALLOWED_IMPORTS: tuple[str, ...] = ()
