from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Core'

    def ready(self):
        from django.core.checks import register

        from core.asset_signing import check_asset_signing_key

        # Refuses a deploy that would sign page scans with the wrong key.
        # The Cloudflare Worker already fails closed without its binding; this
        # is the same refusal on the app side.
        register(check_asset_signing_key)

        import core.auth_audit  # noqa: F401 — registers auth-event signal receivers
        import core.signup_notice  # noqa: F401 — registers the new-account notice
        import core.stripe_handlers  # noqa: F401
