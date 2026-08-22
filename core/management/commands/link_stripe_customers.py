"""Join a Stripe customer to the organization that pays through it.

Every automatic link happens at the moment of purchase — the success page, the
``customer.subscription.created`` webhook, and the one-off migration
``core.0058``.  All three sit on the happy path, so nothing repairs a customer
that missed them, and an unrepaired customer reads as free tier while its
subscription is live and paid.  This command is the repair.

It is also what makes an **invoiced** sale possible.  A firm that pays on a
purchase order gets its customer and subscription made in the Stripe dashboard
with ``collection_method="send_invoice"``, so that customer never passed
through our checkout and carries no metadata naming an organization.  Nothing
else can supply it, so ``--organization`` does:

    python manage.py link_stripe_customers \\
        --customer cus_ABC --organization 7 --apply

Three decisions:

* **It reports before it writes, and ``--apply`` is required.**  A link grants
  every edition to everybody in the organization, which is the same weight as
  the destructive commands in this repository.
* **``--organization`` writes the answer back to Stripe.**  The metadata is
  what lets the whole dj-stripe mirror be rebuilt from Stripe alone, and a
  link that exists only in our database would be lost by exactly the recovery
  the card describes.
* **A customer that names nothing is left alone and named in the report.**  A
  guessed link — matching an email, say — could hand a stranger every edition.
  A missing link locks somebody out, which a person notices and fixes; a wrong
  one nobody notices at all.
"""

from __future__ import annotations

from typing import Any

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from djstripe.models import Customer

from core.models import Organization

#: The metadata key checkout writes, and the one this reads back.
ORGANIZATION_KEY = "django_organization_id"


class Command(BaseCommand):
    help = "Link dj-stripe customers to the organizations that pay through them."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--customer",
            help="One Stripe customer id. Without it, every unlinked customer is read.",
        )
        parser.add_argument(
            "--organization",
            type=int,
            help=(
                "Link --customer to this organization id, and write the answer "
                "back to Stripe. For a customer made outside checkout."
            ),
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the links. Without it, nothing changes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        customer_id: str | None = options["customer"]
        organization_id: int | None = options["organization"]
        apply_changes: bool = options["apply"]

        if organization_id is not None and not customer_id:
            raise CommandError("--organization names one customer, so --customer is required.")

        stripe.api_key = (
            settings.STRIPE_TEST_SECRET_KEY
            if settings.DEBUG
            else settings.STRIPE_LIVE_SECRET_KEY
        )

        if organization_id is not None:
            self._link_by_hand(customer_id or "", organization_id, apply_changes)
            return

        self._link_from_metadata(customer_id, apply_changes)

    # -- the two modes ----------------------------------------------------

    def _link_by_hand(self, customer_id: str, organization_id: int, apply_changes: bool) -> None:
        """Name the organization ourselves, because Stripe does not know it."""
        organization = Organization.objects.filter(id=organization_id).first()
        if organization is None:
            raise CommandError(f"No organization with id {organization_id}.")

        customer = Customer.objects.filter(id=customer_id).first()
        if customer is None:
            raise CommandError(
                f"{customer_id} is not in the local mirror. "
                "Run djstripe_sync_models Customer first, or check the id."
            )

        if customer.subscriber is not None:
            current = customer.subscriber
            self.stdout.write(
                f"{customer_id} already names {current} (id {current.pk}). Nothing to do."
            )
            return

        self.stdout.write(f"{customer_id} -> {organization.name} (id {organization.pk})")
        if not apply_changes:
            self.stdout.write(self.style.WARNING("Nothing written. Add --apply."))
            return

        customer.subscriber = organization
        customer.save(update_fields=["subscriber"])
        # Written back so the link survives a rebuilt mirror.  Stripe is the
        # record; our table is the copy.
        stripe.Customer.modify(
            customer_id, metadata={ORGANIZATION_KEY: str(organization.pk)}
        )
        self.stdout.write(self.style.SUCCESS("Linked, and the id is now on the Stripe customer."))

    def _link_from_metadata(self, customer_id: str | None, apply_changes: bool) -> None:
        """Read the answer Stripe already holds, for one customer or for all."""
        rows = Customer.objects.filter(subscriber__isnull=True)
        if customer_id:
            rows = rows.filter(id=customer_id)

        linked = 0
        unresolved: list[str] = []

        for customer in rows:
            named = (customer.stripe_data or {}).get("metadata", {}).get(ORGANIZATION_KEY)
            if not named:
                unresolved.append(f"{customer.id}: names no organization")
                continue

            organization = Organization.objects.filter(id=named).first()
            if organization is None:
                unresolved.append(f"{customer.id}: names organization {named}, which is gone")
                continue

            self.stdout.write(f"{customer.id} -> {organization.name} (id {organization.pk})")
            linked += 1
            if apply_changes:
                customer.subscriber = organization
                customer.save(update_fields=["subscriber"])

        for line in unresolved:
            self.stdout.write(self.style.WARNING(line))

        if unresolved:
            self.stdout.write(
                "A customer that names nothing is left alone on purpose. "
                "Use --customer with --organization to say who pays."
            )

        if not linked:
            self.stdout.write("Nothing to link.")
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Linked {linked}."))
        else:
            self.stdout.write(self.style.WARNING(f"{linked} would be linked. Add --apply."))
