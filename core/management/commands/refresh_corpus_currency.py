"""Recompute the masthead corpus/consolidation stamp (CorpusCurrency).

``load_edition`` refreshes this automatically at the end of every load, so you
only need this command to backfill an environment whose data was loaded before
the stamp existed (or to recompute after data was changed out-of-band)."""

from typing import Any

from django.core.management.base import BaseCommand

from core.models import CorpusCurrency


class Command(BaseCommand):
    help = "Recompute the masthead CorpusCurrency stamp from the loaded provenance corpus."

    def handle(self, *args: Any, **options: Any) -> None:
        obj = CorpusCurrency.refresh()
        self.stdout.write(
            self.style.SUCCESS(
                f"CorpusCurrency refreshed: {obj.corpus_label} "
                f"({obj.corpus_span or 'no span'}) — "
                f"current to {obj.data_current_to or 'n/a'}"
            )
        )
