"""Wipe map data and stale query cache (and, opt-in, provenance) before a reload.

Scope:
  * Legacy map models  - CodeMap, CodeMapNode, KeywordIDF.  The
    map-abstraction the provenance display migration stopped reading;
    slated for outright removal in tasks/provenance/5-cleanup.md.
  * Query cache         - QueryCache, QueryPrompt.  Cached LLM-parsed
    queries and result metadata that point at editions about to change.
  * Provenance models   - OPT-IN via ``--wipe-provenance``.  Code and
    everything that CASCADEs from it: ProvinceCode, CodeEdition,
    Regulation, RegulationClause, RegulationAsset, CodeEditionProvision,
    CodeEditionProvisionVersion, CodeEditionProvisionVersionClause,
    ProvisionVersionTable, ProvisionMapping.  ``load_edition`` self-cleans
    only the *edition it reloads*, so stale editions you are NOT reloading
    (e.g. leftover test fixtures) survive that per-edition clean -- the
    flag wipes them too for a true clean slate.

Deliberately NOT touched:
  * User accounts + SearchHistory - real user data, never touched here.

Runs in a single transaction so a mid-wipe failure rolls back cleanly.
"""

from typing import Any

from coloured_logger import Logger
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    CodeEditionProvisionVersionClause,
    CodeMap,
    CodeMapNode,
    KeywordIDF,
    ProvinceCode,
    ProvisionMapping,
    ProvisionVersionTable,
    QueryCache,
    QueryPrompt,
    Regulation,
    RegulationAsset,
    RegulationClause,
)

logger = Logger(__name__)


class Command(BaseCommand):
    help = (
        "Wipe legacy map data (CodeMap/CodeMapNode/KeywordIDF) and query cache.  "
        "Add --wipe-provenance to also clear all provenance (Code + cascade).  "
        "Leaves user data untouched."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip the interactive confirmation prompt.",
        )
        parser.add_argument(
            "--wipe-provenance",
            action="store_true",
            help=(
                "Also wipe all provenance (Code/CodeEdition/Regulation/... + "
                "cascade) for a true pre-reload clean slate.  Off by default: "
                "without it, only legacy maps + query cache are cleared."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        wipe_provenance = options["wipe_provenance"]

        # Count first so the operator sees the blast radius before committing.
        # Legacy maps + query cache are deleted explicitly; provenance is
        # deleted via a single Code cascade, but we count each table so the
        # preview is honest about what the cascade will take.
        legacy_counts = {
            "CodeMapNode": CodeMapNode.objects.count(),
            "CodeMap": CodeMap.objects.count(),
            "KeywordIDF": KeywordIDF.objects.count(),
            "QueryCache": QueryCache.objects.count(),
            "QueryPrompt": QueryPrompt.objects.count(),
        }
        prov_counts = {
            "Code": Code.objects.count(),
            "ProvinceCode": ProvinceCode.objects.count(),
            "CodeEdition": CodeEdition.objects.count(),
            "Regulation": Regulation.objects.count(),
            "RegulationClause": RegulationClause.objects.count(),
            "RegulationAsset": RegulationAsset.objects.count(),
            "CodeEditionProvision": CodeEditionProvision.objects.count(),
            "CodeEditionProvisionVersion": CodeEditionProvisionVersion.objects.count(),
            "CodeEditionProvisionVersionClause": (
                CodeEditionProvisionVersionClause.objects.count()
            ),
            "ProvisionVersionTable": ProvisionVersionTable.objects.count(),
            "ProvisionMapping": ProvisionMapping.objects.count(),
        } if wipe_provenance else {}

        counts = {**legacy_counts, **prov_counts}
        total = sum(counts.values())

        self.stdout.write("Rows to delete:")
        self.stdout.write("  [legacy maps + query cache]")
        for name, n in legacy_counts.items():
            self.stdout.write(f"    {name:<33} {n:>8}")
        if wipe_provenance:
            self.stdout.write("  [provenance (Code + cascade)]")
            for name, n in prov_counts.items():
                self.stdout.write(f"    {name:<33} {n:>8}")
        else:
            self.stdout.write("  [provenance] preserved (pass --wipe-provenance to clear)")
        self.stdout.write(f"  {'TOTAL':<35} {total:>8}")

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

        prov_deleted: dict[str, int] = {}
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

            # Provenance: a single Code wipe cascades the whole graph (editions,
            # regulations, clauses, assets, provisions, versions, tables,
            # mappings, province links).  Legacy maps have no FK to Code, and
            # SearchHistory references only User -- neither blocks this.
            if wipe_provenance:
                _, by_model = Code.objects.all().delete()
                prov_deleted = {k.split(".")[-1]: v for k, v in by_model.items()}

        # Recompute the matview now that its CodeMapNode source is empty.  This
        # MUST run outside the atomic block: REFRESH ... CONCURRENTLY cannot
        # execute inside a transaction.  With the source gone the view recomputes
        # to zero rows -- the matview equivalent of a wipe.
        KeywordIDF.refresh()

        logger.info(
            "Wiped legacy data: %d map nodes, %d maps, %d query-cache rows, "
            "%d query-prompt rows; refreshed keyword_idf matview (%d rows -> 0)",
            legacy_counts["CodeMapNode"],
            legacy_counts["CodeMap"],
            legacy_counts["QueryCache"],
            legacy_counts["QueryPrompt"],
            legacy_counts["KeywordIDF"],
        )
        if wipe_provenance:
            logger.info(
                "Wiped provenance via Code cascade: %d rows across %d tables (%s)",
                sum(prov_deleted.values()),
                len(prov_deleted),
                ", ".join(f"{k}={v}" for k, v in sorted(prov_deleted.items())),
            )

        wiped_rows = total - legacy_counts["KeywordIDF"]
        self.stdout.write(self.style.SUCCESS(
            f"Wiped {wiped_rows} rows "
            f"({'incl. provenance' if wipe_provenance else 'legacy + cache only'}); "
            f"refreshed keyword_idf matview to empty."
        ))
