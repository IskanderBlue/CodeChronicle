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

* **Anonymous requests only.**  The tier gate (:mod:`accounts.access`) makes the
  same URL render differently for a Pro reader, and a validator that ignored
  the reader would let somebody who has just subscribed keep a cached locked
  page.  Anonymous readers are uniformly free-tier, so one stamp describes
  them all — and they are exactly the crawlers this is aimed at.
* **The stamp is the corpus load stamp**, ``CorpusCurrency.refreshed_at``.
  It is a single primary-key read, already served on every page by
  :mod:`web.context_processors`, and ``load_edition`` bumps it.
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


#: How long the edge may serve a stored copy before it revalidates.  Short,
#: because nothing purges the edge on deploy: an hour bounds how long a
#: template change can stay invisible.  Going stale is cheap — Cloudflare
#: revalidates with ``If-Modified-Since`` and the origin answers 304, so an
#: expired entry costs one conditional request rather than a re-render.
EDGE_MAX_AGE = 3600

#: How long nginx on the VM may keep an anonymous page.  Long, because the
#: bots come back to the same URL days later: over 7 days to 24 September 2026,
#: 76% of the read-page requests were for a URL already fetched that week, and
#: the one-hour edge copy had gone.  A cache hit in nginx runs no Django and
#: reads no Neon row, so it lets the compute sleep; a 304 from Django does not,
#: because the check reads ``CorpusCurrency``.
#:
#: nginx obeys ``X-Accel-Expires`` and removes it, so the edge and the browser
#: still see only ``Cache-Control``.  Nothing checks the stamp on a hit, so the
#: copy must be cleared when the pages change: ``deploy-web.sh`` clears it on
#: every deploy, and a corpus load needs the clear by hand (``CLAUDE.md``).
#: This value is the limit when somebody forgets.
ORIGIN_CACHE_SECONDS = 7 * 24 * 3600


def corpus_conditional(
    view: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
    """Give a read surface a corpus-scoped validator and a cache policy.

    The two belong together.  The validator deliberately differs between an
    anonymous reader and a signed-in one, so a shared cache that ignored the
    difference would hand a free-tier page to a Pro subscriber.  Keeping both
    in one decorator means a new surface cannot pick up half of it.

    The policy says so directly rather than through ``Vary: Cookie``:

    * **Signed in — ``private, no-store``.**  No shared cache may keep it, so
      the tier gate holds even if the edge is misconfigured.  This is the
      guarantee ``Vary: Cookie`` used to make, stated as a refusal instead of
      as a cache key, which is stronger because it does not depend on the
      cache honouring a key it may not support.
    * **Anonymous — ``public``, revalidated by the browser, stored by the
      edge.**  ``max-age=0, must-revalidate`` keeps a reader's own browser
      asking (they should see a new edition immediately); ``s-maxage`` lets
      Cloudflare answer without touching Django at all.

    ``Vary: Cookie`` is dropped by :class:`PublicCacheVary`, which has to run
    outside the middleware that adds it.  See that class for why.
    """
    conditional = last_modified(corpus_last_modified)(view)

    @functools.wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        response = conditional(request, *args, **kwargs)
        if getattr(request.user, "is_authenticated", False):
            response["Cache-Control"] = "private, no-store"
        elif response.status_code in (200, 304):
            response["Cache-Control"] = (
                f"public, max-age=0, must-revalidate, s-maxage={EDGE_MAX_AGE}"
            )
            # Only a full body.  nginx strips the conditional headers when it
            # fills its cache, so a 304 here is a reader's own revalidation,
            # which has no body to keep.
            if response.status_code == 200:
                response["X-Accel-Expires"] = str(ORIGIN_CACHE_SECONDS)
        else:
            # A redirect to the login page is about the reader, not the
            # corpus.  Stored publicly it would be served to everybody.
            response["Cache-Control"] = "private, no-store"
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


class PublicCacheVary:
    """Drop ``Vary: Cookie`` from responses we marked publicly cacheable.

    Cloudflare honours ``Vary`` only on ``Accept-Encoding``.  Any other value
    on an HTML response makes it uncacheable at the edge — which is the entire
    cost problem this work exists to fix.

    ``SessionMiddleware`` adds the header whenever anything reads the session,
    and :func:`corpus_conditional` reads ``request.user`` to decide whether the
    reader gets a validator at all.  So the header is added *after* the view
    and its decorators have finished, and only a middleware outside that one
    can take it off again.  This must therefore sit **first** in
    ``MIDDLEWARE``, so its ``process_response`` runs last.

    Two conditions keep it narrow, and both matter:

    * **Only responses that say ``public``.**  That marking is made in one
      place, for anonymous readers, on a corpus page.  A signed-in reader's
      page says ``private, no-store`` and is untouched.
    * **Never a response carrying ``Set-Cookie``.**  A response that hands out
      a cookie is one no shared cache will store anyway, so removing the
      ``Vary`` would gain nothing and would strip a real signal from any
      private cache that does store it.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if "public" not in response.get("Cache-Control", ""):
            return response
        if response.cookies or response.has_header("Set-Cookie"):
            return response
        varies = [
            part.strip()
            for part in response.get("Vary", "").split(",")
            if part.strip() and part.strip().lower() != "cookie"
        ]
        if varies:
            response["Vary"] = ", ".join(varies)
        elif response.has_header("Vary"):
            del response["Vary"]
        return response
