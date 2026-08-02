"""The CCM-mirrored asset trees, and where their bytes come from.

One list, three consumers, because they used to be three lists and drifted:

* ``code_chronicle/urls.py`` serves these prefixes from disk in development.
* ``core/management/commands/sync_images.py`` publishes them to R2.
* ``asset_path_prefixes`` in the Terraform Cloudflare module routes them to
  the edge Worker in production.

The Terraform list lives in another repository and cannot import this one, so
it carries a comment naming this constant.  Keep the two in step by hand.  A
prefix present here and absent there uploads to R2 and then returns 404,
which is how ``elaws/`` went missing from production.
"""

from pathlib import Path

# Every URL path prefix whose bytes are CCM build artifacts rather than
# application static files.  Order is not significant.
MIRRORED_PREFIXES: tuple[str, ...] = ("documents", "elaws", "amended", "laws")

# CCM does not gather the trees under one root: ``laws/`` is a build *output*,
# while ``documents/`` and ``elaws/`` are *intermediates*.  The sync searches
# these roots in order and takes each prefix from the first root that holds it.
DEFAULT_ASSET_SOURCES: tuple[str, ...] = (
    str(Path("..") / "CodeChronicleMapping" / "data" / "outputs"),
    str(Path("..") / "CodeChronicleMapping" / "data" / "intermediates" / "images"),
)
