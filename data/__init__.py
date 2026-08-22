"""Fixed reference data: the vocabularies, the limits and the article spines.

The bottom of the tree, with ``shared``. These modules hold values, not
behaviour, so nothing here needs to read a model.
"""

#: The packages this one may import. The guard in
#: ``tests/structure/test_import_manifests.py`` reads it, and fails on an
#: import that is not listed AND on a listed package nothing imports.
ALLOWED_IMPORTS: tuple[str, ...] = ()
