"""Template context processors for site-wide chrome."""

from typing import Any

from django.http import HttpRequest

from core.models import CorpusCurrency


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
        "coverage_end": obj.coverage_end,
    }
