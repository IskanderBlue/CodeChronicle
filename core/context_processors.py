"""Template context processors for site-wide chrome."""

from typing import Any

from django.http import HttpRequest

from core.models import CorpusCurrency
from core.seo import (
    DEFAULT_DESCRIPTION,
    DEFAULT_TITLE,
    SITE_NAME,
    SOCIAL_IMAGE_ALT,
    SOCIAL_IMAGE_HEIGHT,
    SOCIAL_IMAGE_PATH,
    SOCIAL_IMAGE_WIDTH,
)


def page_metadata(request: HttpRequest) -> dict[str, Any]:
    """Site-wide values the ``<title>``, the canonical link and the card share.

    A link somebody forwards — in email, in Slack, on LinkedIn — is rendered
    from these tags alone.  They live here rather than in the templates
    because the description a crawler reads and the description a search
    engine prints must be one string: two that mean the same thing disagree
    within a month.

    ``site_origin`` is scheme + host, which the canonical link and ``og:url``
    both need to make a relative path absolute.  A crawler resolves neither
    against the page it is reading.
    """
    return {
        "site_name": SITE_NAME,
        "site_origin": f"{request.scheme}://{request.get_host()}",
        "default_title": DEFAULT_TITLE,
        "default_description": DEFAULT_DESCRIPTION,
        "social_image_path": SOCIAL_IMAGE_PATH,
        "social_image_alt": SOCIAL_IMAGE_ALT,
        "social_image_width": SOCIAL_IMAGE_WIDTH,
        "social_image_height": SOCIAL_IMAGE_HEIGHT,
    }


def masthead_currency(_request: HttpRequest) -> dict[str, Any]:
    """Expose the precomputed corpus/consolidation stamp to the masthead.

    A single PK read of the :class:`~core.models.CorpusCurrency` singleton
    (refreshed once per data load).  Returns an empty dict before the first
    load so the masthead falls back to the corpus-label default and hides the
    currency side — never a faked date.
    """
    obj = CorpusCurrency.get_solo()
    if obj is None:
        return {}
    return {
        "corpus_label": obj.corpus_label,
        "corpus_span": obj.corpus_span,
        "data_current_to": obj.data_current_to,
        "coverage_start": obj.coverage_start,
        "coverage_end": obj.coverage_end,
    }
