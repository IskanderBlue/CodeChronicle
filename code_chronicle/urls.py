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

# Explicit union so the list accepts both URLResolver entries (include(...))
# and URLPattern entries (a path() to a view), which we append below.
urlpatterns: list[URLResolver | URLPattern] = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    path('accounts/', include('allauth.urls')),
    path('stripe/', include('djstripe.urls', namespace='djstripe')),
    # Browsers and crawlers request /favicon.ico unprompted; the real icon is
    # the SVG in static/, so bounce the legacy path there.  permanent=False —
    # a 301 here would be cached by browsers/CDNs and survive an icon swap.
    path('favicon.ico', RedirectView.as_view(
        url=staticfiles_storage.url('favicon.svg'), permanent=False,
    )),
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
