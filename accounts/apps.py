from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = 'Accounts'

    def ready(self):
        from django.core.checks import register

        import accounts.signals.auth_audit  # noqa: F401 — registers auth-event signal receivers
        import accounts.signals.signup_notice  # noqa: F401 — registers the new-account notice
        import accounts.signals.stripe_handlers  # noqa: F401
        from accounts.turnstile import check_turnstile_secret

        # Refuses a deploy whose signup and reset forms would let any bot
        # send email to any address.
        register(check_turnstile_secret)
