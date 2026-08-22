"""Tests for authentication audit logging (AuthEvent)."""

import pytest
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.test import RequestFactory

from core.models import AuthEvent, User


@pytest.fixture
def login_request():
    """A request carrying a client IP, as the auth views would have."""
    req = RequestFactory().get("/accounts/login/")
    req.META["REMOTE_ADDR"] = "203.0.113.7"
    return req


@pytest.mark.django_db
class TestAuthAudit:
    def test_records_successful_login(self, login_request):
        user = User.objects.create_user(email="a@example.com", password="pw")
        user_logged_in.send(sender=User, request=login_request, user=user)

        event = AuthEvent.objects.get()
        assert event.event_type == AuthEvent.EventType.LOGIN
        assert event.user == user
        assert event.email == "a@example.com"
        assert event.ip_address == "203.0.113.7"

    def test_records_logout(self, login_request):
        user = User.objects.create_user(email="b@example.com", password="pw")
        user_logged_out.send(sender=User, request=login_request, user=user)

        event = AuthEvent.objects.get()
        assert event.event_type == AuthEvent.EventType.LOGOUT
        assert event.user == user

    def test_failed_login_keeps_attempted_email_and_has_no_user(self, login_request):
        # The whole point of the failed-login row: no user exists, but the
        # presented identifier is captured for credential-stuffing detection.
        user_login_failed.send(
            sender=User,
            credentials={"email": "nobody@example.com", "password": "secret"},
            request=login_request,
        )
        event = AuthEvent.objects.get()
        assert event.event_type == AuthEvent.EventType.LOGIN_FAILED
        assert event.user is None
        assert event.email == "nobody@example.com"
        assert event.ip_address == "203.0.113.7"

    def test_failed_login_falls_back_to_username_key(self, login_request):
        # Django's model backend passes the identifier under "username";
        # allauth uses "email". The receiver accepts either.
        user_login_failed.send(
            sender=User,
            credentials={"username": "legacy@example.com"},
            request=login_request,
        )
        assert AuthEvent.objects.get().email == "legacy@example.com"

    def test_audit_never_raises_on_missing_request_or_credentials(self):
        # A receiver failure must never propagate into the auth flow.
        user_login_failed.send(sender=User, credentials=None, request=None)
        event = AuthEvent.objects.get()
        assert event.event_type == AuthEvent.EventType.LOGIN_FAILED
        assert event.email == ""
        assert event.ip_address is None
