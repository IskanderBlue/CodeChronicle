"""Wipe legacy map data and stale query cache ahead of a fresh edition load.

Scope (deliberately narrow):
  * Legacy map models  - CodeMap, CodeMapNode, KeywordIDF.  The
    map-abstraction the provenance display migration stopped reading;
    slated for outright removal in tasks/provenance/5-cleanup.md.
  * Query cache         - QueryCache, QueryPrompt.  Cached LLM-parsed
    queries and result metadata that point at editions about to change.

Deliberately NOT touched:
  * Provenance models (Code/CodeEdition/.../ProvisionMapping) - these are
    self-cleaned per-edition by ``load_edition`` (it deletes an edition's
    provisions+regulations before reloading), so a blanket wipe would only
    risk dropping editions you are not reloading.
  * User accounts + SearchHistory - real user data, never touched here.

Runs in a single transaction so a mid-wipe failure rolls back cleanly.
"""

from typing import Any

from coloured_logger import Logger
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    CodeMap,
    CodeMapNode,
    KeywordIDF,
    QueryCache,
    QueryPrompt,
)

logger = Logger(__name__)


class Command(BaseCommand):
    help = "Wipe legacy map data (CodeMap/CodeMapNode/KeywordIDF) and query cache."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip the interactive confirmation prompt.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Count first so the operator sees the blast radius before committing.
        counts = {
            "CodeMapNode": CodeMapNode.objects.count(),
            "CodeMap": CodeMap.objects.count(),
            "KeywordIDF": KeywordIDF.objects.count(),
            "QueryCache": QueryCache.objects.count(),
            "QueryPrompt": QueryPrompt.objects.count(),
        }
        total = sum(counts.values())

        self.stdout.write("Rows to delete:")
        for name, n in counts.items():
            self.stdout.write(f"  {name:<14} {n:>8}")
        self.stdout.write(f"  {'TOTAL':<14} {total:>8}")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to wipe; already clean."))
            return

        if not options["no_input"]:
            confirm = input(
                "\nThis permanently deletes the rows above. Type 'yes' to proceed: "
            )
            if confirm.strip().lower() != "yes":
                self.stdout.write(self.style.WARNING("Aborted; nothing deleted."))
                return

        with transaction.atomic():
            # Deletion order matters: QueryCache.prompt is on_delete=PROTECT,
            # so QueryCache rows must go before the QueryPrompt rows they pin.
            # CodeMapNode CASCADEs from CodeMap, but deleting nodes first keeps
            # the cascade explicit and the reported counts honest.
            #
            # KeywordIDF is NOT deleted here: it is an unmanaged materialized
            # view (managed=False) whose rows are derived from CodeMapNode, so
            # a row-level DELETE raises "cannot change materialized view".  We
            # empty it by removing its source rows above, then REFRESH below.
            CodeMapNode.objects.all().delete()
            CodeMap.objects.all().delete()
            QueryCache.objects.all().delete()
            QueryPrompt.objects.all().delete()

        # Recompute the matview now that its CodeMapNode source is empty.  This
        # MUST run outside the atomic block: REFRESH ... CONCURRENTLY cannot
        # execute inside a transaction.  With the source gone the view recomputes
        # to zero rows -- the matview equivalent of a wipe.
        KeywordIDF.refresh()

        logger.info(
            "Wiped legacy data: %d map nodes, %d maps, %d query-cache rows, "
            "%d query-prompt rows; refreshed keyword_idf matview "
            "(%d rows -> 0)",
            counts["CodeMapNode"],
            counts["CodeMap"],
            counts["QueryCache"],
            counts["QueryPrompt"],
            counts["KeywordIDF"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Wiped {total - counts['KeywordIDF']} rows; "
            f"refreshed keyword_idf matview to empty."
        ))
