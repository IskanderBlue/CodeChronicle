"""The CCM-mirrored asset trees, and where their bytes come from.

One list, three consumers, because they used to be three lists and drifted:

* ``code_chronicle/urls.py`` serves these prefixes from disk in development.
* ``corpus/management/commands/sync_images.py`` publishes them to R2.
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

# Prefixes the edge Worker refuses to serve without a valid token (see
# ``corpus.asset_signing``).  ``documents/`` holds the whole-page scans of the
# pre-e-Laws editions — the primary evidence, one image per printed page — and
# its keys are sequential, so anybody can walk an edition without ever loading
# a page we gated.  A token cannot be guessed, and Django only mints one while
# rendering a page ``accounts.access`` already allowed, so the asset gate is the
# page gate.
#
# The other three stay open on purpose.  ``laws/`` and ``elaws/`` are figure
# *fragments* referenced from free and paid editions alike, and ``laws/`` paths
# are baked into stored e-Laws HTML that this product renders verbatim — signing
# them would mean rewriting that HTML, which is the one thing the render path
# must not do.
#
# This list must match ``signed_path_prefixes`` in the Terraform Cloudflare
# module.  A prefix added here and not there stays open in production; added
# there and not here, every one of its images breaks.
SIGNED_PREFIXES: tuple[str, ...] = ("documents",)

# CCM does not gather the trees under one root: ``laws/`` is a build *output*,
# while ``documents/`` and ``elaws/`` are *intermediates*.  The sync searches
# these roots in order and takes each prefix from the first root that holds it.
DEFAULT_ASSET_SOURCES: tuple[str, ...] = (
    str(Path("..") / "CodeChronicleMapping" / "data" / "outputs"),
    str(Path("..") / "CodeChronicleMapping" / "data" / "intermediates" / "images"),
)
