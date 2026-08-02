"""Tests for the Pro price, read from the local dj-stripe row.

The bug this replaces: the page printed a literal while Stripe held the real
price, so the page could advertise a figure checkout did not charge and
nothing would fail. Every test here is about the two never disagreeing, or
about the page still printing *a* number when the row cannot be read.
"""

import pytest
from django.urls import reverse
from djstripe.models import Price, Product

from core.pricing import FALLBACK_AMOUNT, get_pro_price


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

        assert price.amount == "29"
        assert price.currency == "CAD"
        assert price.interval == "mo"
        assert price.from_stripe is True

    def test_a_new_stripe_figure_needs_no_deploy(self, settings):
        """The whole point: change it in Stripe, the page follows."""
        settings.STRIPE_PRO_PRICE_ID = "price_new"
        _make_price("price_new", unit_amount=29900)

        assert get_pro_price().amount == "299"

    def test_renders_cents_when_the_amount_has_them(self, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_cents"
        _make_price("price_cents", unit_amount=2999)

        assert get_pro_price().amount == "29.99"

    def test_a_yearly_price_says_yr(self, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_year"
        _make_price("price_year", recurring={"interval": "year", "interval_count": 1})

        assert get_pro_price().interval == "yr"

    def test_falls_back_when_the_row_is_missing(self, settings):
        """A webhook that has not landed must not 500 the pricing page."""
        settings.STRIPE_PRO_PRICE_ID = "price_absent"

        price = get_pro_price()

        assert price.amount == FALLBACK_AMOUNT
        assert price.currency == "CAD"
        assert price.from_stripe is False

    def test_falls_back_when_no_price_id_is_configured(self, settings):
        settings.STRIPE_PRO_PRICE_ID = ""

        assert get_pro_price().from_stripe is False

    def test_falls_back_for_a_tiered_price_with_no_flat_amount(self, settings):
        settings.STRIPE_PRO_PRICE_ID = "price_tiered"
        _make_price("price_tiered", unit_amount=None, billing_scheme="tiered")

        price = get_pro_price()

        assert price.amount == FALLBACK_AMOUNT
        assert price.from_stripe is False


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

    def test_the_page_still_prints_a_number_with_no_stripe_row(
        self, client, settings
    ):
        settings.STRIPE_PRO_PRICE_ID = "price_gone"

        response = client.get(reverse("core:pricing"))

        assert response.status_code == 200
        assert f"${FALLBACK_AMOUNT}" in response.content.decode()

    def test_the_roadmap_is_anchored_for_deep_links(self, client):
        body = client.get(reverse("core:pricing")).content.decode()
        assert 'id="roadmap"' in body
