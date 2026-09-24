"""Tests for the Turnstile check on signup and password reset.

The property that matters is the one a reader never sees: a refused POST
sends no email.  The check exists because both forms send an email to
whatever address is typed in, and after the send nothing can take it back.
So most tests here look at ``mail.outbox``, not at the page.

``siteverify`` is the one seam that reaches Cloudflare, and every test
replaces it.  The autouse fixture in ``conftest.py`` switches the check off;
the tests that need it on set a secret explicitly.
"""

from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse

from accounts import turnstile
from accounts.turnstile import REFUSAL, TOKEN_FIELD, check_turnstile_secret, token_passes
from core.models import User

PASSPHRASE = "a-long-enough-passphrase-42"


def _answer(action: str = "signup", hostname: str = "localhost", success: bool = True):
    return {"success": success, "action": action, "hostname": hostname}


def _sign_up(client, token: str | None = "a-token", email: str = "reader@example.com"):
    payload = {
        "email": email,
        "password1": PASSPHRASE,
        "password2": PASSPHRASE,
        "terms_accepted": "on",
    }
    if token is not None:
        payload[TOKEN_FIELD] = token
    return client.post(reverse("account_signup"), payload)


def _ask_for_reset(client, email: str, token: str | None = "a-token"):
    payload = {"email": email}
    if token is not None:
        payload[TOKEN_FIELD] = token
    return client.post(reverse("account_reset_password"), payload)


@pytest.fixture
def check_on(settings):
    settings.TURNSTILE_SECRET_KEY = "a-secret"
    settings.TURNSTILE_HOSTNAMES = ("localhost",)
    mail.outbox.clear()


class TestWhatATokenMustSay:
    """``token_passes``: all three of success, action and hostname, or nothing."""

    @pytest.fixture(autouse=True)
    def _hostnames(self, settings):
        settings.TURNSTILE_HOSTNAMES = ("localhost",)

    def _passes(self, answer, token="a-token", action="signup"):
        with mock.patch.object(turnstile, "siteverify", return_value=answer):
            return token_passes(token, action)

    def test_a_good_answer_passes(self):
        assert self._passes(_answer())

    def test_cloudflare_saying_no_refuses(self):
        assert not self._passes(_answer(success=False))

    def test_a_token_solved_on_the_other_form_refuses(self):
        """A reset token must not open signup, and the other way round."""
        assert not self._passes(_answer(action="password_reset"))

    def test_a_token_solved_on_another_site_refuses(self):
        """The site key is public, so somebody else's page can carry it."""
        assert not self._passes(_answer(hostname="evil.example"))

    def test_an_unreachable_cloudflare_refuses(self):
        """Fail closed: an open fallback is the path a bot would take."""
        with mock.patch.object(turnstile, "siteverify", side_effect=TimeoutError):
            assert not token_passes("a-token", "signup")

    @pytest.mark.parametrize("token", [None, "", 42, "x" * (turnstile.MAX_TOKEN_LENGTH + 1)])
    def test_no_usable_token_refuses_without_asking_cloudflare(self, token):
        with mock.patch.object(turnstile, "siteverify") as siteverify:
            assert not token_passes(token, "signup")
        siteverify.assert_not_called()


@pytest.mark.django_db
@pytest.mark.usefixtures("check_on")
class TestSignup:
    def test_a_refused_signup_creates_nobody_and_sends_nothing(self, client):
        with mock.patch.object(turnstile, "siteverify", return_value=_answer(success=False)):
            response = _sign_up(client)

        assert not User.objects.exists()
        assert mail.outbox == []
        assert REFUSAL in response.content.decode()

    def test_a_signup_with_no_token_is_refused(self, client):
        """What a script that posts the form directly sends."""
        _sign_up(client, token=None)
        assert not User.objects.exists()
        assert mail.outbox == []

    def test_a_passing_signup_creates_the_account(self, client):
        with mock.patch.object(turnstile, "siteverify", return_value=_answer()) as siteverify:
            _sign_up(client, token="the-posted-token")

        assert User.objects.filter(email="reader@example.com").exists()
        siteverify.assert_called_once_with("the-posted-token")

    def test_the_page_shows_the_widget_with_the_forms_action(self, client):
        page = client.get(reverse("account_signup")).content.decode()
        assert 'class="cf-turnstile"' in page
        assert 'data-action="signup"' in page


@pytest.mark.django_db
@pytest.mark.usefixtures("check_on")
class TestPasswordReset:
    @pytest.fixture
    def reader(self):
        return User.objects.create_user(email="reader@example.com", password=PASSPHRASE)

    def test_a_refused_request_sends_nothing_to_a_known_address(self, client, reader):
        with mock.patch.object(turnstile, "siteverify", return_value=_answer(success=False)):
            _ask_for_reset(client, reader.email)
        assert mail.outbox == []

    def test_a_refused_request_sends_nothing_to_an_unknown_address(self, client):
        """The bombing path: an unknown address gets an email when the check passes."""
        with mock.patch.object(turnstile, "siteverify", return_value=_answer(success=False)):
            _ask_for_reset(client, "stranger@example.com")
        assert mail.outbox == []

    def test_a_passing_request_still_answers_an_unknown_address(self, client):
        """The emails do not change: a reader who registered with a different
        address of their own still learns that this one has no account."""
        answer = _answer(action="password_reset")
        with mock.patch.object(turnstile, "siteverify", return_value=answer):
            _ask_for_reset(client, "stranger@example.com")
        assert [m.to for m in mail.outbox] == [["stranger@example.com"]]

    def test_a_signup_token_does_not_open_the_reset_form(self, client, reader):
        with mock.patch.object(turnstile, "siteverify", return_value=_answer(action="signup")):
            _ask_for_reset(client, reader.email)
        assert mail.outbox == []

    def test_the_page_shows_the_widget_with_the_forms_action(self, client):
        page = client.get(reverse("account_reset_password")).content.decode()
        assert 'data-action="password_reset"' in page


@pytest.mark.django_db
class TestSwitchedOff:
    """No secret: the forms work as before, and nobody calls Cloudflare."""

    def test_signup_needs_no_token(self, client):
        with mock.patch.object(turnstile, "siteverify") as siteverify:
            _sign_up(client, token=None)
        assert User.objects.filter(email="reader@example.com").exists()
        siteverify.assert_not_called()

    def test_the_page_shows_no_widget(self, client):
        page = client.get(reverse("account_signup")).content.decode()
        assert "cf-turnstile" not in page


class TestTheDeployRefusesAnOpenForm:
    """``check_turnstile_secret`` — ``accounts.E001``."""

    def test_it_objects_when_the_secret_is_missing(self, settings):
        settings.DEBUG = False
        settings.TURNSTILE_SECRET_KEY = ""
        assert [e.id for e in check_turnstile_secret(None)] == ["accounts.E001"]

    def test_it_is_satisfied_once_the_secret_is_set(self, settings):
        settings.DEBUG = False
        settings.TURNSTILE_SECRET_KEY = "a-secret"
        assert check_turnstile_secret(None) == []

    def test_a_developer_checkout_is_exempt(self, settings):
        settings.DEBUG = True
        settings.TURNSTILE_SECRET_KEY = ""
        assert check_turnstile_secret(None) == []
