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
(`tasks/complete/security-hardening-rollout.md`, step A3). Until you do, the app runs
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

**The deploy does this for you.** `.github/workflows/publish.yml` carries a step
named *Apply migrations as the database owner*, and it runs before the step that
replaces the container. You do not run anything by hand for an ordinary deploy.

The step pulls the new image and runs one `migrate` from it:

```
sudo docker run --rm --network host \
  --env-file /home/codechroniclenet/.env \
  -e DATABASE_URL_SECRET_ID=database_url_owner \
  <NEW_IMAGE> python manage.py migrate --noinput
```

Four things about that command are deliberate.

**It names a secret, not a credential.** `DATABASE_URL_SECRET_ID` tells
`production.py` which Secret Manager secret holds the connection string. The
container reads it with the VM's service account, exactly as it reads the app's
own. So the owner password appears in no workflow file, no ssh argument, no
shell history and no CI log. Never replace this with a literal `DATABASE_URL`.

**It runs from the new image.** The migration ships with the new code, so an
older image does not contain it.

**It runs before the container is replaced.** A failed migration fails the job,
the deploy step never runs, and the previous container keeps serving. The site
stays up on old code, which is what you want when a schema change will not
apply.

**`docker exec` into the running container is too late.** That container has
already run the entrypoint's `migrate` and already failed.

### What this depends on

| | |
|---|---|
| Secret | `database_url_owner`, holding the **owner** connection string |
| Role | `codechroniclenet_app` — Neon's owner role, created with the project |
| Host | `ep-shiny-boat-aivobvoc.c-4.us-east-1.aws.neon.tech` — the **direct** endpoint |
| Access | the VM's service account holds `secretmanager.secretAccessor` at project level, so the secret needs no binding of its own |

**The owner uses the direct endpoint, not the pooler.** The app's `cc_app` string names
the pooler, which is right for many short-lived request connections. A migration is the
opposite case: a transaction-mode pooler cannot carry session-level DDL such as
`CREATE INDEX CONCURRENTLY`. Do not "tidy" the two hosts into one.

**Where the owner password comes from.** It is `database_url` version 1 — the string
the app used before A3. Build `database_url_owner` by copying that version rather than
retyping it, which keeps the password off the screen and gets the direct host for free.

🚨 **The secret must exist, or no deploy succeeds.** The step runs on every deploy, not
only ones carrying a migration. With the secret missing, `_get_secret` returns `""`,
`production.py` falls through to its non-DSN branch (`localhost:5432` as `postgres`),
and `migrate` cannot connect. The step fails and the container is never replaced. The
site stays up on old code — but nothing new ships until the secret is there.

`core/tests/test_production_settings.py` holds the override. Without those
tests, a broken indirection would connect as `cc_app`, and you would learn it
from a failed production deploy.

### Running it by hand

You need this only if you deploy outside the workflow. Same command, with the
image tag filled in, over `gcloud compute ssh`. Do not paste a connection string
into it — set `DATABASE_URL_SECRET_ID` and let the container fetch the secret.
