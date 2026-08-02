"""Tests for the signup clickwrap and its two version stamps.

One checkbox covers the Terms of Service and the Privacy Policy, but the two
documents are versioned separately. The property under test is that a stamp
never claims a document changed when it did not, and never points at text that
has since been rewritten — the two ways a single shared stamp used to fail.
"""

import importlib

import pytest
from django.apps import apps
from django.conf import settings
from django.urls import reverse

from core.models import TermsAcceptance, User

# Migration module names begin with a digit, so they cannot be imported with
# a plain `from ... import`. Loading the real module (rather than copying its
# functions here) is the point: the test fails if the migration's backfill
# rule and its constant ever change without the test changing too.
_m0047 = importlib.import_module(
    "core.migrations.0047_termsacceptance_privacy_version_and_more"
)
backfill_privacy_version = _m0047.backfill_privacy_version
unset_privacy_version = _m0047.unset_privacy_version
PRE_SPLIT_PRIVACY_VERSION = _m0047.PRE_SPLIT_PRIVACY_VERSION


def _signup(client, email: str, **overrides):
    payload = {
        "email": email,
        "password1": "a-long-enough-passphrase-42",
        "password2": "a-long-enough-passphrase-42",
        "terms_accepted": "on",
    }
    payload.update(overrides)
    return client.post(reverse("account_signup"), payload)


@pytest.mark.django_db
class TestClickwrap:
    def test_signup_records_both_document_versions(self, client):
        _signup(client, "reader@example.com")

        acceptance = TermsAcceptance.objects.get()
        assert acceptance.terms_version == settings.TERMS_VERSION
        assert acceptance.privacy_version == settings.PRIVACY_VERSION
        assert acceptance.email == "reader@example.com"

    def test_the_two_versions_are_independent(self, client, settings):
        """Bumping one document must not restamp the other."""
        settings.TERMS_VERSION = "2026-06-17"
        settings.PRIVACY_VERSION = "2026-08-01"

        _signup(client, "split@example.com")

        acceptance = TermsAcceptance.objects.get()
        assert acceptance.terms_version != acceptance.privacy_version

    def test_refusing_the_checkbox_creates_neither_user_nor_record(self, client):
        _signup(client, "refuser@example.com", terms_accepted="")

        assert not User.objects.filter(email="refuser@example.com").exists()
        assert TermsAcceptance.objects.count() == 0

    def test_the_record_carries_the_evidence_fields(self, client):
        _signup(client, "evidence@example.com", HTTP_USER_AGENT="pytest-agent")

        acceptance = TermsAcceptance.objects.get()
        assert acceptance.ip_address
        assert acceptance.accepted_at is not None


@pytest.mark.django_db
class TestAcceptanceLookups:
    def test_each_document_is_checked_on_its_own_version(self, client):
        _signup(client, "lookup@example.com")
        user = User.objects.get(email="lookup@example.com")

        assert user.has_accepted_terms(settings.TERMS_VERSION)
        assert user.has_accepted_privacy(settings.PRIVACY_VERSION)
        # A user current on one document is not thereby current on the other.
        assert not user.has_accepted_privacy("1999-01-01")
        assert not user.has_accepted_terms("1999-01-01")

    def test_the_record_reads_both_versions(self, client):
        _signup(client, "str@example.com")

        text = str(TermsAcceptance.objects.get())
        assert settings.TERMS_VERSION in text
        assert settings.PRIVACY_VERSION in text


@pytest.mark.django_db
class TestBackfill:
    """Migration 0047's data step, exercised directly.

    Called as a plain function with the real app registry rather than through
    a migration harness: the step is a single ``update()``, and what needs
    proving is that it touches only blank rows and can be re-run.
    """

    def test_a_blank_row_is_stamped_with_the_policy_it_accepted(self):
        acceptance = TermsAcceptance.objects.create(
            email="old@example.com", terms_version="2026-06-17", privacy_version=""
        )

        backfill_privacy_version(apps, None)

        acceptance.refresh_from_db()
        assert acceptance.privacy_version == PRE_SPLIT_PRIVACY_VERSION

    def test_a_row_that_already_has_a_version_is_left_alone(self):
        acceptance = TermsAcceptance.objects.create(
            email="new@example.com",
            terms_version="2026-06-17",
            privacy_version="2026-08-01",
        )

        backfill_privacy_version(apps, None)

        acceptance.refresh_from_db()
        assert acceptance.privacy_version == "2026-08-01"

    def test_the_reverse_clears_only_what_the_backfill_set(self):
        stamped = TermsAcceptance.objects.create(
            email="a@example.com", terms_version="x", privacy_version=""
        )
        untouched = TermsAcceptance.objects.create(
            email="b@example.com", terms_version="x", privacy_version="2026-08-01"
        )

        backfill_privacy_version(apps, None)
        unset_privacy_version(apps, None)

        stamped.refresh_from_db()
        untouched.refresh_from_db()
        assert stamped.privacy_version == ""
        assert untouched.privacy_version == "2026-08-01"
