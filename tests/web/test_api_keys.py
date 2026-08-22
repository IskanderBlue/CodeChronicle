"""Issuing and revoking keys from the settings page, and what the ledger shows."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from core.models import (
    ApiKey,
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionFetch,
    User,
)
from telemetry.insights import reading_coverage
from web.views.api_keys import MAX_ACTIVE_KEYS


@pytest.mark.django_db
class TestTheKeySection:
    def setup_method(self):
        self.client = Client()
        self.pro = User.objects.create_user(
            email="pro@example.com", password="pw", pro_courtesy=True
        )
        self.free = User.objects.create_user(email="free@example.com", password="pw")

    def test_a_subscriber_sees_the_section(self):
        self.client.force_login(self.pro)
        body = self.client.get(reverse("web:user_settings")).content.decode()
        assert "API keys" in body

    def test_a_free_reader_sees_nothing_about_it(self):
        """Hidden, not explained.  The pricing page is where the feature is
        sold; a control that only says "not for you" sells nothing."""
        self.client.force_login(self.free)
        body = self.client.get(reverse("web:user_settings")).content.decode()
        assert "API keys" not in body

    def test_making_a_key_shows_the_token_once(self):
        self.client.force_login(self.pro)
        self.client.post(reverse("web:create_api_key"), {"name": "takeoff"})

        first = self.client.get(reverse("web:user_settings")).content.decode()
        key = ApiKey.objects.get(user=self.pro)
        assert key.lookup in first
        assert "not shown again" in first

        second = self.client.get(reverse("web:user_settings")).content.decode()
        assert "not shown again" not in second

    def test_a_free_reader_cannot_make_a_key(self):
        """The view makes the same test the section does, so a posted form
        from a stale page is refused rather than honoured."""
        self.client.force_login(self.free)
        self.client.post(reverse("web:create_api_key"), {"name": "sneaky"})
        assert not ApiKey.objects.filter(user=self.free).exists()

    def test_the_key_count_is_capped(self):
        self.client.force_login(self.pro)
        for i in range(MAX_ACTIVE_KEYS + 2):
            self.client.post(reverse("web:create_api_key"), {"name": f"key {i}"})
        assert ApiKey.objects.filter(user=self.pro, revoked_at__isnull=True).count() == (
            MAX_ACTIVE_KEYS
        )

    def test_a_revoked_key_frees_a_slot(self):
        self.client.force_login(self.pro)
        for i in range(MAX_ACTIVE_KEYS):
            self.client.post(reverse("web:create_api_key"), {"name": f"key {i}"})
        doomed = ApiKey.objects.filter(user=self.pro).first()
        assert doomed is not None
        self.client.post(reverse("web:revoke_api_key", args=[doomed.pk]))
        self.client.post(reverse("web:create_api_key"), {"name": "replacement"})
        assert ApiKey.objects.filter(user=self.pro, revoked_at__isnull=True).count() == (
            MAX_ACTIVE_KEYS
        )

    def test_revoking_keeps_the_row(self):
        """The row is the record that the key existed, and a deleted row
        cannot explain a request in yesterday's log."""
        key, _ = ApiKey.generate(self.pro, "x")
        self.client.force_login(self.pro)
        self.client.post(reverse("web:revoke_api_key", args=[key.pk]))
        key.refresh_from_db()
        assert key.revoked_at is not None

    def test_nobody_revokes_somebody_elses_key(self):
        key, _ = ApiKey.generate(self.pro, "x")
        other = User.objects.create_user(email="other@example.com", password="pw")
        self.client.force_login(other)
        response = self.client.post(reverse("web:revoke_api_key", args=[key.pk]))
        assert response.status_code == 404
        key.refresh_from_db()
        assert key.revoked_at is None

    def test_a_lapsed_subscriber_can_still_revoke(self):
        """Revoking is a safety control, not a paid feature: somebody whose
        subscription ended must still be able to turn off a leaked key."""
        key, _ = ApiKey.generate(self.free, "issued while paying")
        self.client.force_login(self.free)
        self.client.post(reverse("web:revoke_api_key", args=[key.pk]))
        key.refresh_from_db()
        assert key.revoked_at is not None

    def test_the_key_routes_refuse_a_get(self):
        """Both write, so neither answers a link or a crawler."""
        self.client.force_login(self.pro)
        assert self.client.get(reverse("web:create_api_key")).status_code == 405


@pytest.mark.django_db
class TestTheCoverageReadout:
    """The novelty signal, which is the reason the text is fetched one at a time."""

    def setup_method(self):
        self.user = User.objects.create_user(email="pro@example.com", pro_courtesy=True)

    def _hold(self, count, fetch_count=1):
        for i in range(count):
            ProvisionFetch.objects.create(
                user=self.user,
                code_edition="OBC_2012",
                division="B",
                provision_id=f"9.8.{i}.",
                version=0,
                fetch_count=fetch_count,
                # Named, never left to the implicit empty string: a check
                # constraint refuses a row that does not say which surface
                # delivered it.
                source=ProvisionFetch.Source.API,
            )

    def test_a_recorder_reads_as_nearly_all_new(self):
        """Never the same provision twice is the shape being looked for."""
        self._hold(200, fetch_count=1)

        row = reading_coverage()[0]

        assert row["new_share"] == 100
        assert row["held"] == 200

    def test_a_working_reader_reads_as_mostly_repeats(self):
        """Returning to the same provisions is what real use looks like."""
        self._hold(5, fetch_count=20)

        row = reading_coverage()[0]

        assert row["fetches"] == 100
        assert row["new_share"] == 5

    def test_coverage_is_measured_against_the_whole_corpus(self):
        """A copy made a month at a time is still a copy, so the share is of
        everything held, not of the window."""
        edition = CodeEdition.objects.create(
            code=Code.objects.create(code="OBC", display_name="Ontario Building Code"),
            edition_id="2012",
            year=2012,
            effective_date=date(2012, 1, 1),
        )
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id="9.8.1.", level="article", division="B"
        )
        for n in range(4):
            # With text: the denominator counts versions that carry text,
            # because the ledger only records those.
            CodeEditionProvisionVersion.objects.create(
                provision=provision,
                version=n,
                effective_date=date(2012, 1, 1),
                html=f"<p>v{n}</p>",
            )
        self._hold(1)

        assert reading_coverage()[0]["coverage"] == 25.0

    def test_an_account_that_took_nothing_is_not_listed(self):
        assert reading_coverage() == []
