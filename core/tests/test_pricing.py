"""Tests for the Pro price, read from the local dj-stripe row.

Two rules, and every test here holds one of them: the page and checkout never
name different prices, and the page prints no figure at all rather than a
stand-in when the row cannot be read.
"""

import pytest
from django.urls import reverse
from djstripe.models import Price, Product

from core.models import User
from core.pricing import checkout_is_configured, get_pro_price


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
