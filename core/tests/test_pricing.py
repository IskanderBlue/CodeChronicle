"""Tests for the Pro price, read from the local dj-stripe row.

Two rules, and every test here holds one of them: the page and checkout never
name different prices, and the page prints no figure at all rather than a
stand-in when the row cannot be read.
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse
from djstripe.models import Customer, Price, Product, Subscription

from api.auth import API_SEARCHES_BEFORE_THROTTLE
from core.models import Membership, Organization, User
from core.pricing import checkout_is_configured, get_pro_price
from core.views.billing import MAX_SELF_SERVE_SEATS, _requested_seats
from core.views.pages import _pricing_plans


def _make_price(price_id: str, **overrides):
    """A dj-stripe Price row shaped like the live one.

    ``stripe_data`` is what ``core.pricing`` reads; the concrete columns
    (``active``, ``currency``, ``product``) are set only because dj-stripe
    declares them NOT NULL. The product is created here for the same reason —
    ``product_id`` is a non-null foreign key.
    """
    data = {
        "id": price_id,
        "object": "price",
        "active": True,
        "currency": "cad",
        "unit_amount": 2900,
        "type": "recurring",
        "recurring": {"interval": "month", "interval_count": 1},
        "livemode": False,
    }
    data.update(overrides)
    product, _ = Product.objects.get_or_create(
        id="prod_test",
        defaults={
            "name": "CodeChronicle Pro",
            "livemode": False,
            "stripe_data": {"id": "prod_test", "object": "product", "name": "Pro"},
        },
    )
    return Price.objects.create(
        id=price_id,
        livemode=False,
        active=True,
        currency=data["currency"],
        product=product,
        stripe_data=data,
    )


@pytest.mark.django_db
class TestGetProPrice:
    def test_reads_amount_currency_and_interval_from_stripe(self, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_test123"
        _make_price("price_test123")

        price = get_pro_price()

        assert price is not None
        assert price.amount == "29"
        assert price.currency == "CAD"
        assert price.interval == "mo"

    def test_a_new_stripe_figure_needs_no_deploy(self, settings):
        """The whole point: change it in Stripe, the page follows."""
        settings.STRIPE_PRO_PRICE_ID = "price_new"
        _make_price("price_new", unit_amount=29900)

        price = get_pro_price()

        assert price is not None
        assert price.amount == "299"

    def test_renders_cents_when_the_amount_has_them(self, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_cents"
        _make_price("price_cents", unit_amount=2999)

        price = get_pro_price()

        assert price is not None
        assert price.amount == "29.99"

    def test_a_yearly_price_says_yr(self, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_year"
        _make_price("price_year", recurring={"interval": "year", "interval_count": 1})

        price = get_pro_price()

        assert price is not None
        assert price.interval == "yr"

    def test_says_nothing_when_the_row_is_missing(self, settings):
        """A webhook that has not landed must not 500 the pricing page.

        It must not invent a figure either. Checkout reads the price id, not
        this row, so it still charges correctly — and a stand-in number here
        would be the only thing on the page that was wrong.
        """
        settings.STRIPE_PRO_PRICE_ID = "price_absent"

        assert get_pro_price() is None

    def test_says_nothing_when_no_price_id_is_configured(self, settings):
        settings.STRIPE_PRO_PRICE_ID = ""

        assert get_pro_price() is None

    def test_says_nothing_for_a_tiered_price_with_no_flat_amount(self, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_tiered"
        _make_price("price_tiered", unit_amount=None, billing_scheme="tiered")

        assert get_pro_price() is None


class TestCheckoutIsConfigured:
    """The page must not offer a purchase the checkout view will refuse."""

    def test_a_price_id_means_pro_can_be_bought(self, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_live"

        assert checkout_is_configured() is True

    def test_no_price_id_means_there_is_no_way_to_pay(self, settings):
        settings.STRIPE_PRO_PRICE_ID = ""

        assert checkout_is_configured() is False


@pytest.mark.django_db
class TestPricingPage:
    def test_the_page_prints_the_stripe_figure_with_the_currency(
        self, client, settings
    ):
        settings.STRIPE_PRO_PRICE_ID = "price_page"
        _make_price("price_page", unit_amount=29900)

        body = client.get(reverse("core:pricing")).content.decode()

        assert "$299" in body
        # The currency is never omitted: "$299" alone is ambiguous to a
        # Canadian buyer and wrong to an American one.
        assert "CAD/mo" in body

    def test_the_page_quotes_no_figure_with_no_stripe_row(self, client, settings):
        """No row, no number — and no stand-in for one.

        The price id is set, so checkout still works and states the real
        figure. The card points at it instead of quoting one.
        """
        settings.STRIPE_PRO_PRICE_ID = "price_gone"

        response = client.get(reverse("core:pricing"))
        body = response.content.decode()

        assert response.status_code == 200
        assert "Price shown at checkout" in body
        assert "$29" not in body
        # Free is still genuinely zero, and says so without a currency it
        # would have had to borrow from a price nobody could read.
        assert "$0" in body

    def test_no_purchase_is_offered_when_nothing_can_take_the_money(
        self, client, settings
    ):
        """An empty price id is the state where there is no way to pay."""
        settings.STRIPE_PRO_PRICE_ID = ""

        body = client.get(reverse("core:pricing")).content.decode()

        assert "Sign up to upgrade" not in body
        assert "Price shown at checkout" not in body
        # The comparison still makes the argument for Pro; only the
        # purchase is withheld.
        assert "Ontario Building Code 2006" in body

    def test_the_roadmap_is_anchored_for_deep_links(self, client):
        body = client.get(reverse("core:pricing")).content.decode()
        assert 'id="roadmap"' in body

    def test_the_page_promises_the_api_in_one_place(self, client):
        """The API is a feature of the paid plans, not a plan and not a promise.

        It sat in the roadmap while the only way in was a replayed browser
        cookie.  Now that a key exists it is a comparison row, and naming it
        in both places would sell the same thing twice.

        The count is not the test.  A comparison row repeats across every
        column that includes it, which is what a comparison is for; what must
        not happen is the same feature appearing as a row *and* as something
        still to come.
        """
        body = client.get(reverse("core:pricing")).content.decode()
        plans, _, roadmap = body.partition('id="roadmap"')

        assert "Direct API access" in plans
        assert "Direct API access" not in roadmap


@pytest.mark.django_db
class TestCheckoutWithNoPriceConfigured:
    """What a reader meets when nothing can take the money.

    The pricing page withholds the purchase control in this state, so reaching
    the view needs a hand-made post or a stale tab.  It still has to answer
    with a page that works.
    """

    def test_it_sends_the_reader_back_to_a_whole_pricing_page(self, client, settings):
        settings.STRIPE_PRO_PRICE_ID = ""
        client.force_login(User.objects.create_user(email="buyer@example.com", password="pw"))

        response = client.post(reverse("core:create_checkout_session"), follow=True)
        body = response.content.decode()

        assert response.redirect_chain[-1][0] == reverse("core:pricing")
        assert "Pro is not available for purchase right now." in body
        # The setting name means nothing to a buyer, and the operator reads it
        # in the log instead.
        assert "STRIPE_PRO_PRICE_ID" not in body
        # The page renders through core.views.pages.pricing, so it carries its
        # comparison rows.  Rendering the template from the checkout view gave
        # it none, and an `error` key the template has never read.
        assert "Ontario Building Code 2006" in body


@pytest.mark.django_db
class TestTheFourColumns:
    """Free, Pro, Team and Custom read as one comparison, not a plan and a band.

    The seat factory here is a copy of the one in ``test_teams.py``.  It is
    twelve lines and there is no shared test package, so a second copy is
    cheaper than the import path a shared one would need.
    """

    def _firm(self, name: str = "Firm", seats: int = 3) -> Organization:
        organization = Organization.objects.create(name=name, email=f"{name}@x.ca")
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
                "status": "active",
                "items": {"data": [{"quantity": seats}]},
            },
        )
        return organization

    def test_every_plan_has_a_column(self, client):
        body = client.get(reverse("core:pricing")).content.decode()
        for name in ("Free", "Pro", "Team", "Custom"):
            assert f">{name}</h2>" in body

    def test_team_keeps_its_column_with_no_price_configured(self, client, settings):
        """The column says what the plan is; only the control depends on
        whether there is a way to pay."""
        settings.STRIPE_TEAM_PRICE_ID = ""
        body = client.get(reverse("core:pricing")).content.decode()
        assert ">Team</h2>" in body
        assert "Buy seats" not in body

    def test_team_offers_seats_once_a_price_exists(self, client, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_first"
        settings.STRIPE_TEAM_PRICE_ID = "price_seat"
        _make_price("price_first", unit_amount=29900)
        _make_price("price_seat", unit_amount=20000)
        user = User.objects.create_user(email="buyer@example.com", password="pw")
        client.force_login(user)

        body = client.get(reverse("core:pricing")).content.decode()

        assert "Buy seats" in body

    def test_team_prints_the_whole_bill_not_a_rate(self, client, settings):
        """The card states what a firm pays, not what it would have to work out.

        A team invoice is the Pro price once plus the seat price for every
        seat after it.  Printing those as two figures made the reader do the
        arithmetic; the card does it, for the seat count on screen.
        """
        settings.STRIPE_PRO_PRICE_ID = "price_first"
        settings.STRIPE_TEAM_PRICE_ID = "price_seat"
        _make_price("price_first", unit_amount=29900)
        _make_price("price_seat", unit_amount=20000)

        body = client.get(reverse("core:pricing")).content.decode()
        team = body.split(">Team</h2>")[1].split(">Custom</h2>")[0]

        # 299 + 200 for the two seats the card opens on.  The "$" sits
        # outside the Alpine span on purpose, so the currency symbol does not
        # flicker when only the number changes.
        assert '$<span x-text="total">499</span>' in team
        assert "(<span x-text=\"count\">2</span> seats)" in team
        assert "per seat after" not in team

    def test_the_total_is_server_rendered_so_it_needs_no_javascript(
        self, client, settings
    ):
        """Alpine re-totals the figure; it does not supply the first one.

        A card whose price appears only once a script runs states no price to
        a reader whose script did not.
        """
        settings.STRIPE_PRO_PRICE_ID = "price_first"
        settings.STRIPE_TEAM_PRICE_ID = "price_seat"
        _make_price("price_first", unit_amount=29900)
        _make_price("price_seat", unit_amount=20000)

        plans = {p["id"]: p for p in _pricing_plans(AnonymousUser())}

        assert plans["team"]["price"] == "499"
        # The cents are what the browser does arithmetic on. Money maths on
        # the rendered string is how a page quotes a figure Stripe would not
        # charge.
        assert plans["team"]["price_cents"] == 29900
        assert plans["team"]["extra_price_cents"] == 20000

    def test_team_cannot_be_bought_without_the_first_seat_price(
        self, client, settings
    ):
        """A team checkout sends two line items, so it needs two price ids.

        The Pro id was previously irrelevant to the Team control, which would
        have offered a purchase `create_checkout_session` refuses.
        """
        settings.STRIPE_PRO_PRICE_ID = ""
        settings.STRIPE_TEAM_PRICE_ID = "price_seat"
        _make_price("price_seat", unit_amount=20000)
        client.force_login(User.objects.create_user(email="b@example.com", password="pw"))

        body = client.get(reverse("core:pricing")).content.decode()

        assert "Buy seats" not in body

    def test_custom_is_quoted_and_never_priced(self, client, settings):
        """A figure beside Custom would be a guess at somebody else's quote."""
        settings.STRIPE_TEAM_PRICE_ID = "price_seat"
        _make_price("price_seat", unit_amount=9900)

        body = client.get(reverse("core:pricing")).content.decode()
        custom = body.split(">Custom</h2>")[1]

        assert "Quoted" in custom
        assert "mailto:support@codechronicle.ca" in custom
        # Custom inherits nothing on screen: a heading promising additions
        # over one line of prose read as an error.
        assert "Everything in Team" not in custom
        assert "Contact us to discuss your needs." in custom

    def test_a_seat_holder_reads_team_as_current_not_pro(self, client):
        """Asking only "do they pay" would mark Pro for somebody in a firm."""
        firm = self._firm(seats=5)
        member = User.objects.create_user(email="member@firm.ca", password="pw")
        Membership.objects.create(organization=firm, user=member)
        client.force_login(member)

        body = client.get(reverse("core:pricing")).content.decode()
        pro_column = body.split(">Pro</h2>")[1].split(">Team</h2>")[0]
        team_column = body.split(">Team</h2>")[1].split(">Custom</h2>")[0]

        assert "Current" not in pro_column
        assert "Current" in team_column

    def test_somebody_who_bought_alone_reads_pro_as_current(self, client):
        alone = self._firm("solo", seats=1)
        buyer = User.objects.create_user(email="solo@example.com", password="pw")
        Membership.objects.create(
            organization=alone, user=buyer, role=Membership.Role.ADMIN
        )
        client.force_login(buyer)

        body = client.get(reverse("core:pricing")).content.decode()
        pro_column = body.split(">Pro</h2>")[1].split(">Team</h2>")[0]

        assert "Current" in pro_column

    def test_the_seat_input_reads_the_constant_and_the_prose_names_no_ceiling(
        self, client, settings
    ):
        """The ceiling guards a typing mistake; it is not a sales boundary.

        So it bounds the input and the checkout clamp, and appears in no
        sentence.  Printing "up to N seats" would invent a boundary between
        Team and Custom that the product does not have: what separates them is
        a purchase order and negotiated terms, not head count.
        """
        settings.STRIPE_PRO_PRICE_ID = "price_first"
        settings.STRIPE_TEAM_PRICE_ID = "price_seat"
        _make_price("price_first", unit_amount=29900)
        _make_price("price_seat", unit_amount=20000)
        client.force_login(User.objects.create_user(email="c@example.com", password="pw"))

        body = client.get(reverse("core:pricing")).content.decode()

        assert f'max="{MAX_SELF_SERVE_SEATS}"' in body
        assert "seats or more" not in body
        assert "Up to" not in body

    def test_a_large_firm_can_still_buy_without_asking(self):
        """Refusing a purchase a buyer is ready to make protects nobody.

        Whether a firm can put four figures a month on a card is the firm's
        own constraint, and a firm that cannot goes to Custom by itself.  A
        low ceiling would only turn a sale we could take today into an email
        thread that may never close.
        """
        assert _requested_seats(RequestFactory().post("/", {"seats": "20"})) == 20

    def test_each_column_inherits_the_one_before_it(self):
        """The chain is what stops a column repeating the columns to its left.

        Free starts it and inherits nothing.  Pro and Team each name their
        predecessor.  Custom ends it, because it lists no features to inherit
        into.
        """
        plans = {p["id"]: p for p in _pricing_plans(AnonymousUser())}

        assert plans["free"]["inherits"] is None
        assert plans["pro"]["inherits"] == "Everything in Free, plus"
        assert plans["team"]["inherits"] == "Everything in Pro, plus"
        # Custom breaks the chain deliberately: what it adds is paperwork, and
        # "Everything in Team, plus" over one line of prose read as an error.
        assert plans["custom"]["inherits"] is None

    def test_no_feature_is_written_in_two_columns(self):
        """The whole reason the matrix went.  A repeated line is one that can
        drift, and it says nothing a reader could compare."""
        seen: set[str] = set()
        for plan in _pricing_plans(AnonymousUser()):
            for feature in plan["features"]:
                assert feature not in seen, feature
                seen.add(feature)

    def test_the_api_allowance_is_stated_where_the_api_is_sold(self, client):
        """Unlimited searches is true of the website and false of the API.

        A reader who meets "Unlimited searches" and a bare "Direct API access"
        concludes the API is unlimited too.  API_SEARCHES_BEFORE_THROTTLE is a real
        allowance, so the line that sells the API states it.
        """
        body = client.get(reverse("core:pricing")).content.decode()
        api_line = next(
            line for line in body.splitlines() if "Direct API access" in line
        )

        assert str(API_SEARCHES_BEFORE_THROTTLE) in api_line


@pytest.mark.django_db
class TestTheTeamMembershipSwitch:
    """``TEAM_MEMBERSHIPS_ENABLED`` sets this reader's membership aside.

    It exists so both states — "buy seats" and "manage seats" — are reachable
    without making and destroying an organization each time.  It is an
    interface switch: it never hides the Team column, never stops a firm
    buying, and never takes access away.
    """

    def _firm(self, seats: int = 3) -> Organization:
        organization = Organization.objects.create(name="Firm", email="f@x.ca")
        customer = Customer.objects.create(
            id="cus_switch",
            livemode=False,
            subscriber=organization,
            stripe_data={"id": "cus_switch", "object": "customer"},
        )
        Subscription.objects.create(
            id="sub_switch",
            livemode=False,
            customer=customer,
            stripe_data={
                "id": "sub_switch",
                "object": "subscription",
                "status": "active",
                "items": {"data": [{"quantity": seats}]},
            },
        )
        return organization

    def test_off_reads_team_as_something_to_buy(self, client, settings):
        settings.TEAM_MEMBERSHIPS_ENABLED = False
        settings.STRIPE_PRO_PRICE_ID = "price_first"
        settings.STRIPE_TEAM_PRICE_ID = "price_seat"
        _make_price("price_first", unit_amount=29900)
        _make_price("price_seat", unit_amount=20000)
        member = User.objects.create_user(email="m@firm.ca", password="pw")
        Membership.objects.create(
            organization=self._firm(), user=member, role=Membership.Role.ADMIN
        )
        client.force_login(member)

        body = client.get(reverse("core:pricing")).content.decode()
        team = body.split(">Team</h2>")[1].split(">Custom</h2>")[0]

        assert "Current" not in team
        assert "Buy seats" in team

    def test_on_reads_team_as_the_current_plan(self, client, settings):
        settings.TEAM_MEMBERSHIPS_ENABLED = True
        member = User.objects.create_user(email="m@firm.ca", password="pw")
        Membership.objects.create(organization=self._firm(), user=member)
        client.force_login(member)

        body = client.get(reverse("core:pricing")).content.decode()
        team = body.split(">Team</h2>")[1].split(">Custom</h2>")[0]

        assert "Current" in team

    def test_the_team_column_is_never_hidden_either_way(self, client, settings):
        """The switch sets a membership aside; it does not withdraw the plan."""
        for state in (True, False):
            settings.TEAM_MEMBERSHIPS_ENABLED = state
            body = client.get(reverse("core:pricing")).content.decode()
            assert ">Team</h2>" in body
            assert "repeat(4, minmax(0, 1fr))" in body

    def test_off_takes_no_access_away(self, settings):
        """The gate is ``has_active_subscription``, and this is not that gate.

        A switch that locked out a paying member would be a gate wearing a
        switch's clothes.
        """
        member = User.objects.create_user(email="m@firm.ca", password="pw")
        Membership.objects.create(organization=self._firm(), user=member)
        settings.TEAM_MEMBERSHIPS_ENABLED = False

        member = User.objects.get(pk=member.pk)  # drop the cached answer
        assert member.has_active_subscription is True
