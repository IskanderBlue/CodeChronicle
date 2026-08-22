"""
URL configuration for code_chronicle project.
"""
from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import index as sitemap_index
from django.contrib.sitemaps.views import sitemap
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import URLPattern, URLResolver, include, path
from django.views.generic.base import RedirectView, TemplateView
from django.views.static import serve

from corpus.sitemaps import SITEMAPS
from data.assets import MIRRORED_PREFIXES
from web.api.views import api


class RobotsView(TemplateView):
    """``/robots.txt`` — the disallow list plus an absolute sitemap link.

    A template rather than a static file because the ``Sitemap:`` line must be
    absolute, and the host differs between dev and production.  It is built
    from the request (not from ``ALLOWED_HOSTS``) so a preview deployment
    advertises its own sitemap instead of production's.
    """

    template_name = "robots.txt"
    content_type = "text/plain"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["sitemap_url"] = self.request.build_absolute_uri("/sitemap.xml")
        return context


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
    path('robots.txt', RobotsView.as_view()),
    # Index + per-section pattern rather than one flat sitemap.xml: the
    # provision section already runs to thousands of URLs and grows with every
    # edition loaded, and a section that exceeds ``Sitemap.limit`` can only be
    # paginated through an index.  The section view keeps Django's default
    # ``name`` because the index view reverses it to build its own links.
    path('sitemap.xml', sitemap_index, {'sitemaps': SITEMAPS}),
    path(
        'sitemap-<section>.xml',
        sitemap,
        {'sitemaps': SITEMAPS},
        name='django.contrib.sitemaps.views.sitemap',
    ),
    path('', include('web.urls')),
]

# Development-only asset serving.  CCM-mirrored trees (documents/,
# elaws/, amended/, laws/) live under settings.ASSET_ROOT with paths
# verbatim, so both page/table ``image`` keys (e.g. "documents/…webp",
# "elaws/…jpg") and inline ``<img src="/laws/images/...">`` references in
# version HTML resolve through these patterns.
#
# In production a Cloudflare Worker answers these same paths from R2 at the
# edge, so neither nginx nor Django is in the path and the URLs need no
# rewrite.  The prefix list below must therefore stay in step with
# MIRRORED_PREFIXES in corpus/management/commands/sync_images.py and with
# asset_path_prefixes in the Terraform Cloudflare module.  A prefix that is
# missing from the Terraform list works in dev and 404s in production.
if settings.DEBUG:
    for _prefix in MIRRORED_PREFIXES:
        urlpatterns.append(path(
            f"{_prefix}/<path:path>",
            serve,
            {"document_root": str(settings.ASSET_ROOT / _prefix)},
        ))
