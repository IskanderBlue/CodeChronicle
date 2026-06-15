"""
URL configuration for code_chronicle project.
"""
from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import URLPattern, URLResolver, include, path
from django.views.generic.base import RedirectView
from django.views.static import serve

from api.views import api


class FaviconRedirectView(RedirectView):
    """Bounce the unprompted ``/favicon.ico`` requests to the SVG in static/.

    The static URL is resolved lazily (per request, in ``get_redirect_url``)
    rather than at module import.  Under ``ManifestStaticFilesStorage`` the
    hashed URL is read from the ``staticfiles.json`` manifest, which only
    exists after ``collectstatic`` — so calling ``staticfiles_storage.url()``
    while the URLconf is merely *imported* (e.g. during ``manage.py check`` or
    the ``migrate`` that precedes ``collectstatic`` at container boot) raises
    "Missing staticfiles manifest entry".  Deferring to request time means the
    import is side-effect-free and the manifest is always present by the time
    the URL is actually built.

    ``permanent=False`` — a 301 here would be cached by browsers/CDNs and
    survive an icon swap.
    """

    permanent = False

    def get_redirect_url(self, *args: object, **kwargs: object) -> str | None:
        # Resolve the hashed static URL now (request time), then hand off to
        # RedirectView's usual %-substitution / append-query handling.
        self.url = staticfiles_storage.url('favicon.svg')
        return super().get_redirect_url(*args, **kwargs)


# Explicit union so the list accepts both URLResolver entries (include(...))
# and URLPattern entries (a path() to a view), which we append below.
urlpatterns: list[URLResolver | URLPattern] = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    path('accounts/', include('allauth.urls')),
    path('stripe/', include('djstripe.urls', namespace='djstripe')),
    path('favicon.ico', FaviconRedirectView.as_view()),
    path('', include('core.urls')),
]

# Development-only asset serving.  CCM-mirrored trees (documents/,
# amended/, laws/) live under settings.ASSET_ROOT with paths verbatim,
# so inline ``<img src="/laws/images/...">`` references in version HTML
# resolve through these patterns.  In production these prefixes are
# served by nginx aliasing to ASSET_ROOT — Django stays out of the path.
if settings.DEBUG:
    for _prefix in ("documents", "amended", "laws"):
        urlpatterns.append(path(
            f"{_prefix}/<path:path>",
            serve,
            {"document_root": str(settings.ASSET_ROOT / _prefix)},
        ))
