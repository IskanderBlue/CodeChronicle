"""The repair for a Stripe customer that never reached its organization.

Every automatic link happens at purchase.  These tests hold the two rules that
make a later repair safe: it writes nothing without ``--apply``, and it never
guesses which organization pays.
"""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command
from djstripe.models import Customer

from core.models import Organization


def unlinked_customer(customer_id: str, metadata: dict | None = None) -> Customer:
    data: dict = {"id": customer_id, "object": "customer"}
    if metadata is not None:
        data["metadata"] = metadata
    return Customer.objects.create(id=customer_id, livemode=False, stripe_data=data)


def run(*args: str) -> str:
    out = StringIO()
    call_command("link_stripe_customers", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestReadingWhatStripeHolds:
    def test_nothing_is_written_without_apply(self):
        firm = Organization.objects.create(name="Firm", email="firm@example.com")
        customer = unlinked_customer(
            "cus_dry", {"django_organization_id": str(firm.pk)}
        )
        output = run()
        assert "would be linked" in output
        customer.refresh_from_db()
        assert customer.subscriber is None

    def test_apply_links_it(self):
        firm = Organization.objects.create(name="Firm", email="firm@example.com")
        customer = unlinked_customer(
            "cus_wet", {"django_organization_id": str(firm.pk)}
        )
        run("--apply")
        customer.refresh_from_db()
        assert customer.subscriber == firm

    def test_a_customer_naming_nothing_is_left_alone(self):
        """A guessed link could hand a stranger every edition.  A missing one
        locks somebody out, which a person notices."""
        customer = unlinked_customer("cus_bare")
        output = run("--apply")
        assert "names no organization" in output
        customer.refresh_from_db()
        assert customer.subscriber is None

    def test_a_customer_naming_a_gone_organization_is_reported(self):
        customer = unlinked_customer("cus_ghost", {"django_organization_id": "9999"})
        output = run("--apply")
        assert "which is gone" in output
        customer.refresh_from_db()
        assert customer.subscriber is None

    def test_an_already_linked_customer_is_not_read_again(self):
        firm = Organization.objects.create(name="Firm", email="firm@example.com")
        Customer.objects.create(
            id="cus_done",
            livemode=False,
            subscriber=firm,
            stripe_data={"id": "cus_done", "object": "customer"},
        )
        assert "Nothing to link" in run()


@pytest.mark.django_db
class TestNamingTheOrganizationByHand:
    """The invoiced sale: a customer made in the dashboard names nobody."""

    def test_it_links_and_writes_the_id_back_to_stripe(self):
        firm = Organization.objects.create(name="Firm", email="firm@example.com")
        customer = unlinked_customer("cus_invoice")

        with patch("stripe.Customer.modify") as modify:
            run("--customer", "cus_invoice", "--organization", str(firm.pk), "--apply")

        customer.refresh_from_db()
        assert customer.subscriber == firm
        # Written back, or a rebuilt mirror would lose the link.
        modify.assert_called_once_with(
            "cus_invoice", metadata={"django_organization_id": str(firm.pk)}
        )

    def test_nothing_is_written_without_apply(self):
        firm = Organization.objects.create(name="Firm", email="firm@example.com")
        customer = unlinked_customer("cus_invoice")

        with patch("stripe.Customer.modify") as modify:
            output = run("--customer", "cus_invoice", "--organization", str(firm.pk))

        assert "Add --apply" in output
        customer.refresh_from_db()
        assert customer.subscriber is None
        modify.assert_not_called()

    def test_it_will_not_move_a_link_that_exists(self):
        first = Organization.objects.create(name="First", email="a@example.com")
        second = Organization.objects.create(name="Second", email="b@example.com")
        customer = Customer.objects.create(
            id="cus_taken",
            livemode=False,
            subscriber=first,
            stripe_data={"id": "cus_taken", "object": "customer"},
        )
        output = run("--customer", "cus_taken", "--organization", str(second.pk), "--apply")
        assert "already names" in output
        customer.refresh_from_db()
        assert customer.subscriber == first

    def test_an_unknown_organization_stops_the_command(self):
        unlinked_customer("cus_x")
        with pytest.raises(CommandError):
            run("--customer", "cus_x", "--organization", "9999", "--apply")

    def test_an_unknown_customer_stops_the_command(self):
        firm = Organization.objects.create(name="Firm", email="firm@example.com")
        with pytest.raises(CommandError):
            run("--customer", "cus_missing", "--organization", str(firm.pk), "--apply")

    def test_the_organization_flag_needs_a_customer(self):
        with pytest.raises(CommandError):
            run("--organization", "1", "--apply")
