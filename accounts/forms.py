"""Account forms for CodeChronicle."""

from django import forms
from django.conf import settings
from django.http import HttpRequest

from core.models import TermsAcceptance, User
from shared.ip import extract_client_ip


class CustomSignupForm(forms.Form):
    """Extra fields mixed into allauth's signup form via ``ACCOUNT_SIGNUP_FORM_CLASS``.

    Adds a required Terms of Service / Privacy Policy acceptance checkbox so
    that creating an account is an affirmative manifestation of assent
    (clickwrap), not mere browsewrap. The acceptance is recorded as an
    immutable ``TermsAcceptance`` row (both document versions, IP, user-agent,
    timestamp) as evidence of when, and to what, the user agreed.

    One checkbox, two recorded versions: the user assents to both documents in
    one act, but the documents are versioned separately so the record names
    the exact text each of them read.
    """

    terms_accepted = forms.BooleanField(
        required=True,
        label="I agree to the Terms of Service and Privacy Policy",
        error_messages={
            "required": (
                "You must accept the Terms of Service and Privacy Policy "
                "to create an account."
            ),
        },
    )

    def signup(self, request: HttpRequest, user: User) -> None:
        """allauth hook, invoked after the user is created.

        Records an immutable clickwrap acceptance row — both document
        versions, IP, user-agent, and timestamp; see ``TermsAcceptance``.
        """
        TermsAcceptance.objects.create(
            user=user,
            email=user.email,
            terms_version=settings.TERMS_VERSION,
            privacy_version=settings.PRIVACY_VERSION,
            ip_address=extract_client_ip(request.META),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )
