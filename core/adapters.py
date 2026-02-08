"""Custom allauth adapter for CodeChronicle."""

from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    def get_password_change_redirect_url(self, request):
        return "/settings/#account"
