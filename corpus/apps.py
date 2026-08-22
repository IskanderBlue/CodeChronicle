from django.apps import AppConfig


class CorpusConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'corpus'
    verbose_name = 'Corpus'

    def ready(self):
        from django.core.checks import register

        from corpus.asset_signing import check_asset_signing_key

        # Refuses a deploy that would sign page scans with the wrong key.
        # The Cloudflare Worker already fails closed without its binding; this
        # is the same refusal on the app side.
        register(check_asset_signing_key)
