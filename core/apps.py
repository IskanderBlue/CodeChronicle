from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Core'

    def ready(self):
        import core.auth_audit  # noqa: F401 — registers auth-event signal receivers
        import core.stripe_handlers  # noqa: F401
