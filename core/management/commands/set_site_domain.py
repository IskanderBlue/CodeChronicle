"""Point the ``django.contrib.sites`` row at the domain this deployment serves.

Django ships ``SITE_ID = 1`` pre-filled with ``example.com``.  Nothing in the
app writes to that row, so until this command runs, every absolute URL built
from the Sites framework names ``example.com``: the ``<loc>`` of every entry in
``/sitemap.xml``, and the links allauth puts in confirmation and password-reset
email.  Both failures are silent — the pages render, the email sends — which is
why this is a command rather than a comment.

Run it once per environment, and again after a domain change::

    python manage.py set_site_domain --domain codechronicle.net
    python manage.py set_site_domain            # takes ALLOWED_HOSTS[0]
"""

from typing import Any

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Set the Site row's domain (used by sitemap URLs and allauth email)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--domain",
            default=None,
            help="Domain to store, e.g. codechronicle.net. Defaults to ALLOWED_HOSTS[0].",
        )
        parser.add_argument(
            "--name",
            default="CodeChronicle",
            help="Human-readable site name.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        domain = options["domain"]
        if not domain:
            hosts = [h.strip() for h in settings.ALLOWED_HOSTS if h.strip()]
            # A wildcard host is not a domain, and "localhost" is not one either
            # in the sense that matters here, but it is a legitimate dev value —
            # so only the wildcard is rejected.
            hosts = [h for h in hosts if h != "*"]
            if not hosts:
                raise CommandError(
                    "No --domain given and ALLOWED_HOSTS has no usable entry."
                )
            domain = hosts[0]

        site, created = Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={"domain": domain, "name": options["name"]},
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} Site {site.pk}: {site.domain} ({site.name})")
        )
