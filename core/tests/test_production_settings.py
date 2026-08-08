"""The one production setting a deploy depends on: which secret holds the DSN.

`tasks/ao-security-hardening-rollout.md` A3 pointed the app at `cc_app`, which
cannot run DDL.  A4 applies each migration as the owner role instead, and the
deploy does that by naming a *different* Secret Manager secret for one
`migrate` run rather than by passing a connection string around.

That indirection fails silently in the worst place.  If the override stopped
working, the migrate step would connect as `cc_app`, the migration would fail
with `must be owner of table …`, and nobody would learn it until a deploy
carrying a schema change went out.  These tests hold the two halves: the
default is the app's own secret, and the environment can point it elsewhere.

`GCP_PROJECT_ID` is empty throughout, so `_get_secret` never reaches the
network — it reads the matching environment variable and returns.
"""
import importlib
import os
from unittest import mock

import pytest


def _reload_production(env: dict):
    """Import the production settings fresh under a given environment."""
    full_env = {"GCP_PROJECT_ID": "", **env}
    with mock.patch.dict(os.environ, full_env, clear=False):
        module = importlib.import_module("code_chronicle.settings.production")
        return importlib.reload(module)


@pytest.fixture(autouse=True)
def _restore_production_settings():
    """Reload the module once more at the end, so a later test sees it clean."""
    yield
    _reload_production({})


class TestDatabaseUrlSecretId:
    def test_the_app_reads_its_own_secret_by_default(self):
        """Nothing set means the least-privilege role, which is what serves."""
        settings = _reload_production({})
        assert settings.DATABASE_URL_SECRET_ID == "database_url"

    def test_the_deploy_can_point_it_at_the_owner_secret(self):
        """The migrate run names a different secret, and gets a different DSN."""
        settings = _reload_production(
            {
                "DATABASE_URL_SECRET_ID": "database_url_owner",
                "DATABASE_URL_OWNER": "postgresql://owner:pw@host/db",
            }
        )
        assert settings.DATABASE_URL_SECRET_ID == "database_url_owner"
        assert settings.DATABASES["default"]["USER"] == "owner"

    def test_an_empty_value_falls_back_rather_than_naming_no_secret(self):
        """An unset variable arrives as "" through some shells and env-files.

        Treating "" as a valid secret id would ask Secret Manager for a secret
        called nothing, get "", and leave the app on its non-DSN fallback —
        a wrong database rather than a loud failure.
        """
        settings = _reload_production({"DATABASE_URL_SECRET_ID": ""})
        assert settings.DATABASE_URL_SECRET_ID == "database_url"

    def test_the_two_secrets_do_not_share_an_environment_variable(self):
        """`_get_secret` derives the env name from the secret id.

        So `database_url` reads `DATABASE_URL` and `database_url_owner` reads
        `DATABASE_URL_OWNER`.  If they collided, the override would be a no-op
        and the deploy would migrate as `cc_app` while appearing to work.
        """
        settings = _reload_production(
            {
                "DATABASE_URL": "postgresql://app:pw@host/db",
                "DATABASE_URL_SECRET_ID": "database_url_owner",
                "DATABASE_URL_OWNER": "postgresql://owner:pw@host/db",
            }
        )
        assert settings.DATABASES["default"]["USER"] == "owner"
