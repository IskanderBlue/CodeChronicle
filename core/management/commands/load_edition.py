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
    CodeEditionProvisionVersionClause,
    CorpusCurrency,
    ProvinceCode,
    ProvisionMapping,
    ProvisionVersionTable,
    Regulation,
    RegulationAsset,
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

    #: Default location of CCM's consolidated edition JSON output, mirroring
    #: load_maps/sync_images.  A bare ``load_edition`` loads DEFAULT_FILE from
    #: here.
    DEFAULT_SOURCE_DIR = Path("..") / "CodeChronicleMapping" / "data" / "outputs"
    #: The only edition currently in scope to load (OBC 2012).
    DEFAULT_FILE = "OBC_2012.json"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            default=str(self.DEFAULT_SOURCE_DIR),
            help=(
                "Path to a consolidated edition JSON file, or a directory "
                "containing one (in which case --file is appended).  "
                f"Defaults to {self.DEFAULT_SOURCE_DIR}."
            ),
        )
        parser.add_argument(
            "--file",
            default=self.DEFAULT_FILE,
            help=(
                "Edition JSON filename to load when --source is a directory.  "
                f"Defaults to {self.DEFAULT_FILE}."
            ),
        )
        parser.add_argument(
            "--allow-incomplete-chain",
            action="store_true",
            help=(
                "Permit ingest of an edition whose JSON has "
                "amendment_chain_complete=false.  Off by default — the "
                "contract is explicit that incomplete chains are out-of-spec."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source_path = Path(options["source"]).expanduser().resolve()
        # When --source names a directory (the default), append --file so a
        # bare `load_edition` resolves to DEFAULT_SOURCE_DIR / DEFAULT_FILE.
        if source_path.is_dir():
            source_path = source_path / options["file"]
        if not source_path.exists():
            raise CommandError(f"Source file not found: {source_path}")

        # Sanity guard: snapshots/ holds CCM's raw e-Laws scrapes whose
        # shape matches the consolidated file but whose content is
        # intermediate.  Ingesting them would silently double-load.
        if "snapshots" in source_path.parts:
            raise CommandError(
                f"Refusing to ingest a path under snapshots/: {source_path}.  "
                f"snapshots/ contains CCM's raw e-Laws intermediate files; "
                f"consolidated edition JSON lives at the data/outputs/ root."
            )

        try:
            data = json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON: {exc}") from exc

        code_str = data.get("code")
        edition_str = data.get("edition")
        if not code_str or not edition_str:
            raise CommandError("JSON must have 'code' and 'edition' top-level fields.")

        if "edition_mappings" in data:
            raise CommandError(
                "JSON contains the deprecated 'edition_mappings' key. "
                "Re-run CCM to emit 'provision_mappings' instead "
                "(see CCM impl-19 / CC provision-mapping-rename)."
            )

        # Sanity guard: contract §"What CodeChronicle Does NOT Expect" —
        # "Editions with incomplete amendment chains" are out-of-spec.
        if not data.get("amendment_chain_complete", False) and not options["allow_incomplete_chain"]:
            raise CommandError(
                "Edition JSON has amendment_chain_complete=False.  "
                "Pass --allow-incomplete-chain to ingest anyway."
            )

        with transaction.atomic():
            code, edition = self._load_edition(data)
            reg_lookup = self._load_regulations(edition, data.get("regulations", []))
            clause_lookup = self._load_clauses(reg_lookup, data.get("regulations", []))
            asset_count = self._load_assets(reg_lookup, data.get("regulations", []))
            prov_lookup = self._load_provisions(edition, data.get("provisions", []))
            version_lookup = self._load_versions(prov_lookup, data.get("provisions", []))
            clause_link_count = self._load_version_clause_links(
                version_lookup, clause_lookup, reg_lookup, data.get("provisions", []),
            )
            table_count = self._load_tables(version_lookup, data.get("provisions", []))
            self._resolve_transition_provisions(
                version_lookup, prov_lookup, data.get("provisions", []),
            )
            self._update_version_counts(prov_lookup)
            mapping_count = self._load_provision_mappings(
                code, version_lookup, data.get("provision_mappings", []),
            )

        # Refresh the masthead provenance stamp once per load — outside the
        # atomic block, so it snapshots committed data.  (Computing the
        # corpus span / consolidation-currency date per request would be
        # wasteful; the context processor just reads this singleton.)
        currency = CorpusCurrency.refresh()

        logger.info(
            "Loaded %s %s: %d regulations, %d clauses, %d assets, %d provisions, "
            "%d versions, %d version-clause links, %d tables, %d mappings; "
            "corpus current to %s",
            code_str,
            edition_str,
            len(reg_lookup),
            len(clause_lookup),
            asset_count,
            len(prov_lookup),
            len(version_lookup),
            clause_link_count,
            table_count,
            mapping_count,
            currency.data_current_to,
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
            code=code,
            edition_id=data["edition"],
            defaults={
                "year": int(data.get("year", data["edition"])),
                "effective_date": _require_date(data.get("effective_date"), "effective_date"),
                "ineffective_date": _parse_date(data.get("ineffective_date")),
                "amendment_chain_complete": data.get("amendment_chain_complete", False),
                "map_codes": data.get("map_codes", []),
            },
        )

        province = data.get("province")
        if province:
            ProvinceCode.objects.update_or_create(
                province=province,
                defaults={"code": code},
            )

        # Clear existing provenance data for idempotency.  CASCADE on
        # ProvisionMapping.{old,new}_provision cleans up dangling mappings
        # (including cross-edition ones touching this edition) automatically.
        # CASCADE on RegulationAsset.regulation cleans up assets too.
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
                effective_date=_require_date(
                    reg_data.get("effective_date"), f"{reg_id}.effective_date",
                ),
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
        """Build RegulationClause rows from each regulation's clauses[].

        Meta-amendment back-pointer stubs (clauses carrying only
        ``clause_id`` + ``amended_by``, no ``action``/``target_*``) and
        full clauses for the same ``(regulation, clause_id)`` are merged
        into one row to satisfy the unique constraint.  The full clause
        wins on the populated fields; ``amended_by`` from the stub is
        preserved when the full clause lacks it.
        """
        merged: dict[tuple[str, str], dict[str, Any]] = {}

        for reg_data in regulations:
            reg_id = reg_data["reg_id"]
            for cl_data in reg_data.get("clauses", []):
                clause_id = cl_data["clause_id"]
                key = (reg_id, clause_id)
                existing = merged.get(key)
                if existing is None:
                    merged[key] = dict(cl_data)
                    continue
                # Merge: prefer non-empty fields from whichever entry has them.
                for field, value in cl_data.items():
                    cur = existing.get(field)
                    if cur in (None, "", []) and value not in (None, "", []):
                        existing[field] = value
                # amended_by is a list — concatenate if both have it.
                stub_ab = cl_data.get("amended_by")
                full_ab = existing.get("amended_by")
                if stub_ab and full_ab and stub_ab is not full_ab:
                    seen = {json.dumps(e, sort_keys=True) for e in full_ab}
                    for entry in stub_ab:
                        if json.dumps(entry, sort_keys=True) not in seen:
                            full_ab.append(entry)
                    existing["amended_by"] = full_ab

        clause_lookup: dict[tuple[str, str], RegulationClause] = {}
        clauses_to_create: list[RegulationClause] = []
        for (reg_id, clause_id), cl_data in merged.items():
            clause = RegulationClause(
                regulation=reg_lookup[reg_id],
                clause_id=clause_id,
                parent_clause=cl_data.get("parent_clause", ""),
                action=cl_data.get("action", ""),
                target_level=cl_data.get("target_level", ""),
                target_id=cl_data.get("target_id", ""),
                target_division=cl_data.get("target_division", ""),
                target_reg=cl_data.get("target_reg", ""),
                clause_text=cl_data.get("clause_text", ""),
                strike_text=cl_data.get("strike_text"),
                sub_text=cl_data.get("sub_text"),
                amended_by=cl_data.get("amended_by"),
                page=cl_data.get("page"),
                bbox=cl_data.get("bbox"),
                overlay=cl_data.get("overlay"),
            )
            clauses_to_create.append(clause)
            clause_lookup[(reg_id, clause_id)] = clause

        if clauses_to_create:
            RegulationClause.objects.bulk_create(clauses_to_create)

        return clause_lookup

    def _load_assets(
        self,
        reg_lookup: dict[str, Regulation],
        regulations: list[dict[str, Any]],
    ) -> int:
        """Persist ``regulations[].assets[]`` manifest entries.

        The bytes themselves are mirrored by ``sync_images`` — this step
        only writes the manifest so the FK ``regulation.assets`` is
        populated for ingest-time verification and for later
        serving/auditing.
        """
        assets_to_create: list[RegulationAsset] = []
        for reg_data in regulations:
            reg_id = reg_data["reg_id"]
            regulation = reg_lookup.get(reg_id)
            if regulation is None:
                continue
            for asset_data in reg_data.get("assets", []) or []:
                path = asset_data.get("path")
                if not path:
                    continue
                assets_to_create.append(RegulationAsset(
                    regulation=regulation,
                    path=path,
                    original_url=asset_data.get("original_url", ""),
                    sha256=asset_data.get("sha256", ""),
                    byte_size=asset_data.get("bytes"),
                    content_type=asset_data.get("content_type", ""),
                ))

        if assets_to_create:
            RegulationAsset.objects.bulk_create(assets_to_create)

        return len(assets_to_create)

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
                version = CodeEditionProvisionVersion(
                    provision=provision,
                    version=version_num,
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

    def _load_version_clause_links(
        self,
        version_lookup: dict[tuple[str, str, int], CodeEditionProvisionVersion],
        clause_lookup: dict[tuple[str, str], RegulationClause],
        reg_lookup: dict[str, Regulation],
        provisions: list[dict[str, Any]],
    ) -> int:
        """Populate ``CodeEditionProvisionVersionClause`` from
        ``versions[].clauses[]``.

        Contract: clauses are listed in application order, which is
        ``(regulation.filed_date, clause_id)``.  CCM commits to this
        ordering on the producer side, but we re-sort defensively so
        ``apply_order`` is a stable projection of the contract rule
        rather than a snapshot of however the producer happened to emit.
        """
        through_rows: list[CodeEditionProvisionVersionClause] = []

        for prov_data in provisions:
            provision_id = prov_data["provision_id"]
            division = prov_data.get("division", "")
            for ver_data in prov_data.get("versions", []):
                version_num = ver_data["version"]
                version = version_lookup.get((provision_id, division, version_num))
                if version is None:
                    continue

                refs: list[tuple[str, str]] = []
                for cl_ref in ver_data.get("clauses", []) or []:
                    reg_id = cl_ref.get("regulation")
                    clause_id = cl_ref.get("clause_id")
                    if not reg_id or not clause_id:
                        continue
                    refs.append((reg_id, clause_id))

                def _sort_key(ref: tuple[str, str]) -> tuple[date, str]:
                    reg_id, clause_id = ref
                    reg = reg_lookup.get(reg_id)
                    filed = reg.filed_date if reg and reg.filed_date else date.min
                    return (filed, clause_id)

                refs.sort(key=_sort_key)

                for apply_order, ref in enumerate(refs):
                    clause = clause_lookup.get(ref)
                    if clause is None:
                        logger.warning(
                            "Version %s/%s v%d references missing clause %s/%s",
                            provision_id, division, version_num, ref[0], ref[1],
                        )
                        continue
                    through_rows.append(CodeEditionProvisionVersionClause(
                        version=version,
                        clause=clause,
                        apply_order=apply_order,
                    ))

        if through_rows:
            CodeEditionProvisionVersionClause.objects.bulk_create(through_rows)

        return len(through_rows)

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
                        html=tbl_data.get("html", ""),
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
        """Resolve ``transition_provision_ref`` records to FK pins.

        Contract shape (CCM impl-57):
        ``{"provision_id": str, "division": str, "version": int}``.
        Hard error on the legacy ``transition_provision_id`` string.
        """
        del prov_lookup  # impl-57: no longer needed; the ref carries division
        versions_to_update: list[CodeEditionProvisionVersion] = []

        for prov_data in provisions:
            provision_id = prov_data["provision_id"]
            division = prov_data.get("division", "")
            for ver_data in prov_data.get("versions", []):
                if "transition_provision_id" in ver_data:
                    raise CommandError(
                        "Edition JSON carries the legacy "
                        "'transition_provision_id' field.  Re-emit from "
                        "CCM under impl-57 (the field was renamed to "
                        "'transition_provision_ref' and reshaped to a "
                        "{provision_id, division, version} record)."
                    )
                ref = ver_data.get("transition_provision_ref")
                if ref is None:
                    continue
                version_num = ver_data["version"]
                version = version_lookup.get((provision_id, division, version_num))
                if version is None:
                    raise ValueError(
                        f"Linking version not found in version_lookup: "
                        f"{provision_id} (division={division!r}) v{version_num}."
                    )

                tp_pid = ref["provision_id"]
                tp_div = ref.get("division", "") or ""
                tp_ver = int(ref["version"])
                tp_version = version_lookup.get((tp_pid, tp_div, tp_ver))
                if tp_version is None:
                    raise ValueError(
                        f"transition_provision_ref does not resolve: "
                        f"(provision_id={tp_pid!r}, division={tp_div!r}, "
                        f"version={tp_ver}) is not present in the edition's "
                        f"provision-version set.  Linking version: "
                        f"{provision_id} (division={division!r}) v{version_num}.  "
                        f"Fix the producer (CCM impl-57)."
                    )

                version.transition_provision = tp_version
                versions_to_update.append(version)

        if versions_to_update:
            CodeEditionProvisionVersion.objects.bulk_update(
                versions_to_update, ["transition_provision"], batch_size=500
            )

    def _load_provision_mappings(
        self,
        code: Code,
        version_lookup: dict[tuple[str, str, int], CodeEditionProvisionVersion],
        provision_mappings: list[dict[str, Any]],
    ) -> int:
        mappings_to_create: list[ProvisionMapping] = []

        for mapping_data in provision_mappings:
            old_edition_id = mapping_data["old_edition"]
            new_edition_id = mapping_data["new_edition"]
            old_provision_id = mapping_data["old_provision_id"]
            new_provision_id = mapping_data["new_provision_id"]
            old_division = mapping_data.get("old_division", "")
            new_division = mapping_data.get("new_division", "")

            old_provision = CodeEditionProvision.objects.filter(
                edition__code=code,
                edition__edition_id=old_edition_id,
                provision_id=old_provision_id,
                division=old_division,
            ).first()
            new_provision = CodeEditionProvision.objects.filter(
                edition__code=code,
                edition__edition_id=new_edition_id,
                provision_id=new_provision_id,
                division=new_division,
            ).first()

            if not old_provision or not new_provision:
                logger.warning(
                    "Skipping mapping %s/%s -> %s/%s: provision not found",
                    old_edition_id, old_provision_id,
                    new_edition_id, new_provision_id,
                )
                continue

            introduced_by_version: CodeEditionProvisionVersion | None = None
            intro = mapping_data.get("introduced_by")
            if intro is not None:
                intro_provision_id = intro["provision_id"]
                intro_division = intro.get("division", "")
                intro_version_num = intro["version"]
                introduced_by_version = version_lookup.get(
                    (intro_provision_id, intro_division, intro_version_num)
                )
                if introduced_by_version is None:
                    logger.warning(
                        "Mapping %s -> %s: introduced_by version "
                        "%s/%s/v%d not found; storing without FK",
                        old_provision_id, new_provision_id,
                        intro_provision_id, intro_division, intro_version_num,
                    )

            mappings_to_create.append(ProvisionMapping(
                old_provision=old_provision,
                new_provision=new_provision,
                mapping_type=mapping_data.get("mapping_type", ""),
                introduced_by_version=introduced_by_version,
                notes=mapping_data.get("notes", ""),
            ))

        if mappings_to_create:
            ProvisionMapping.objects.bulk_create(
                mappings_to_create, ignore_conflicts=True
            )

        return len(mappings_to_create)

    def _update_version_counts(
        self,
        prov_lookup: dict[tuple[str, str], CodeEditionProvision],
    ) -> None:
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
