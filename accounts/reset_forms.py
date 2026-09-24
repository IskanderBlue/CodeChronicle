"""The password-reset form, with the Turnstile check in front of it.

A module of its own, not a class in ``accounts.forms``: allauth imports
``accounts.forms`` while it builds its own forms module
(``ACCOUNT_SIGNUP_FORM_CLASS``), so ``accounts.forms`` cannot import
``allauth.account.forms`` back without a circular import.

The emails do not change.  An address with no account still gets the "no
account uses this address" email, because a reader who registered with a
different address of their own needs that answer.  The check only decides
whether a person or a bot asked for it.
"""

from allauth.account.forms import ResetPasswordForm

from accounts.turnstile import TurnstileMixin


class TurnstileResetPasswordForm(TurnstileMixin, ResetPasswordForm):
    turnstile_action = "password_reset"
