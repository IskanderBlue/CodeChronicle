"""Load a CCM consolidated edition JSON into provenance models."""

import json
from datetime import date
from pathlib import Path
from typing import Any

from coloured_logger import Logger
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionVersionTable,
    Regulation,
    RegulationClause,
)

logger = Logger(__name__)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _require_date(value: str | None, field: str) -> date:
    if not value:
        raise ValueError(f"Missing required date field: {field}")
    return date.fromisoformat(value)


class Command(BaseCommand):
    help = "Load a CCM consolidated edition JSON into provenance models."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            required=True,
            help="Path to consolidated edition JSON file.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source_path = Path(options["source"]).expanduser().resolve()
        if not source_path.exists():
            raise CommandError(f"Source file not found: {source_path}")

        try:
            data = json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON: {exc}") from exc

        code_str = data.get("code")
        edition_str = data.get("edition")
        if not code_str or not edition_str:
            raise CommandError("JSON must have 'code' and 'edition' top-level fields.")

        with transaction.atomic():
            code, edition = self._load_edition(data)
            reg_lookup = self._load_regulations(edition, data.get("regulations", []))
            clause_lookup = self._load_clauses(reg_lookup, data.get("regulations", []))
            prov_lookup = self._load_provisions(edition, data.get("provisions", []))
            version_lookup = self._load_versions(
                prov_lookup, clause_lookup, data.get("provisions", [])
            )
            table_count = self._load_tables(version_lookup, data.get("provisions", []))
            self._resolve_transition_provisions(version_lookup, prov_lookup, data.get("provisions", []))
            self._update_version_counts(prov_lookup)

        logger.info(
            "Loaded %s %s: %d regulations, %d clauses, %d provisions, %d versions, %d tables",
            code_str,
            edition_str,
            len(reg_lookup),
            len(clause_lookup),
            len(prov_lookup),
            len(version_lookup),
            table_count,
        )

    def _load_edition(self, data: dict[str, Any]) -> tuple[Code, CodeEdition]:
        code, _ = Code.objects.update_or_create(
            code=data["code"],
            defaults={
                "display_name": data.get("display_name", ""),
                "is_national": data.get("is_national", False),
            },
        )
        edition, _ = CodeEdition.objects.update_or_create(
            system=code,
            edition_id=data["edition"],
            defaults={
                "year": int(data.get("year", data["edition"])),
                "effective_date": _require_date(data.get("effective_date"), "effective_date"),
                "ineffective_date": _parse_date(data.get("ineffective_date")),
                "amendment_chain_complete": data.get("amendment_chain_complete", False),
                "map_codes": data.get("map_codes", []),
            },
        )

        # Clear existing provenance data for idempotency
        edition.provisions.all().delete()
        edition.regulations.all().delete()

        return code, edition

    def _load_regulations(
        self, edition: CodeEdition, regulations: list[dict[str, Any]]
    ) -> dict[str, Regulation]:
        reg_lookup: dict[str, Regulation] = {}

        for reg_data in regulations:
            reg_id = reg_data["reg_id"]
            reg = Regulation.objects.create(
                reg_id=reg_id,
                edition=edition,
                role=reg_data.get("role", Regulation.Role.AMENDMENT),
                filed_date=_parse_date(reg_data.get("filed_date")),
                effective_date=_require_date(reg_data.get("effective_date"), f"{reg_id}.effective_date"),
                source_pdf=reg_data.get("source_pdf", ""),
                source_pages=reg_data.get("source_pages"),
            )
            reg_lookup[reg_id] = reg

        # Second pass: set amends FK
        for reg_data in regulations:
            amends_id = reg_data.get("amends")
            if amends_id and amends_id in reg_lookup:
                reg = reg_lookup[reg_data["reg_id"]]
                reg.amends = reg_lookup[amends_id]
                reg.save(update_fields=["amends"])

        return reg_lookup

    def _load_clauses(
        self,
        reg_lookup: dict[str, Regulation],
        regulations: list[dict[str, Any]],
    ) -> dict[tuple[str, str], RegulationClause]:
        clause_lookup: dict[tuple[str, str], RegulationClause] = {}
        clauses_to_create: list[RegulationClause] = []

        for reg_data in regulations:
            reg_id = reg_data["reg_id"]
            regulation = reg_lookup[reg_id]
            for cl_data in reg_data.get("clauses", []):
                clause_id = cl_data["clause_id"]
                clause = RegulationClause(
                    regulation=regulation,
                    clause_id=clause_id,
                    parent_clause=cl_data.get("parent_clause", ""),
                    action=cl_data["action"],
                    target_level=cl_data.get("target_level", ""),
                    target_id=cl_data.get("target_id", ""),
                    clause_text=cl_data.get("clause_text", ""),
                    strike_text=cl_data.get("strike_text"),
                    sub_text=cl_data.get("sub_text"),
                    page=cl_data.get("page"),
                    bbox=cl_data.get("bbox"),
                    overlay=cl_data.get("overlay"),
                )
                clauses_to_create.append(clause)
                clause_lookup[(reg_id, clause_id)] = clause

        if clauses_to_create:
            RegulationClause.objects.bulk_create(clauses_to_create)

        return clause_lookup

    def _load_provisions(
        self,
        edition: CodeEdition,
        provisions: list[dict[str, Any]],
    ) -> dict[tuple[str, str], CodeEditionProvision]:
        prov_lookup: dict[tuple[str, str], CodeEditionProvision] = {}
        provs_to_create: list[CodeEditionProvision] = []

        # First pass: create without parent/appendix_of FKs
        for prov_data in provisions:
            provision_id = prov_data["provision_id"]
            division = prov_data.get("division", "")
            prov = CodeEditionProvision(
                edition=edition,
                provision_id=provision_id,
                level=prov_data["level"],
                division=division,
            )
            provs_to_create.append(prov)
            prov_lookup[(provision_id, division)] = prov

        if provs_to_create:
            CodeEditionProvision.objects.bulk_create(provs_to_create)

        # Second pass: set parent and appendix_of FKs
        provs_to_update: list[CodeEditionProvision] = []
        for prov_data in provisions:
            provision_id = prov_data["provision_id"]
            division = prov_data.get("division", "")
            prov = prov_lookup[(provision_id, division)]

            changed = False
            parent_id = prov_data.get("parent_id")
            if parent_id:
                parent = prov_lookup.get((parent_id, division))
                if parent:
                    prov.parent = parent
                    changed = True

            appendix_of_id = prov_data.get("appendix_of_id")
            if appendix_of_id:
                # Appendix provisions link to body provisions which may be in
                # a different division or no division
                appendix_target = prov_lookup.get((appendix_of_id, division))
                if not appendix_target:
                    appendix_target = prov_lookup.get((appendix_of_id, ""))
                if not appendix_target:
                    # Search all divisions
                    for key, candidate in prov_lookup.items():
                        if key[0] == appendix_of_id:
                            appendix_target = candidate
                            break
                if appendix_target:
                    prov.appendix_of = appendix_target
                    changed = True

            if changed:
                provs_to_update.append(prov)

        if provs_to_update:
            CodeEditionProvision.objects.bulk_update(
                provs_to_update, ["parent", "appendix_of"], batch_size=500
            )

        return prov_lookup

    def _load_versions(
        self,
        prov_lookup: dict[tuple[str, str], CodeEditionProvision],
        clause_lookup: dict[tuple[str, str], RegulationClause],
        provisions: list[dict[str, Any]],
    ) -> dict[tuple[str, str, int], CodeEditionProvisionVersion]:
        version_lookup: dict[tuple[str, str, int], CodeEditionProvisionVersion] = {}
        versions_to_create: list[CodeEditionProvisionVersion] = []

        for prov_data in provisions:
            provision_id = prov_data["provision_id"]
            division = prov_data.get("division", "")
            provision = prov_lookup[(provision_id, division)]

            for ver_data in prov_data.get("versions", []):
                version_num = ver_data["version"]

                # Resolve clause FK
                clause = None
                reg_id = ver_data.get("regulation")
                clause_id = ver_data.get("clause_id")
                if reg_id and clause_id:
                    clause = clause_lookup.get((reg_id, clause_id))

                version = CodeEditionProvisionVersion(
                    provision=provision,
                    version=version_num,
                    clause=clause,
                    action=ver_data.get("action", CodeEditionProvisionVersion.Action.ORIGINAL),
                    effective_date=_require_date(
                        ver_data.get("effective_date"),
                        f"{provision_id} v{version_num}.effective_date",
                    ),
                    ineffective_date=_parse_date(ver_data.get("ineffective_date")),
                    title=ver_data.get("title", ""),
                    html=ver_data.get("html", ""),
                    page_images=ver_data.get("page_images"),
                    keyword_counts=ver_data.get("keyword_counts"),
                )
                versions_to_create.append(version)
                version_lookup[(provision_id, division, version_num)] = version

        if versions_to_create:
            CodeEditionProvisionVersion.objects.bulk_create(versions_to_create)

        return version_lookup

    def _load_tables(
        self,
        version_lookup: dict[tuple[str, str, int], CodeEditionProvisionVersion],
        provisions: list[dict[str, Any]],
    ) -> int:
        tables_to_create: list[ProvisionVersionTable] = []

        for prov_data in provisions:
            provision_id = prov_data["provision_id"]
            division = prov_data.get("division", "")
            for ver_data in prov_data.get("versions", []):
                version_num = ver_data["version"]
                version = version_lookup.get((provision_id, division, version_num))
                if not version:
                    continue
                for tbl_data in ver_data.get("tables", []):
                    tables_to_create.append(ProvisionVersionTable(
                        version=version,
                        table_id=tbl_data["table_id"],
                        caption=tbl_data.get("caption", ""),
                        images=tbl_data.get("images", []),
                        notes=tbl_data.get("notes", ""),
                        order=tbl_data.get("order", 0),
                    ))

        if tables_to_create:
            ProvisionVersionTable.objects.bulk_create(tables_to_create)

        return len(tables_to_create)

    def _resolve_transition_provisions(
        self,
        version_lookup: dict[tuple[str, str, int], CodeEditionProvisionVersion],
        prov_lookup: dict[tuple[str, str], CodeEditionProvision],
        provisions: list[dict[str, Any]],
    ) -> None:
        versions_to_update: list[CodeEditionProvisionVersion] = []

        for prov_data in provisions:
            provision_id = prov_data["provision_id"]
            division = prov_data.get("division", "")
            for ver_data in prov_data.get("versions", []):
                tp_id = ver_data.get("transition_provision_id")
                if not tp_id:
                    continue
                version_num = ver_data["version"]
                version = version_lookup.get((provision_id, division, version_num))
                if not version:
                    continue

                # Find the current (latest) version of the transition provision
                tp_prov = prov_lookup.get((tp_id, division))
                if not tp_prov:
                    tp_prov = prov_lookup.get((tp_id, ""))
                if not tp_prov:
                    for key, candidate in prov_lookup.items():
                        if key[0] == tp_id:
                            tp_prov = candidate
                            break
                if not tp_prov:
                    logger.warning(
                        "Transition provision %s not found for %s v%d",
                        tp_id, provision_id, version_num,
                    )
                    continue

                # Find the latest version of the transition provision
                tp_version = None
                for key, ver in version_lookup.items():
                    if key[0] == tp_prov.provision_id and key[1] == (tp_prov.division or ""):
                        if tp_version is None or key[2] > tp_version.version:
                            tp_version = ver

                if tp_version:
                    version.transition_provision = tp_version
                    versions_to_update.append(version)

        if versions_to_update:
            CodeEditionProvisionVersion.objects.bulk_update(
                versions_to_update, ["transition_provision"], batch_size=500
            )

    def _update_version_counts(
        self,
        prov_lookup: dict[tuple[str, str], CodeEditionProvision],
    ) -> None:
        # Count versions per provision from DB
        from django.db.models import Count

        counts = (
            CodeEditionProvisionVersion.objects
            .filter(provision__in=prov_lookup.values())
            .values("provision_id")
            .annotate(cnt=Count("id"))
        )
        count_map: dict[int, int] = {row["provision_id"]: row["cnt"] for row in counts}

        provs_to_update: list[CodeEditionProvision] = []
        for prov in prov_lookup.values():
            new_count = count_map.get(prov.pk, 0)
            if prov.version_count != new_count:
                prov.version_count = new_count
                provs_to_update.append(prov)

        if provs_to_update:
            CodeEditionProvision.objects.bulk_update(
                provs_to_update, ["version_count"], batch_size=500
            )
