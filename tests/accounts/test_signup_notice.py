"""Tests for the new-account notice.

Two things can go wrong here and only one of them is visible. The notice can
fail to arrive, which we would notice eventually. Or the notice can break the
signup — and the reader, who has just handed over an email and a password,
meets a 500 for a message that was never for them.

So the tests are weighted towards the second. The signup must survive
anything this code does.
"""

import pytest
from django.core import mail
from django.urls import reverse

from core.models import User

PASSPHRASE = "a-long-enough-passphrase"
WATCHER = "rob@codechronicle.ca"


def _sign_up(client, email="newreader@example.com"):
    """A real signup, through the real form.

    ``terms_accepted`` is required (``accounts.forms.CustomSignupForm``): the
    clickwrap checkbox is part of creating an account, so a post without it
    creates nobody and every assertion below would be testing an empty page.
    """
    return client.post(
        reverse("account_signup"),
        {
            "email": email,
            "password1": PASSPHRASE,
            "password2": PASSPHRASE,
            "terms_accepted": "on",
        },
        follow=True,
    )


def _notices():
    return [m for m in mail.outbox if "New CodeChronicle account" in m.subject]


@pytest.mark.django_db
class TestTheNoticeArrives:
    def test_a_signup_writes_to_the_watchers(self, client, settings):
        settings.SIGNUP_NOTICE_EMAILS = [WATCHER]
        mail.outbox.clear()

        _sign_up(client)

        assert len(_notices()) == 1
        assert _notices()[0].to == [WATCHER]

    def test_the_notice_names_the_account(self, client, settings):
        settings.SIGNUP_NOTICE_EMAILS = [WATCHER]
        mail.outbox.clear()

        _sign_up(client, email="whoever@example.com")

        notice = _notices()[0]
        assert "whoever@example.com" in notice.subject
        assert "whoever@example.com" in notice.body

    def test_the_notice_carries_the_running_total(self, client, settings):
        """One signup means little; the shape of the line means a lot."""
        settings.SIGNUP_NOTICE_EMAILS = [WATCHER]
        User.objects.create_user(email="already@example.com", password="pw")
        mail.outbox.clear()

        _sign_up(client)

        assert "Total: 2 accounts" in _notices()[0].body

    def test_more_than_one_watcher_is_allowed(self, client, settings):
        settings.SIGNUP_NOTICE_EMAILS = [WATCHER, "two@example.com"]
        mail.outbox.clear()

        _sign_up(client)

        assert _notices()[0].to == [WATCHER, "two@example.com"]


@pytest.mark.django_db
class TestTheNoticeNeverCostsTheSignup:
    def test_a_broken_mail_host_does_not_break_the_signup(
        self, client, settings, monkeypatch
    ):
        """The account already exists by the time this runs, so a failure here
        would lose the notice *and* tell the reader their signup failed."""
        settings.SIGNUP_NOTICE_EMAILS = [WATCHER]

        def _explode(*args, **kwargs):
            raise OSError("mail host is down")

        monkeypatch.setattr("accounts.signals.signup_notice.send_mail", _explode)

        response = _sign_up(client)

        assert response.status_code == 200
        assert User.objects.filter(email="newreader@example.com").exists()

    def test_a_broken_count_still_sends_the_notice(self, client, settings, monkeypatch):
        """The total is nice to have.  Losing it must not lose the message."""
        settings.SIGNUP_NOTICE_EMAILS = [WATCHER]
        mail.outbox.clear()

        def _explode(*args, **kwargs):
            raise RuntimeError("no")

        monkeypatch.setattr("accounts.signals.signup_notice.User.objects.count", _explode)

        _sign_up(client)

        assert "newreader@example.com" in _notices()[0].body


@pytest.mark.django_db
class TestAnEmptyListSwitchesItOff:
    def test_no_watchers_means_no_notice(self, client, settings):
        """What a local run wants, and what stops a suite pretending to write
        to somebody."""
        settings.SIGNUP_NOTICE_EMAILS = []
        mail.outbox.clear()

        _sign_up(client)

        assert _notices() == []

    def test_the_signup_still_works(self, client, settings):
        settings.SIGNUP_NOTICE_EMAILS = []

        _sign_up(client)

        assert User.objects.filter(email="newreader@example.com").exists()


@pytest.mark.django_db
class TestItFiresOnceAndOnlyForSignups:
    def test_a_later_login_sends_nothing(self, client, settings):
        """``user_signed_up`` is allauth's signal for account creation.  A
        ``post_save`` on the user model would fire on every profile edit."""
        settings.SIGNUP_NOTICE_EMAILS = [WATCHER]
        _sign_up(client)
        client.logout()
        mail.outbox.clear()

        client.post(
            reverse("account_login"),
            {"login": "newreader@example.com", "password": PASSPHRASE},
        )

        assert _notices() == []

    def test_an_account_made_in_code_sends_nothing(self, settings):
        """The loader and the test suite create users directly.  Neither is
        somebody arriving at the product."""
        settings.SIGNUP_NOTICE_EMAILS = [WATCHER]
        mail.outbox.clear()

        User.objects.create_user(email="scripted@example.com", password="pw")

        assert _notices() == []
