"""Delete reading records past the retention period the Privacy Policy states.

The Privacy Policy says the record of which provisions an account opens is kept
for up to two years and then deleted. That sentence is a promise, and a promise
with nothing behind it is worse than no promise: it is a statement to a
regulator that the operator cannot support.

Run on a schedule, and reuse the schedule that exists. The production VM is
Container-Optimized OS and has no cron, so anything periodic is a systemd timer
in Terraform's ``startup.sh`` — a rebuild loses anything added by hand.
``cc-backup.service`` already runs a command inside the web container daily, so
this needs no unit of its own: it is one more line in that script, after the
backup, with its exit code kept out of the backup's healthchecks.io ping. A
purge failure must not redden the check that means "the backup stopped".

Two decisions:

* **The cutoff is measured from the last fetch, not the first.** A provision an
  account still reads every month is a live record, and deleting it while the
  reading continues would only make the account look new the next day. The
  promise is about how long we keep a record of something you did, and the
  thing you did most recently is what dates it.
* **It reports before it deletes**, and ``--apply`` is required. Every other
  destructive command in this repository reads the same way, and a retention
  job that quietly removes the wrong two years is a job nobody can audit.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import ProvisionFetch

#: What the Privacy Policy says, in days.  Change both together.
RETENTION_DAYS = 730


class Command(BaseCommand):
    help = "Delete ProvisionFetch rows older than the stated retention period."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without this the command only reports.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=RETENTION_DAYS,
            help=f"Retention period in days (default {RETENTION_DAYS}).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        stale = ProvisionFetch.objects.filter(last_fetched_at__lt=cutoff)
        count = stale.count()

        self.stdout.write(
            f"Retention: {days} days. Cutoff: {cutoff:%Y-%m-%d}. "
            f"Rows last fetched before then: {count}."
        )
        if not count:
            return
        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Dry run. Pass --apply to delete."))
            return

        deleted, _ = stale.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} reading records."))
