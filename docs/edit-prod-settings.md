# Editing the app_runtime_secrets bundle

## Read this first: never use `>` to download the bundle

On 18 August 2026 this took the site down for the length of a rollback.

`>` in Windows PowerShell 5.1 writes **UTF-16LE with a BOM**. `production.py`
does `payload.data.decode("UTF-8")`, so an uploaded UTF-16 bundle raises
`UnicodeDecodeError`. `_get_secret` catches it and answers `""`, and
`_get_bundled_secret` turns that into `{}`. **Every** setting in the bundle
goes empty at once — `SECRET_KEY` and `DATABASE_URL` included — so the site
answers 502. The symptom does not point at the setting you edited, and it does
not point at encoding either.

The corrupt version 9 was 2336 bytes against version 8's 1131. Roughly double
is the signature: every character stored twice.

The same assumption bites in the other direction. `gcloud secrets versions
access` writing to a cp1252 console crashes with
`UnicodeEncodeError: 'charmap' codec can't encode characters`.

## Edit the bundle over the REST API

No file, no console encoding, no editor. The payload moves as base64 the whole
way.

```powershell
$P="codechronicle-487104"; $S="app_runtime_secrets"
$H = @{ Authorization = "Bearer $(gcloud auth print-access-token)" }

$r   = Invoke-RestMethod -Headers $H "https://secretmanager.googleapis.com/v1/projects/$P/secrets/$S/versions/latest:access"
$d   = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($r.payload.data)) | ConvertFrom-Json
$d.STRIPE_PRO_PRICE_ID = "price_..."     # <- the price_ ID, not prod_
$out = $d | ConvertTo-Json -Depth 10
```

**Check the result before you upload it.** The absence of this step is what
made the outage possible.

```powershell
$bytes = [Text.Encoding]::UTF8.GetBytes($out)
"{0} keys, {1} bytes" -f ($d.PSObject.Properties.Name.Count), $bytes.Length
```

The key count must match what you read. A count that fell, or a byte count
near double, means stop.

```powershell
$b64 = [Convert]::ToBase64String($bytes)
Invoke-RestMethod -Method POST -Headers $H -ContentType "application/json" `
  -Body (@{ payload = @{ data = $b64 } } | ConvertTo-Json) `
  "https://secretmanager.googleapis.com/v1/projects/$P/secrets/$S`:addVersion"
```

Restart:

```
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```

## Roll back

🚨 **Never roll back by disabling.** `latest` resolves to the most recently
**created** version, not the most recently enabled one. Disabling the bad
version does not fall back to the one before it — it makes `latest`
unreadable, and the app then behaves as though the bundle were empty. That is
the same 502, with a log line that names the version and the word `DISABLED`:

```
Failed to fetch secret app_runtime_secrets: 400 Secret Version [.../versions/9] is in DISABLED state.
```

**Roll back by adding a new version** holding the old content. The new version
becomes `latest` at once. Read the last good version, re-upload it with the
procedure above, and restart.

Disable or destroy the bad version afterwards, for tidiness. Do it after the
replacement exists, never as the rollback itself.

## Read a version's bytes without printing its values

To tell a good bundle from a bad one, look at the encoding, not the content:

```powershell
$H = @{ Authorization = "Bearer $(gcloud auth print-access-token)" }
$r = Invoke-RestMethod -Headers $H "https://secretmanager.googleapis.com/v1/projects/codechronicle-487104/secrets/app_runtime_secrets/versions/9:access"
$b = [Convert]::FromBase64String($r.payload.data)
"{0} bytes, first 4: {1}" -f $b.Length, (($b[0..3] | ForEach-Object { $_.ToString('x2') }) -join ' ')
```

`ff fe` is UTF-16LE. `ef bb bf` is a UTF-8 BOM. A healthy bundle starts `7b`,
which is `{`.

## Billing

Secret Manager bills each **active** version. Six are free. The state it
reports is **lowercase**, so a filter written as `state!=DESTROYED` matches
every row and tells you that you are paying for versions you already removed.
Read the column instead.

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
