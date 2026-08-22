"""The models, the migrations and the admin. Every other package sits above.

It keeps its name because Django names it in strings no import rewriter sees:
``AUTH_USER_MODEL``, ``DJSTRIPE_SUBSCRIBER_MODEL``, every
``ForeignKey("core.X")`` and every migration.
"""

#: The packages this one may import. The guard in
#: ``tests/structure/test_import_manifests.py`` reads it, and fails on an
#: import that is not listed AND on a listed package nothing imports.
ALLOWED_IMPORTS = (
    "data",
)
