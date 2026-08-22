"""The re-acceptance wall, and the rule that decides who meets it."""

import pytest
from django.test import Client
from django.urls import reverse

from core.models import TermsAcceptance, User
from core.reacceptance import ACCEPTED_VERSIONS_SESSION_KEY, outstanding

CURRENT_TERMS = "2026-08-18"
CURRENT_PRIVACY = "2026-08-19"


def _accept(user: User, terms: str, privacy: str) -> TermsAcceptance:
    return TermsAcceptance.objects.create(
        user=user, email=user.email, terms_version=terms, privacy_version=privacy
    )


@pytest.fixture
def versions(settings):
    settings.TERMS_VERSION = CURRENT_TERMS
    settings.PRIVACY_VERSION = CURRENT_PRIVACY
    settings.TERMS_REACCEPT_FROM = CURRENT_TERMS
    settings.PRIVACY_REACCEPT_FROM = CURRENT_PRIVACY
    return settings


@pytest.mark.django_db
class TestTheRule:
    def test_a_current_acceptance_is_asked_for_nothing(self, versions):
        user = User.objects.create_user(email="a@example.com")
        _accept(user, CURRENT_TERMS, CURRENT_PRIVACY)

        assert outstanding(user) == (False, False)

    def test_an_old_terms_acceptance_is_outstanding(self, versions):
        user = User.objects.create_user(email="a@example.com")
        _accept(user, "2026-06-01", CURRENT_PRIVACY)

        assert outstanding(user) == (True, False)

    def test_the_two_documents_are_asked_for_separately(self, versions):
        """The stamps are separate so only the document that changed asks."""
        user = User.objects.create_user(email="a@example.com")
        _accept(user, CURRENT_TERMS, "2026-06-17")

        assert outstanding(user) == (False, True)

    def test_a_minor_bump_asks_nothing(self, versions):
        """TERMS_VERSION moves for a typo; the floor does not."""
        user = User.objects.create_user(email="a@example.com")
        _accept(user, CURRENT_TERMS, CURRENT_PRIVACY)
        versions.TERMS_VERSION = "2026-09-02"

        assert outstanding(user) == (False, False)

    def test_the_latest_acceptance_decides(self, versions):
        """The table is append-only, so an old row must not re-trigger it."""
        user = User.objects.create_user(email="a@example.com")
        _accept(user, "2026-06-01", "2026-06-17")
        _accept(user, CURRENT_TERMS, CURRENT_PRIVACY)

        assert outstanding(user) == (False, False)

    def test_an_account_with_no_acceptance_is_never_trapped(self, versions):
        """Accounts made before clickwrap, or by a script, have nothing to
        re-affirm and no way to have been at fault."""
        user = User.objects.create_user(email="a@example.com")

        assert outstanding(user) == (False, False)

    def test_a_blank_privacy_stamp_asks_again(self, versions):
        """Rows written before the stamps split carry no privacy version."""
        user = User.objects.create_user(email="a@example.com")
        _accept(user, CURRENT_TERMS, "")

        assert outstanding(user) == (False, True)


@pytest.mark.django_db
class TestTheWall:
    def setup_method(self):
        self.client = Client()
        self.url = reverse("core:accept_terms")

    def _stale_user(self) -> User:
        user = User.objects.create_user(email="a@example.com", password="pw12345678")
        _accept(user, "2026-06-01", "2026-06-17")
        self.client.force_login(user)
        return user

    def test_a_stale_reader_is_redirected_to_the_wall(self, versions):
        self._stale_user()

        response = self.client.get(reverse("core:search"))

        assert response.status_code == 302
        assert response["Location"].startswith(self.url)

    def test_the_destination_is_carried_and_returned_to(self, versions):
        self._stale_user()
        target = reverse("core:pricing")

        redirected = self.client.get(target)
        assert f"next={target}" in redirected["Location"].replace("%2F", "/")

        accepted = self.client.post(self.url, {"accepted": "1", "next": target})
        assert accepted.status_code == 302
        assert accepted["Location"] == target

    def test_accepting_writes_a_row_with_both_current_versions(self, versions):
        user = self._stale_user()

        self.client.post(self.url, {"accepted": "1"})

        latest = TermsAcceptance.objects.filter(user=user).order_by("-accepted_at")[0]
        assert latest.terms_version == CURRENT_TERMS
        assert latest.privacy_version == CURRENT_PRIVACY

    def test_reaching_the_wall_is_not_acceptance(self, versions):
        user = self._stale_user()

        self.client.get(self.url)

        assert TermsAcceptance.objects.filter(user=user).count() == 1

    def test_an_unticked_box_records_nothing_and_says_so(self, versions):
        user = self._stale_user()

        response = self.client.post(self.url, {})

        assert response.status_code == 400
        assert TermsAcceptance.objects.filter(user=user).count() == 1

    def test_the_wall_does_not_stand_in_front_of_itself(self, versions):
        self._stale_user()

        assert self.client.get(self.url).status_code == 200

    def test_the_documents_stay_readable_behind_the_wall(self, versions):
        """A reader must be able to read what they are being asked to accept."""
        self._stale_user()

        for name in ("core:terms_of_service", "core:privacy_policy"):
            assert self.client.get(reverse(name)).status_code == 200

    def test_signing_out_is_still_possible(self, versions):
        """Refusing is allowed, so the exit cannot be behind the wall."""
        self._stale_user()

        response = self.client.get(reverse("account_logout"))

        assert response.status_code in (200, 302)
        if response.status_code == 302:
            assert not response["Location"].startswith(self.url)

    def test_an_offsite_next_is_refused(self, versions):
        """The wall is handed a destination on every request, which is the
        shape an open redirect takes."""
        self._stale_user()

        response = self.client.post(
            self.url, {"accepted": "1", "next": "https://evil.example.com/"}
        )

        assert response["Location"] == reverse("core:search")

    def test_a_current_reader_never_meets_it(self, versions):
        user = User.objects.create_user(email="b@example.com", password="pw12345678")
        _accept(user, CURRENT_TERMS, CURRENT_PRIVACY)
        self.client.force_login(user)

        assert self.client.get(reverse("core:search")).status_code == 200

    def test_the_verdict_is_cached_in_the_session(self, versions):
        user = User.objects.create_user(email="b@example.com", password="pw12345678")
        _accept(user, CURRENT_TERMS, CURRENT_PRIVACY)
        self.client.force_login(user)

        self.client.get(reverse("core:search"))

        assert self.client.session[ACCEPTED_VERSIONS_SESSION_KEY] == f"{CURRENT_TERMS}|{CURRENT_PRIVACY}"

    def test_an_anonymous_visitor_is_unaffected(self, versions):
        assert Client().get(reverse("core:search")).status_code == 200

    def test_the_api_is_not_walled(self, versions):
        """A bearer-key caller cannot act on an HTML wall."""
        self._stale_user()

        response = self.client.get("/api/health")

        assert response.status_code == 200
