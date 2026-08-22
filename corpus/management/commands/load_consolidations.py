"""Load the e-Laws consolidation date-range map into ``Consolidation``.

Consumes the JSON emitted by ``scripts/build_elaws_consolidations.py`` (one row
per real consolidation period: code, edition, version, url, effective_from,
effective_to) and upserts it per edition. Idempotent: each edition present in the
file is replaced wholesale, so re-running after a regenerate is safe.

These rows are edition-scoped (FK to CodeEdition, CASCADE), so reloading an
edition wipes its consolidation rows — re-run this command after a
``load_edition`` of an edition whose consolidations you want restored.

    python manage.py load_consolidations [--source data/elaws_consolidations.json]
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import CodeEdition, Consolidation


class Command(BaseCommand):
    help = "Load e-Laws consolidation date ranges from the build script's JSON."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--source",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "elaws_consolidations.json"),
            help="Path to the consolidations JSON (default: data/elaws_consolidations.json).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source = Path(options["source"])
        if not source.is_file():
            raise CommandError(f"Consolidations file not found: {source}")

        rows: list[dict[str, Any]] = json.loads(source.read_text(encoding="utf-8"))

        # Resolve each (code, edition) to a CodeEdition once. Group rows by it so
        # we can replace an edition's set atomically.
        by_edition: dict[int, list[dict[str, Any]]] = {}
        skipped_editions: set[str] = set()
        for row in rows:
            key = f"{row['code']} {row['edition']}"
            edition = CodeEdition.objects.filter(
                code__code=row["code"], edition_id=row["edition"]
            ).first()
            if edition is None:
                skipped_editions.add(key)
                continue
            by_edition.setdefault(edition.pk, []).append(row)

        created = 0
        with transaction.atomic():
            for edition_pk, edition_rows in by_edition.items():
                Consolidation.objects.filter(edition_id=edition_pk).delete()
                Consolidation.objects.bulk_create(
                    [
                        Consolidation(
                            edition_id=edition_pk,
                            version=r["version"],
                            url=r["url"],
                            # Both bounds are always present: a closed period is
                            # [from, to]; the live consolidation is a zero-range
                            # point [from, from] (no NULL tail — decision 4).
                            effective_from=date.fromisoformat(r["effective_from"]),
                            effective_to=date.fromisoformat(r["effective_to"]),
                        )
                        for r in edition_rows
                    ]
                )
                created += len(edition_rows)

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {created} consolidation rows across {len(by_edition)} edition(s)."
            )
        )
        for key in sorted(skipped_editions):
            self.stdout.write(
                self.style.WARNING(f"  skipped {key}: edition not in DB (load it first)")
            )
