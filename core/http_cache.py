"""Conditional responses for the read surfaces — the anonymous path only.

A provision page is expensive: ``provision_permalink`` renders the matched
provision *and its whole subtree*, so one request for a root can pull well
over a megabyte out of the database.  Nothing about that page changes between
corpus loads, and until now nothing said so, so a crawler that fetched the
same URL six times paid full price six times.

:func:`corpus_last_modified` supplies the missing statement.  Django's
``@last_modified`` decorator turns the second fetch into a ``304 Not
Modified``, which runs no view code and reads no rows.

Three rules hold this together:

* **Anonymous requests only.**  The tier gate (:mod:`core.access`) makes the
  same URL render differently for a Pro reader, and a validator that ignored
  the reader would let somebody who has just subscribed keep a cached locked
  page.  Anonymous readers are uniformly free-tier, so one stamp describes
  them all — and they are exactly the crawlers this is aimed at.
* **The stamp is the corpus load stamp**, ``CorpusCurrency.refreshed_at``.
  It is a single primary-key read, already served on every page by
  :mod:`core.context_processors`, and ``load_edition`` bumps it.
* **A deploy bumps it too**, because ``scripts/entrypoint.sh`` runs
  ``refresh_corpus_currency``.  Without that a template change would keep
  answering 304 and the site would serve last week's markup.  This errs
  toward re-rendering: a restart costs a re-crawl, and showing stale legal
  text costs more than that.

One limit worth stating: an HTTP date carries **whole seconds**, so a load
that finishes in the same second as a reader's fetch cannot invalidate that
reader's copy.  A corpus load takes minutes, so this has no practical reach,
but it is why the tests move the stamp explicitly rather than race the clock.
"""

import functools
from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import last_modified

from core.models import CorpusCurrency


def corpus_last_modified(
    request: HttpRequest, *args: Any, **kwargs: Any
) -> datetime | None:
    """When the corpus behind this page last changed, for anonymous readers.

    Returns ``None`` — meaning "no validator, always render" — for a
    signed-in reader, for the print routes, and before the first edition load.
    """
    if getattr(request.user, "is_authenticated", False):
        return None
    # The print routes send an anonymous reader to the login page, so they
    # have no anonymous body to validate.  Answering 304 there would let a
    # client reuse a reading page's stamp to get an empty answer for an
    # exhibit it never fetched.
    if kwargs.get("for_print"):
        return None
    currency = CorpusCurrency.get_solo()
    if currency is None or currency.refreshed_at is None:
        return None
    # HTTP dates carry whole seconds.  Truncating here means the value we
    # compare against is the value we sent, rather than one that is always
    # a fraction of a second newer than the client's copy of it.
    return currency.refreshed_at.replace(microsecond=0)


def corpus_conditional(
    view: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
    """Give a read surface a corpus-scoped validator and a ``Vary: Cookie``.

    The two belong together.  The validator deliberately differs between an
    anonymous reader and a signed-in one, so any shared cache must key on the
    cookie — otherwise it hands a free-tier page to a Pro subscriber.  Keeping
    them in one decorator means a new surface cannot pick up half of it.
    """
    conditional = last_modified(corpus_last_modified)(view)

    @functools.wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        response = conditional(request, *args, **kwargs)
        patch_vary_headers(response, ("Cookie",))
        # Django's ``condition`` decorator stamps every safe-method response,
        # whatever its status.  Only a body we would serve again should carry
        # a validator: a 404 that handed one out could later be answered 304,
        # telling a crawler its cached miss is still current, and a redirect
        # to the login page is about the reader rather than the corpus.  304
        # keeps it because the specification requires it there.
        if response.status_code not in (200, 304) and response.has_header(
            "Last-Modified"
        ):
            del response["Last-Modified"]
        return response

    return wrapper
