"""
Management command to verify data integrity after migrations and map loads.

Usage: python manage.py check_data_integrity
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from core.models import CodeEdition, CodeMap, CodeMapNode


class Command(BaseCommand):
    help = "Check data integrity of code maps and nodes in the database."

    def handle(self, *args, **options):
        total_maps = CodeMap.objects.count()
        total_nodes = CodeMapNode.objects.count()
        self.stdout.write(f"CodeMaps: {total_maps}")
        self.stdout.write(f"CodeMapNodes: {total_nodes}")

        if total_nodes == 0:
            self.stdout.write(self.style.WARNING("No nodes found — nothing to check."))
            return

        # PDF-sourced nodes missing page bounds
        pdf_nodes = CodeMapNode.objects.filter(page__isnull=False)
        pdf_count = pdf_nodes.count()
        missing_top = pdf_nodes.filter(initial_page_top__isnull=True).count()
        missing_bottom = pdf_nodes.filter(final_page_bottom__isnull=True).count()
        self.stdout.write(f"\nPDF-sourced nodes (page IS NOT NULL): {pdf_count}")
        if missing_top:
            self.stdout.write(
                self.style.WARNING(f"  Missing initial_page_top: {missing_top}")
            )
        if missing_bottom:
            self.stdout.write(
                self.style.WARNING(f"  Missing final_page_bottom: {missing_bottom}")
            )
        if not missing_top and not missing_bottom:
            self.stdout.write(self.style.SUCCESS("  All page bounds populated."))

        # e-Laws nodes missing html
        elaws_nodes = CodeMapNode.objects.filter(page__isnull=True)
        elaws_count = elaws_nodes.count()
        missing_html = elaws_nodes.filter(Q(html__isnull=True) | Q(html="")).count()
        self.stdout.write(f"\ne-Laws nodes (page IS NULL): {elaws_count}")
        if missing_html:
            self.stdout.write(
                self.style.WARNING(f"  Missing html: {missing_html}")
            )
        else:
            self.stdout.write(self.style.SUCCESS("  All html populated."))

        # CodeEditions with empty map_codes
        empty_editions = CodeEdition.objects.filter(
            Q(map_codes__isnull=True) | Q(map_codes=[])
        )
        empty_count = empty_editions.count()
        self.stdout.write(f"\nCodeEditions with empty map_codes: {empty_count}")
        if empty_count:
            for ed in empty_editions:
                self.stdout.write(
                    self.style.WARNING(f"  {ed.code.code}_{ed.edition_id}")
                )
        else:
            self.stdout.write(self.style.SUCCESS("  All editions have map_codes."))

        # Summary
        issues = missing_top + missing_bottom + missing_html + empty_count
        self.stdout.write("")
        if issues:
            self.stdout.write(
                self.style.WARNING(f"Total issues found: {issues}")
            )
        else:
            self.stdout.write(self.style.SUCCESS("All checks passed."))
