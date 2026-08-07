from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Core'

    def ready(self):
        import core.auth_audit  # noqa: F401 — registers auth-event signal receivers
        import core.signup_notice  # noqa: F401 — registers the new-account notice
        import core.stripe_handlers  # noqa: F401
