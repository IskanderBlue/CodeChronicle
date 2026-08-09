"""Production settings whose indirection nothing else would catch.

Both halves here share one failure shape: the setting resolves to a plausible
wrong value instead of raising, and the deploy or the backup reports success.

## Which secret holds the DSN

`tasks/ao-security-hardening-rollout.md` A3 pointed the app at `cc_app`, which
cannot run DDL.  A4 applies each migration as the owner role instead, and the
deploy does that by naming a *different* Secret Manager secret for one
`migrate` run rather than by passing a connection string around.

That indirection fails silently in the worst place.  If the override stopped
working, the migrate step would connect as `cc_app`, the migration would fail
with `must be owner of table …`, and nobody would learn it until a deploy
carrying a schema change went out.  These tests hold the two halves: the
default is the app's own secret, and the environment can point it elsewhere.

## Where the backup reads its R2 credentials

`base.py` fills the `R2_*` settings from `os.environ`, and the GCP container's
env-file carries three variables, none of which is an R2 key.  So the backup
config has to come out of the `app_runtime_secrets` bundle, like email and
Stripe.  Miss that and the bundle keys are read by nothing: `backup_userdata`
aborts naming a setting that *is* in the bundle, which sends you to look at the
secret rather than at the settings module.

`GCP_PROJECT_ID` is empty throughout, so `_get_secret` never reaches the
network — it reads the matching environment variable and returns.
"""
import importlib
import json
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


BACKUP_KEYS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BACKUP_BUCKET",
    "BACKUP_AGE_RECIPIENT",
)


class TestBackupSettingsComeOutOfTheBundle:
    """`manage.py backup_userdata` reads these as settings, not as env vars."""

    def _with_bundle(self, bundle: dict, extra: dict | None = None):
        """Deliver a bundle the way the container gets it, through the secret.

        Blank the R2 variables first.  A developer's own `.env` carries the
        assets-bucket credentials, and `_reload_production` does not clear the
        environment, so without this the test reads the developer's account id
        and passes or fails by whose machine it runs on.
        """
        env = {k: "" for k in (*BACKUP_KEYS, "R2_ENDPOINT_URL")}
        env["APP_RUNTIME_SECRETS"] = json.dumps(bundle)
        env.update(extra or {})
        return _reload_production(env)

    def test_every_backup_setting_is_read_from_the_bundle(self):
        """The whole set, because one unresolved key stops the backup."""
        bundle = {k: f"value-of-{k}" for k in BACKUP_KEYS}
        settings = self._with_bundle(bundle)
        for key in BACKUP_KEYS:
            assert getattr(settings, key) == f"value-of-{key}", key

    def test_the_endpoint_is_derived_from_the_bundled_account_id(self):
        """base.py derived it from an account id that is empty in this container.

        Carrying that derived value over would leave the endpoint empty even
        with the account id supplied, and `backup_userdata` would report
        R2_ENDPOINT_URL missing while the bundle plainly holds an account.
        """
        settings = self._with_bundle({"R2_ACCOUNT_ID": "abc123"})
        assert settings.R2_ENDPOINT_URL == "https://abc123.r2.cloudflarestorage.com"

    def test_an_explicit_endpoint_wins_over_the_derived_one(self):
        settings = self._with_bundle(
            {"R2_ACCOUNT_ID": "abc123", "R2_ENDPOINT_URL": "https://example.invalid"}
        )
        assert settings.R2_ENDPOINT_URL == "https://example.invalid"

    def test_an_environment_variable_still_works(self):
        """A compose-style deploy sets these in the environment, as base.py did."""
        settings = self._with_bundle({}, {"R2_BACKUP_BUCKET": "from-the-environment"})
        assert settings.R2_BACKUP_BUCKET == "from-the-environment"

    def test_the_bundle_wins_over_the_environment(self):
        """One place decides, and on this deployment that place is the bundle."""
        settings = self._with_bundle(
            {"R2_BACKUP_BUCKET": "from-the-bundle"},
            {"R2_BACKUP_BUCKET": "from-the-environment"},
        )
        assert settings.R2_BACKUP_BUCKET == "from-the-bundle"
