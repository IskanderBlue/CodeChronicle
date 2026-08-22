"""Seats: the gate, the seat count, the invitation, and who may press what.

Every test here holds one of the rules in ``tasks/complete/team-payments.md``.  The
two that matter most are the first two: a role that reads is a role that is
paid for, and the seat check binds where a person is added.
"""

import pytest
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from djstripe.models import Customer, Subscription

from accounts.access import user_is_unrestricted
from accounts.signals.stripe_handlers import handle_subscription_created
from accounts.teams import SeatError, accept_invite, invite_member, personal_organization
from core.models import Invite, Membership, Organization, User
from web.views.billing import MAX_SELF_SERVE_SEATS, _requested_seats


def make_organization(name: str = "Firm", *, seats: int = 0, status: str = "active"):
    """An organization, with a mirrored Stripe subscription when seats are bought.

    ``seats`` of 0 makes an organization with no subscription at all, which is
    what a firm looks like between signing up and paying.
    """
    organization = Organization.objects.create(name=name, email=f"{name}@example.com")
    if seats:
        customer = Customer.objects.create(
            id=f"cus_{name}",
            livemode=False,
            subscriber=organization,
            stripe_data={"id": f"cus_{name}", "object": "customer"},
        )
        Subscription.objects.create(
            id=f"sub_{name}",
            livemode=False,
            customer=customer,
            stripe_data={
                "id": f"sub_{name}",
                "object": "subscription",
                "status": status,
                "items": {"data": [{"quantity": seats}]},
            },
        )
    return organization


def join(organization: Organization, email: str, role=Membership.Role.MEMBER) -> User:
    user = User.objects.create_user(email=email, password="pw")
    Membership.objects.create(organization=organization, user=user, role=role)
    return user


@pytest.mark.django_db
class TestTheGate:
    """One question, answered in one place, with no third reason to say yes."""

    def test_a_seat_opens_every_edition(self):
        firm = make_organization(seats=3)
        member = join(firm, "member@firm.ca")
        assert member.has_active_subscription
        assert user_is_unrestricted(member)

    def test_an_admin_reads_too(self):
        firm = make_organization(seats=3)
        admin = join(firm, "admin@firm.ca", Membership.Role.ADMIN)
        assert admin.has_active_subscription

    def test_a_billing_only_role_reads_nothing(self):
        """The hole this role exists to close.

        If an administrator were simply exempt from consuming a seat, a firm
        could make all six people admins and pay for nothing.  The exemption
        is real, so it comes with no access.
        """
        firm = make_organization(seats=3)
        office = join(firm, "office@firm.ca", Membership.Role.BILLING)
        assert not office.has_active_subscription
        assert not user_is_unrestricted(office)
        assert firm.seats_used == 0

    def test_a_cancelled_subscription_closes_the_seat(self):
        firm = make_organization(seats=3, status="canceled")
        member = join(firm, "member@firm.ca")
        assert not member.has_active_subscription

    def test_no_organization_means_free_tier(self):
        alone = User.objects.create_user(email="alone@example.com", password="pw")
        assert not alone.has_active_subscription

    def test_the_courtesy_flag_still_works(self):
        courtesy = User.objects.create_user(
            email="courtesy@example.com", password="pw", pro_courtesy=True
        )
        assert courtesy.has_active_subscription

    def test_the_answer_is_cached_for_the_instance(self):
        """This runs on gated renders, and nearly all traffic is crawlers."""
        firm = make_organization(seats=1)
        member = join(firm, "member@firm.ca")
        assert member.has_active_subscription
        Subscription.objects.all().delete()
        assert member.has_active_subscription  # same instance, same answer
        assert not User.objects.get(pk=member.pk).has_active_subscription


@pytest.mark.django_db
class TestTheSeatCount:
    """The number on screen is the number on the invoice."""

    def test_seats_come_from_the_subscription_item(self):
        firm = make_organization(seats=6)
        assert firm.seats_bought == 6

    def test_a_top_level_quantity_is_read_too(self):
        """Stripe has written the quantity in two places over the years."""
        firm = make_organization(seats=2)
        subscription = firm.active_subscription
        assert subscription is not None
        subscription.stripe_data = dict(subscription.stripe_data, quantity=9)
        subscription.save(update_fields=["stripe_data"])
        assert Organization.objects.get(pk=firm.pk).seats_bought == 9

    def test_no_subscription_is_no_seats(self):
        assert make_organization().seats_bought == 0

    def test_only_seat_roles_are_counted(self):
        firm = make_organization(seats=5)
        join(firm, "a@firm.ca")
        join(firm, "b@firm.ca", Membership.Role.ADMIN)
        join(firm, "c@firm.ca", Membership.Role.BILLING)
        assert firm.seats_used == 2
        assert firm.seats_free == 3

    def test_free_seats_never_go_negative(self):
        """An admin can lower the count in Stripe below the people already in."""
        firm = make_organization(seats=1)
        join(firm, "a@firm.ca")
        join(firm, "b@firm.ca")
        assert firm.seats_used == 2
        assert firm.seats_free == 0


@pytest.mark.django_db
class TestInviting:
    def setup_method(self):
        self.firm = make_organization(seats=2)
        self.admin = join(self.firm, "admin@firm.ca", Membership.Role.ADMIN)

    def test_an_invitation_holds_only_a_hash(self):
        invite, token = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        assert token not in invite.hashed_token
        assert invite.hashed_token == Invite.hash_token(token)
        assert Invite.open_for_token(token) == invite

    def test_a_promised_seat_is_counted(self):
        """One seat is used by the admin, one is free, so the second invitation
        has nothing left to promise."""
        invite_member(self.firm, "one@firm.ca", Membership.Role.MEMBER)
        with pytest.raises(SeatError):
            invite_member(self.firm, "two@firm.ca", Membership.Role.MEMBER)

    def test_a_billing_invitation_needs_no_seat(self):
        invite_member(self.firm, "one@firm.ca", Membership.Role.MEMBER)
        invite_member(self.firm, "office@firm.ca", Membership.Role.BILLING)

    def test_the_same_address_is_not_invited_twice(self):
        invite_member(self.firm, "one@firm.ca", Membership.Role.MEMBER)
        with pytest.raises(SeatError):
            invite_member(self.firm, "one@firm.ca", Membership.Role.MEMBER)

    def test_somebody_already_in_is_not_invited(self):
        with pytest.raises(SeatError):
            invite_member(self.firm, "admin@firm.ca", Membership.Role.MEMBER)


@pytest.mark.django_db
class TestAccepting:
    """Where the seat check binds."""

    def setup_method(self):
        self.firm = make_organization(seats=2)
        self.admin = join(self.firm, "admin@firm.ca", Membership.Role.ADMIN)

    def test_taking_the_seat_grants_access(self):
        invite, token = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        newcomer = User.objects.create_user(email="new@firm.ca", password="pw")
        assert not newcomer.has_active_subscription

        accept_invite(invite, newcomer)
        assert User.objects.get(pk=newcomer.pk).has_active_subscription
        assert Invite.objects.get(pk=invite.pk).accepted_at is not None

    def test_a_forwarded_link_is_not_a_transfer(self):
        invite, _ = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        somebody_else = User.objects.create_user(email="other@firm.ca", password="pw")
        with pytest.raises(SeatError):
            accept_invite(invite, somebody_else)

    def test_no_free_seat_refuses(self):
        """The seat was free when the invitation went out and is not now."""
        invite, _ = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        join(self.firm, "faster@firm.ca")
        newcomer = User.objects.create_user(email="new@firm.ca", password="pw")
        with pytest.raises(SeatError):
            accept_invite(invite, newcomer)

    def test_a_spent_link_opens_nothing(self):
        invite, token = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        newcomer = User.objects.create_user(email="new@firm.ca", password="pw")
        accept_invite(invite, newcomer)
        assert Invite.open_for_token(token) is None

    def test_an_expired_link_opens_nothing(self):
        invite, token = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        invite.expires_at = timezone.now() - Invite.LIFETIME
        invite.save(update_fields=["expires_at"])
        assert Invite.open_for_token(token) is None

    def test_a_withdrawn_link_opens_nothing(self):
        invite, token = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])
        assert Invite.open_for_token(token) is None

    def test_an_invented_link_opens_nothing(self):
        assert Invite.open_for_token("not-a-real-token") is None


@pytest.mark.django_db
class TestTheTeamPanel:
    """What an administrator sees, and what a reader alone never sees."""

    def setup_method(self):
        self.client = Client()

    def test_a_reader_who_bought_alone_never_meets_the_word(self):
        alone = make_organization("solo", seats=1)
        buyer = join(alone, "solo@example.com", Membership.Role.ADMIN)
        self.client.force_login(buyer)
        body = self.client.get(reverse("web:user_settings")).content.decode()
        assert "Invite by email" not in body
        assert personal_organization(buyer) == alone

    def test_an_administrator_sees_the_panel(self):
        firm = make_organization("Firm", seats=3)
        admin = join(firm, "admin@firm.ca", Membership.Role.ADMIN)
        join(firm, "member@firm.ca")
        self.client.force_login(admin)
        body = self.client.get(reverse("web:user_settings")).content.decode()
        assert "Invite by email" in body
        assert "member@firm.ca" in body

    def test_a_member_gets_no_controls(self):
        firm = make_organization("Firm", seats=3)
        join(firm, "admin@firm.ca", Membership.Role.ADMIN)
        member = join(firm, "member@firm.ca")
        self.client.force_login(member)
        body = self.client.get(reverse("web:user_settings")).content.decode()
        assert "Invite by email" not in body

    def test_a_member_cannot_invite_by_posting(self):
        """The control is absent, and the view refuses the post as well."""
        firm = make_organization("Firm", seats=5)
        join(firm, "admin@firm.ca", Membership.Role.ADMIN)
        member = join(firm, "member@firm.ca")
        self.client.force_login(member)
        response = self.client.post(
            reverse("web:invite_to_team", args=[firm.pk]),
            {"email": "friend@firm.ca", "role": Membership.Role.MEMBER},
        )
        assert response.status_code == 404
        assert not Invite.objects.exists()

    def test_the_last_administrator_cannot_be_removed(self):
        firm = make_organization("Firm", seats=3)
        admin = join(firm, "admin@firm.ca", Membership.Role.ADMIN)
        membership = Membership.objects.get(user=admin)
        self.client.force_login(admin)
        self.client.post(reverse("web:remove_member", args=[membership.pk]))
        assert Membership.objects.filter(pk=membership.pk).exists()

    def test_removing_a_member_leaves_the_account(self):
        firm = make_organization("Firm", seats=3)
        admin = join(firm, "admin@firm.ca", Membership.Role.ADMIN)
        member = join(firm, "member@firm.ca")
        self.client.force_login(admin)
        self.client.post(
            reverse("web:remove_member", args=[Membership.objects.get(user=member).pk])
        )
        reloaded = User.objects.get(pk=member.pk)
        assert reloaded.is_active
        assert not reloaded.has_active_subscription


@pytest.mark.django_db
class TestTheInvitationPage:
    def setup_method(self):
        self.client = Client()
        self.firm = make_organization("Firm", seats=3)
        join(self.firm, "admin@firm.ca", Membership.Role.ADMIN)

    def test_opening_the_link_does_not_spend_the_seat(self):
        """A mail scanner that follows every link must not join the firm."""
        invite, token = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        newcomer = User.objects.create_user(email="new@firm.ca", password="pw")
        self.client.force_login(newcomer)

        response = self.client.get(reverse("web:accept_invite", args=[token]))
        assert response.status_code == 200
        assert not Membership.objects.filter(user=newcomer).exists()

        self.client.post(reverse("web:accept_invite", args=[token]))
        assert Membership.objects.filter(user=newcomer).exists()

    def test_a_stranger_is_told_which_address_it_is_for(self):
        _, token = invite_member(self.firm, "new@firm.ca", Membership.Role.MEMBER)
        stranger = User.objects.create_user(email="stranger@example.com", password="pw")
        self.client.force_login(stranger)
        response = self.client.get(reverse("web:accept_invite", args=[token]))
        assert response.status_code == 403
        assert "new@firm.ca" in response.content.decode()

    def test_somebody_who_already_pays_is_told_so(self):
        """Nothing cancels a subscription without the person clicking."""
        own = make_organization("own", seats=1)
        buyer = join(own, "buyer@example.com", Membership.Role.ADMIN)
        _, token = invite_member(self.firm, "buyer@example.com", Membership.Role.MEMBER)

        self.client.force_login(buyer)
        body = self.client.get(reverse("web:accept_invite", args=[token])).content.decode()
        assert "already pay" in body
        assert own.has_active_subscription


@pytest.mark.django_db
class TestTheWebhookLink:
    """Stripe is asked which organization pays, never guessed at."""

    def test_the_customer_metadata_names_the_organization(self):
        firm = make_organization("Firm")
        customer = Customer.objects.create(
            id="cus_hook",
            livemode=False,
            stripe_data={
                "id": "cus_hook",
                "object": "customer",
                "metadata": {"django_organization_id": str(firm.id)},
            },
        )
        handle_subscription_created(
            None, _FakeEvent({"object": {"customer": "cus_hook"}})
        )
        customer.refresh_from_db()
        assert customer.subscriber == firm

    def test_no_metadata_leaves_it_unlinked(self):
        """An unlinked customer is nobody's subscription, which the gate
        handles.  A wrongly linked one hands a stranger every edition."""
        customer = Customer.objects.create(
            id="cus_bare",
            livemode=False,
            stripe_data={"id": "cus_bare", "object": "customer"},
        )
        handle_subscription_created(
            None, _FakeEvent({"object": {"customer": "cus_bare"}})
        )
        customer.refresh_from_db()
        assert customer.subscriber is None


class _FakeEvent:
    """The one attribute the handler reads off a dj-stripe event."""

    def __init__(self, data):
        self.data = data


class TestTheSeatCountPosted:
    """What a checkout does with the number a buyer typed."""

    def _seats(self, value):
        return _requested_seats(RequestFactory().post("/", value))

    def test_nothing_posted_is_one_seat(self):
        assert self._seats({}) == 1

    def test_a_number_is_read(self):
        assert self._seats({"seats": "3"}) == 3

    def test_nonsense_is_one_seat(self):
        """The individual purchase posts no field, so a refusal here would
        explain nothing to the commonest buyer."""
        assert self._seats({"seats": "lots"}) == 1

    def test_the_count_is_capped(self):
        """Above the cap a firm is buying on an invoice and talks to a person,
        so a 500-seat card payment is a typing mistake."""
        assert self._seats({"seats": "500"}) == MAX_SELF_SERVE_SEATS
        assert self._seats({"seats": "-3"}) == 1


@pytest.mark.django_db
class TestWhatCheckoutSendsToStripe:
    """The seat price is what a firm pays for the seats *after* the first.

    The first seat is the Pro price, so a firm of one is a Pro subscription
    and there is no way to buy a single discounted seat.  Stripe bills that as
    two line items on one subscription, which ``Organization.seats_bought``
    already sums back into a seat count.
    """

    def _post(self, monkeypatch, settings, seats: str | None):
        settings.STRIPE_PRO_PRICE_ID = "price_first"
        settings.STRIPE_TEAM_PRICE_ID = "price_seat"
        captured: dict = {}

        def fake_customer_create(**kwargs):
            return {"id": "cus_fake"}

        def fake_session_create(**kwargs):
            captured.update(kwargs)
            return type("S", (), {"url": "https://stripe.test/checkout"})()

        monkeypatch.setattr("stripe.Customer.create", fake_customer_create)
        monkeypatch.setattr("stripe.checkout.Session.create", fake_session_create)

        client = Client()
        client.force_login(User.objects.create_user(email="buyer@firm.ca", password="pw"))
        data = {"organization_name": "Firm"}
        if seats is not None:
            data["seats"] = seats
        client.post(reverse("web:create_checkout_session"), data)
        return captured

    def test_one_seat_is_a_pro_subscription_and_nothing_else(
        self, monkeypatch, settings
    ):
        captured = self._post(monkeypatch, settings, None)

        assert captured["line_items"] == [{"price": "price_first", "quantity": 1}]

    def test_a_firm_pays_the_first_seat_once_and_the_rest_per_seat(
        self, monkeypatch, settings
    ):
        captured = self._post(monkeypatch, settings, "4")

        assert captured["line_items"] == [
            {"price": "price_first", "quantity": 1},
            {"price": "price_seat", "quantity": 3},
        ]

    def test_the_quantities_still_add_up_to_the_seats_asked_for(
        self, monkeypatch, settings
    ):
        """The shape is only safe because the seat count survives it.

        ``seats_bought`` reads the subscription, not this call, and it sums
        across items — so 1 + (n-1) must equal n or every seat figure in the
        product is wrong by one.
        """
        captured = self._post(monkeypatch, settings, "3")

        assert sum(item["quantity"] for item in captured["line_items"]) == 3


@pytest.mark.django_db
class TestWhatCountsAsAFirm:
    """A firm is one that bought seats, not one that has filled them.

    Judging by head count alone hid the invitation form from the only person
    who could use it, on the day the seats were bought — so a firm of five
    could reach none of them.
    """

    def test_a_firm_with_one_member_and_five_seats_is_not_personal(self):
        firm = make_organization(seats=5)
        join(firm, "admin@firm.ca", Membership.Role.ADMIN)
        assert not firm.is_personal

    def test_one_seat_and_one_person_is_personal(self):
        alone = make_organization("solo", seats=1)
        join(alone, "solo@example.com", Membership.Role.ADMIN)
        assert alone.is_personal

    def test_a_firm_that_bought_seats_shows_the_invitation_form(self):
        """The failure this closes: the buyer could not invite anybody."""
        firm = make_organization(seats=5)
        admin = join(firm, "admin@firm.ca", Membership.Role.ADMIN)
        client = Client()
        client.force_login(admin)
        body = client.get(reverse("web:user_settings")).content.decode()
        assert "Invite by email" in body
