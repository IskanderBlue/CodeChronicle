# Security hardening rollout — operator checklist

**Status: Part A is DONE. Part B, the off-host backups, is what remains.**
One-time rollout. Implements the off-host backups in
`docs/security/disaster-recovery-plan.md` §7 and the DB lockdown in
`docs/security/breach-response-plan.md` §8. The standing procedures live in
those two permanent docs; this file is the finite set of setup actions. **Move
it to `tasks/complete/` once B1–B8 are done.** The supporting code
(`core/auth_audit.py`, `manage.py backup_userdata`, `docs/security/db-roles.sql`)
already exists and is tested.

## Where this stands, 2026-08-08

**The next action is B1. Nothing blocks it, and every later B step needs its
output.**

| | |
|---|---|
| **Done** | A1, A2, A3, A4, A6 — Part A entire — and B5 |
| **Ready now** | **B1** (age keypair), then B2 and B3 (Cloudflare) |
| **Waiting on B1 + B2** | B4 |
| **Waiting on B4** | B6, and B7 and B8 behind it |
| **Rehearsed, not run for real** | B6 and B8's mechanics — see the notes under each |

A5, the Neon IP allow-list, is no longer here. It needs a paid tier and could
not be finished, so it moved to `tasks/maybe/neon-ip-allow-list.md` rather than
sit in this card as a permanently blocked line.

## Part A — Database access lockdown (§8). DONE.

The database is locked down. What is true on production now:

| | |
|---|---|
| **The app connects as `cc_app`** | least privilege — SELECT/INSERT/UPDATE/DELETE and sequence USAGE, and nothing else |
| **`cc_app` cannot** | run DDL, TRUNCATE any table, or CREATE in `public` |
| **`cc_ro` exists** | SELECT only, for a read-only session |
| **Neither role inherits anything** | no path to `neon_superuser` |
| **Migrations run as the owner** | automatically, in `publish.yml`, before the container is replaced |
| **TLS is required** | the server refuses `sslmode=disable` |

Verified across the whole schema rather than one table, and re-verified after
the 2026-08-08 deploy: of 104 tables, `cc_app` is missing a needed privilege on
**0** and holds TRUNCATE on **0**; `cc_ro` can UPDATE **0**; `cc_app` has USAGE
on all 100 sequences.

### What each step did

- **A1** (2026-08-07) created the roles from `docs/security/db-roles.sql`,
  after a full drill on `drill-db-roles-a1`, a branch of prod.
- **A2** built the two connection strings.
- **A3** (2026-08-08) rotated `database_url` to the `cc_app` string and
  restarted. `database_url` version 2 was written at 10:37:08Z, the container
  restarted at 10:37:41Z, and `cc_app` held connections from 10:37:52Z.
- **A4** (2026-08-08) moved the migrate-as-owner rule out of prose and into
  `publish.yml`. Full procedure: `docs/edit-prod-settings.md`.
- **A6** (2026-08-07) confirmed TLS by being refused without it.

### Five things Part A learned that are easy to undo by accident

1. **`cc_app` cannot run DDL, and `scripts/entrypoint.sh` runs `migrate` at
   every container start.** A migration that reaches a starting container
   unapplied stops it before gunicorn, and Docker restarts it into the same
   failure — a crash loop, not a degraded page. The `publish.yml` step applies
   each migration as the owner first, from the new image, before the container
   is replaced. **Do not remove that step, and do not reorder it after the
   deploy step.**
2. **The migrate step names a secret, never a credential.**
   `DATABASE_URL_SECRET_ID=database_url_owner` tells `production.py` which
   Secret Manager secret to read, and the container fetches it with the VM's
   service account. Passing the connection string instead would put a password
   in a workflow file, an ssh argument, the VM's shell history and a CI log —
   four places, to save one indirection.
   `core/tests/test_production_settings.py` holds this, because a broken
   override would silently migrate as `cc_app` and fail only in production.
3. **The owner uses the direct endpoint; the app uses the pooler.**
   `ep-shiny-boat-aivobvoc.c-4…` against `ep-shiny-boat-aivobvoc-pooler.c-4…`.
   A transaction-mode pooler cannot carry session-level DDL such as
   `CREATE INDEX CONCURRENTLY`. Do not tidy the two hosts into one.
4. **`neondb` is the wrong database and fails silently.** The project carries
   both `neondb` (Neon's empty default) and `codechroniclenet` (the 104 real
   tables). `GRANT … ON DATABASE neondb` succeeds, grants nothing, and leaves
   roles that look created and cannot read a row.
5. **A 200 does not prove the app changed roles.** Had the A3 restart failed,
   the old container would still be serving on the owner credential and every
   read *and* write would have passed. `pg_stat_activity.usename` is the only
   check that answers "as whom". Expect a second row there for the owner —
   that is your own SQL session.

### One prerequisite of A4 is still outstanding

🚨 **The `database_url_owner` secret does not exist yet, and the deploy pipeline
is blocked until it does.**

The migrate step runs on **every** deploy, not only ones carrying a migration.
Without the secret, `_get_secret` returns `""`, `production.py` falls through
to its non-DSN branch — `localhost:5432` as `postgres`, which does not exist —
and `migrate` cannot connect. The step fails, and the deploy step never runs.

The site is unaffected: the old container keeps serving, which is the failure
mode this step was designed for. But **no deploy will succeed until the secret
exists**, so create it before the next push to `main`.

**Copy it from `database_url` version 1; do not retype it.** That version *is*
the owner connection string, and copying keeps the password off the screen and
gets the direct host right:

```powershell
$tmp = "$env:TEMP\dburl_owner.txt"
$owner = gcloud secrets versions access 1 --secret=database_url --project=codechronicle-487104
[IO.File]::WriteAllText($tmp, $owner)
gcloud secrets create database_url_owner --data-file=$tmp --project=codechronicle-487104
Remove-Item $tmp
```

No IAM step is needed: the VM's service account holds
`secretmanager.secretAccessor` at project level, which covers a secret created
later.

**Rollback for A3** stays available while `database_url` version 1 is enabled:
re-add its value as a new version and restart.

---

## Part B — Off-host encrypted backups (§7)

> Steps are paste-ready. **[PASTE]** = run as-is (fill the obvious blanks);
> **[DASH]** = dashboard action, no CLI.

### B1. Generate the age keypair — KEEP THE PRIVATE KEY OFFLINE [PASTE]
Run on your own machine (install age first: `winget install FiloSottile.age`):
```powershell
age-keygen -o backup-key.txt
```
- The file's **public key** line (`# public key: age1…`) → goes in settings (B4).
- The whole file (the `AGE-SECRET-KEY-…` line) is the **private key** → store it in your
  password manager / offline. **Do not commit it, paste it anywhere, or put it on the VM.**
  Without it, backups are unrecoverable; if it leaks, backups are readable.

### B2. Create a dedicated R2 backups bucket + scoped token [DASH/PASTE]
Separate from the public assets bucket. With Wrangler:
```powershell
npx wrangler r2 bucket create codechronicle-backups-prod
```
Then **[DASH]** Cloudflare → R2 → Manage API Tokens → create a token scoped to **just this
bucket** (Object Read & Write). Note the Access Key ID + Secret.

### B3. Set retention on the bucket [DASH]
Cloudflare → R2 → `codechronicle-backups-prod` → Settings → **Object lifecycle rules** →
delete objects older than e.g. 90 days. (Preferred over the command's `--keep` flag.)

### B4. Put the new config in the prod secret bundle [PASTE]
```powershell
gcloud secrets versions access latest --secret=app_runtime_secrets --project=codechronicle-487104 > bundle.json
# Edit bundle.json — add these keys:
#   "R2_BACKUP_BUCKET":   "codechronicle-backups-prod",
#   "BACKUP_AGE_RECIPIENT":"age1…",                      <- the PUBLIC key from B1
#   "R2_ENDPOINT_URL":    "https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
#   "R2_ACCESS_KEY_ID":   "<from B2>",
#   "R2_SECRET_ACCESS_KEY":"<from B2>"
gcloud secrets versions add app_runtime_secrets --data-file=bundle.json --project=codechronicle-487104
del bundle.json
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```
(The `R2_*` keys are only needed if prod doesn't already carry them — the asset sync runs
elsewhere, so it likely doesn't.)

### B5. Put `pg_dump` + `age` in the container image — **DONE, live on prod 2026-08-08**
`postgresql-client-17` and `age` are in the `Dockerfile`'s existing `apt-get` layer, and
the running container answers `pg_dump` **17.10** and `age` **1.2.1**. No PGDG repository
is needed: the base image is Debian **Trixie** and carries both directly. The version is
pinned to 17 rather than the `postgresql-client` metapackage, because `pg_dump` must match
the server's major version and a base-image change should not move it quietly.

Confirm it in the container, which is the only place that proves it:
```powershell
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker exec codechroniclenet-web sh -c 'pg_dump --version; age --version'"
```

### B6. Smoke-test the pipeline, then a full run [PASTE]
```powershell
# local-only (no upload) — proves pg_dump + age work end to end:
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker exec codechroniclenet-web python manage.py backup_userdata --dest /tmp"
# full run — dump → encrypt → upload to R2:
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker exec codechroniclenet-web python manage.py backup_userdata"
```
Confirm the object appears under `db-backups/` in the bucket.

> **Rehearsed 2026-08-07, dump and restore both.** `pg_dump` was run as `cc_app` against
> a branch of prod, and the result restored into a scratch Postgres 17. It found a real
> defect, now fixed.
>
> The exclude-list held 14 tables and missed four — `provision_cross_references`,
> `provision_cross_reference_alternates`, `provision_version_assets` and
> `consolidations`. All four are rebuilt by `load_edition` (the last by
> `load_consolidations`, from `data/elaws_consolidations.json` in this repository), and
> all four hold foreign keys into tables the backup *does* exclude. So the restore could
> not create those keys: **five constraints failed, and pg_restore reported them as
> warnings and exited 0.** A restored database with 189 foreign keys instead of 194,
> from a command that said it succeeded.
>
> With the four added: the dump halves (1.7 MB → 859 KB — `provision_cross_references`
> alone was 42,983 rows in a backup whose job is to hold 6 users), the restore prints
> nothing at all, and all 194 foreign keys are present. The irreproducible data is
> untouched: 6 users, 111 searches, 10,597 events, 11 sessions.
>
> `core/tests/test_backup_userdata.py` now fails if a backed-up table gains a foreign
> key into an excluded one, so the next model does not have to rediscover this.
>
> **Note for B8:** a clean restore is not a full recovery. The corpus tables come back
> with their schema and no rows, so `load_edition` and `load_consolidations` must run
> before the site is usable. That is by design — see gotcha 4.

### B7. Schedule it (daily) [PASTE — run on the VM]
SSH to the VM (`gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap`) then:
```bash
( crontab -l 2>/dev/null; echo "0 7 * * * docker exec codechroniclenet-web python manage.py backup_userdata >> /var/log/cc-backup.log 2>&1" ) | crontab -
```
(07:00 UTC daily. Adjust as you like.)

### B8. Periodically test a restore [PASTE]
Decrypt with the **private** key (on your machine), then restore into a scratch DB or a
throwaway Neon branch — and stamp `disaster-recovery-plan.md` §6:
```powershell
age -d -i backup-key.txt -o restored.dump <downloaded>.dump.age
pg_restore --no-owner --no-privileges -d "<scratch_or_branch_connection_string>" restored.dump
# then refill the corpus on that target:
#   python manage.py load_edition --source ../CodeChronicleMapping/data/outputs
#   python manage.py load_consolidations
```
`load_consolidations` is part of the restore, not an extra. The `consolidations` table
is now excluded from the backup, so `load_edition` alone leaves it empty.

**A restore that prints nothing is the pass mark.** `pg_restore` reports a failed
constraint as a warning and still exits 0, so an exit code proves nothing. Count the
foreign keys instead — the restored database must have **194**:
```sql
SELECT count(*) FROM pg_constraint WHERE contype = 'f';
```

---

## Fixed values for this project

| Thing | Value |
|---|---|
| Neon project | `codechroniclenet` · id `restless-cell-46809886` · **db `codechroniclenet`** · PG 17 |
| App role | `cc_app` — least privilege, what the app connects as since 2026-08-08 |
| DB owner role | `codechroniclenet_app` — owns the database and all 104 tables; used for migrations only |
| App host | `ep-shiny-boat-aivobvoc-pooler.c-4.us-east-1.aws.neon.tech` (pooler) |
| Owner host | `ep-shiny-boat-aivobvoc.c-4.us-east-1.aws.neon.tech` (direct) |
| Neon org | `org-bold-unit-61886633` (iskander.lee@gmail.com) |
| GCP | project `codechronicle-487104` · VM `codechroniclenet-vm` · zone `us-central1-a` · container `codechroniclenet-web` |
| Secrets | Secret Manager: `app_runtime_secrets` (bundle), `database_url`, `database_url_owner` (**to create**) |
| PITR window | **6 hours** (`history_retention_seconds=21600`) — the reason for Part B |

## Gotchas that still apply

1. **The age private key (B1) is the only irreplaceable new secret.** Lose it → every
   backup is unreadable. It must never touch the repo, the VM, or any chat/transcript.
2. **`postgresql-client` major version must match the server (17).** A mismatched
   `pg_dump` refuses to dump a newer server.
3. **Corpus reproducibility is a dependency** (recovery §7): keep
   `CodeChronicleMapping/data/outputs` durably stored, or it becomes the new single point
   of failure for the part of the DB the backup deliberately skips. It includes
   `data/elaws_consolidations.json`, which rebuilds the excluded `consolidations` table —
   that file is in this repository, so it is already as durable as the code.
4. **A clean restore is not a recovery.** See the note under B6.
5. **A card is a memory of prod, not prod.** This card said migration `0052` was pending
   for a day after it had applied, and that held A3 back for no reason. Read
   `django_migrations` before you trust a sentence here about prod state.
6. **The failing thing reports success.** Three defects in this rollout were found by
   rehearsing rather than reading, and in all three the failure exited 0: a grant aimed at
   the empty `neondb`, a `pg_restore` that dropped five constraints as warnings, and a
   `migrate` that would crash-loop only at the next container start. Check by counting,
   not by exit codes.
7. **On completion** — the recurring facts already graduated to permanent docs, so they
   survive the archive: migrate-as-owner is in `docs/edit-prod-settings.md`, and
   restore-from-encrypted-backup is in the recovery plan §7.

> **Still available, and not yet done:** a real PITR restore drill (recovery §5a) to add
> a second row to the §6 log. The 2026-08-07 row covers 5b (the logical backup) only, so
> the host's own recovery path is still untested. Ask, and it will create the branch,
> run the drill, and — with your OK — delete the branch.
