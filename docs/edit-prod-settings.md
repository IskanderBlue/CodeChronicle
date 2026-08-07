Download bundle.

```
gcloud secrets versions access latest --secret=app_runtime_secrets --project=codechronicle-487104 > bundle.json
```

Edit bundle.json — e.g. add:

```
  "STRIPE_LIVE_SECRET_KEY": "sk_live_...",
  "STRIPE_PRO_PRICE_ID": "price_..."     <- the price_ ID, not prod_
```

Upload bundle, delete local copy:

```
gcloud secrets versions add app_runtime_secrets --data-file=bundle.json --project=codechronicle-487104
del bundle.json   # don't leave live keys sitting on disk
```

Restart:

```
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```

Secret Manager keeps the previous version. To roll back, add that version again,
then restart.

# Migrations, after the app runs as `cc_app`

Read this before you rotate `database_url` to the `cc_app` role
(`tasks/ao-security-hardening-rollout.md`, step A3). Until you do, the app runs
as `codechroniclenet_app`, which owns every table, and nothing here applies.

## Warning

`scripts/entrypoint.sh` runs `migrate --noinput` under `set -e`. The entrypoint
runs at **every container start**, not only at a deploy. `cc_app` cannot run
DDL. So a container that starts with a migration still pending stops before
gunicorn, and Docker restarts it into the same failure. The site is down, not
slow.

Measured on a branch of prod on 2026-08-07:

| The container starts, and | `migrate` | Result |
|---|---|---|
| no migration is pending | exit 0, "No migrations to apply" | the site starts |
| a schema migration is pending | exit 1, `must be owner of table …` | **crash loop** |

A migration that only changes Django state, such as an `AlterField` on the
choices of a field, writes no DDL and applies without a fault. Do not depend on
this. You cannot see which kind you have from the deploy.

## The rule

**Apply each migration as the owner role, before the new container starts.**
The entrypoint then finds nothing to apply, exits 0, and the site starts.

1. Pull the new image on the VM.
2. Run the migration from that image, one time, with the owner role:

```
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker run --rm -e DJANGO_SETTINGS_MODULE=code_chronicle.settings.production -e DATABASE_URL='postgresql://<OWNER>:<OWNER_PW>@<HOST>/codechroniclenet?sslmode=require' <NEW_IMAGE> python manage.py migrate --noinput"
```

3. Start the new container as usual.

Run the migration from the **new** image. The migration is part of the new
code, so an older image does not contain it.

`production.py` lets the `DATABASE_URL` environment variable override the
secret, which is what makes step 2 possible without a secret change.

`<HOST>` is `ep-shiny-boat-aivobvoc-pooler.c-4.us-east-1.aws.neon.tech`.
`<OWNER>` is `codechroniclenet_app`. Keep the owner password out of the shell
history and out of any transcript.
