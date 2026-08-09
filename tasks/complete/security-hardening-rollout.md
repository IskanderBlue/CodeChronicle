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

**B1 to B7 and B9 are done. The next action is a deploy, then B8. Move this
card to `tasks/complete/` once B1–B9 are done.**

| | |
|---|---|
| **Done** | A1, A2, A3, A4, A6 — Part A entire — and B1 to B6 |
| **Done** (cont.) | B7 — the timer is installed, enabled and proven; B9's check and bundle key |
| **Waiting on a deploy** | B9's code — migration `0053` and the settings that read the ping URL |
| **After that** | B8, the restore test — the last step |
| **Rehearsed, not run for real** | B8's mechanics — see the note under it |

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

✅ **`database_url_owner` was created on 2026-08-08 and the whole path is
proven.** The workflow's exact command was run by hand against the deployed
image: it reached the real database through the new secret and reported "No
migrations to apply".

⚠️ **The secret must keep existing, or no deploy succeeds.** The migrate step
runs on **every** deploy, not only ones carrying a migration. If the secret is
missing, `_get_secret` returns `""`, `production.py` falls through to its
non-DSN branch — `localhost:5432` as `postgres`, which does not exist — and
`migrate` cannot connect. The step fails and the container is never replaced.
The site stays up on old code, but nothing new ships.

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

### Rolling A3 back

**Rebuild the owner string from `database_url_owner`, not from an old
`database_url` version.** The pre-A3 version 1 was byte-identical to
`database_url_owner` — same sha256 — so nothing was lost when it was
destroyed, but the "re-add the previous version" route is gone:

```powershell
$tmp = "$env:TEMP\dburl_rollback.txt"
$owner = gcloud secrets versions access latest --secret=database_url_owner --project=codechronicle-487104
[IO.File]::WriteAllText($tmp, $owner)
gcloud secrets versions add database_url --data-file=$tmp --project=codechronicle-487104
Remove-Item $tmp
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```

That puts the app back on the owner role, which is where it ran before
2026-08-08. It is a retreat, not a fix: check which grant `cc_app` is missing
before you leave it there.

---

## Part B — Off-host encrypted backups (§7)

> Steps are paste-ready. **[PASTE]** = run as-is (fill the obvious blanks);
> **[DASH]** = dashboard action, no CLI.

### B1. Generate the age keypair — DONE 2026-08-08. KEEP THE PRIVATE KEY OFFLINE [PASTE]
Run on your own machine (install age first: `winget install FiloSottile.age`):
```powershell
age-keygen -o backup-key.txt
```
- The file's **public key** line (`# public key: age1…`) → goes in settings (B4).
- The whole file (the `AGE-SECRET-KEY-…` line) is the **private key** → store it in your
  password manager / offline. **Do not commit it, paste it anywhere, or put it on the VM.**
  Without it, backups are unrecoverable; if it leaks, backups are readable.

### B2. Create a dedicated R2 backups bucket + scoped token [DASH]
Separate from the public assets bucket. Do both in the dashboard, because the token
half is a dashboard action anyway and Wrangler here is not logged in.

1. Cloudflare → R2 → **Create bucket** → `codechronicle-backups-prod`. Location
   automatic. Default storage class **Standard**. **Leave public access off** —
   this holds user data.

   *Not Infrequent Access.* IA trades storage price for retrieval charges,
   higher per-operation prices and a 30-day minimum billed duration. The dump is
   859 KB, so 90 days of dailies is about 77 MB — far inside R2 Standard's
   10 GB-month free allowance. IA would discount a bill of zero and put a
   retrieval charge on the restore test (B8) and on a real recovery.
2. Cloudflare → R2 → **Manage R2 API Tokens** → Create **Account** API token.
   Permission **Object Read & Write**, and under *Specify bucket(s)* pick
   **only** `codechronicle-backups-prod`.

   *An Account token, not a User token.* A User token carries one person's
   access and dies when that membership or those permissions change. This
   credential runs unattended on the VM.

   *A new token, not an existing all-buckets one.* The backup exists to survive
   an attacker who owns the VM. A credential on that VM that reaches every
   bucket lets the same attacker delete the backups. Reuse would also move
   all-buckets write access into Secret Manager and into a running container,
   and would tie rotation of the backup credential to the asset sync.
3. Note the **Access Key ID** and **Secret Access Key**. The secret is shown once.

⚠️ **Scoping contains the damage; it does not remove it.** R2's *Object Read &
Write* includes delete, so this token can still delete objects in the backups
bucket. The B3 lifecycle rule does not protect them either — it deletes as well.
Treat object immutability as open, not solved.

A Wrangler route exists (`npx wrangler login`, then
`npx wrangler r2 bucket create codechronicle-backups-prod`) and makes the bucket only.

### B3. Set retention on the bucket [DASH]
Cloudflare → R2 → `codechronicle-backups-prod` → Settings → **Object lifecycle rules** →
delete objects older than e.g. 90 days. (Preferred over the command's `--keep` flag.)

### B4. Put the new config in the prod secret bundle [PASTE]

> **A code change had to land first, 2026-08-08.** `backup_userdata` reads these
> as Django *settings*, and `base.py` filled them from `os.environ`. The prod
> container's env-file carries three variables and none of them is an R2 key, so
> the bundle keys would have been read by nothing: the command would abort with
> "R2_ENDPOINT_URL … not set" while the bundle plainly held one, which sends you
> to check the secret instead of the settings module. `production.py` now
> resolves all six through the bundle, the same way it already resolves email and
> Stripe, and `core/tests/test_production_settings.py` fails if that stops.
> **The fix must be deployed before this step is worth doing.**

```powershell
gcloud secrets versions access latest --secret=app_runtime_secrets --project=codechronicle-487104 > bundle.json
# Edit bundle.json — add these keys:
#   "R2_BACKUP_BUCKET":   "codechronicle-backups-prod",
#   "BACKUP_AGE_RECIPIENT":"age1…",                      <- the PUBLIC key from B1
#   "R2_ACCOUNT_ID":      "1606e553e771e417aab1107b4f3b7836",
#   "R2_ACCESS_KEY_ID":   "<from B2>",
#   "R2_SECRET_ACCESS_KEY":"<from B2>"
# R2_ENDPOINT_URL is optional: production.py derives it from R2_ACCOUNT_ID.
gcloud secrets versions add app_runtime_secrets --data-file=bundle.json --project=codechronicle-487104
del bundle.json
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```
Prod carries no `R2_*` key today — confirmed 2026-08-08. The asset sync runs from a
developer machine, and the serving app needs no R2 credential because a Worker with an
R2 binding serves the assets. So all of these are new.

**Use the B2 token, not the assets token.** The assets token cannot even list buckets
(checked 2026-08-08, `AccessDenied`), which is the boundary working. Do not widen it.

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

### B6. Smoke-test the pipeline, then a full run — **DONE on prod 2026-08-09** [PASTE]

Both forms ran against production, on image `4b8fcc6`:

| | |
|---|---|
| Local-only | `cc-userdata-20260809T044545Z.dump.age`, 979,114 bytes, exit 0 |
| Full run | uploaded to `r2://codechronicle-backups-prod/db-backups/` |
| Read back from the bucket | 1 object, 979,171 bytes, class STANDARD |
| Recipient | `age1vg86td83…`, out of `app_runtime_secrets` v6 |
| 18 corpus tables excluded | the original 14 plus the four the rehearsal found |

**List the bucket afterwards; do not trust the exit code.** The command logs
"uploading" before it calls R2, so its own success line proves the code path
ran, not that the object exists. A separate `list_objects_v2` is the first
statement that the bytes are there, and it also proves the B2 token can read as
well as write, which B8 needs.

The recipient in that log line is the other reason to read the output: it exists
only in bundle v6, so seeing it proves the settings resolution works on prod and
not only in the tests.

⚠️ **The local-only form leaves user data in the container's `/tmp`.** Remove it
after the run. A deploy clears it, but not before then.
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

### B7. Schedule it (daily) — **DONE on prod 2026-08-09** [PASTE — run on the VM]

Installed and enabled: `cc-backup.timer` next fires 07:02:10Z (the randomized
delay), and `cc-backup.service` was triggered once by hand to prove it —
`Result=success`, `ExecMainStatus=0`, and the journal shows the full pipeline
through the upload. **Run the unit once after you install a timer.** An
untested schedule is a schedule that fails at 07:00, to nobody.

The units are also in `CodeChronicleTerraform/modules/compute/startup.sh`
(uncommitted there as of this writing), so a rebuild keeps them.

> **Not cron.** The VM runs Container-Optimized OS, which ships no `crontab` for
> any user, including root. The scheduling primitive is a **systemd timer**, and
> `/etc/systemd/system` is writable and survives a reboot. A user crontab would
> also have tied the backup to one person's login — the objection that made an
> Account API token right in B2.

SSH to the VM, then:

```bash
sudo tee /etc/systemd/system/cc-backup.service >/dev/null <<'UNIT'
[Unit]
Description=CodeChronicle off-host encrypted user-data backup
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker exec codechroniclenet-web python manage.py backup_userdata
UNIT

sudo tee /etc/systemd/system/cc-backup.timer >/dev/null <<'UNIT'
[Unit]
Description=Run the CodeChronicle backup daily

[Timer]
OnCalendar=*-*-* 07:00:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now cc-backup.timer
systemctl list-timers cc-backup.timer --no-pager
```

Output goes to journald, not to a log file — on COS that is the durable place:

```bash
journalctl -u cc-backup.service -n 50 --no-pager
```

`Persistent=true` runs a schedule missed while the VM was down at the next boot.
It does **not** retry within the same day, so a deploy that replaces the
container while the timer fires costs one backup. B9's alarm tolerates that; two
consecutive misses it does not.

⚠️ **This is drift until it is in Terraform.** `startup.sh` in
`CodeChronicleTerraform/modules/compute/` rebuilds this VM, the same way it owns
`nginx.conf`. Add the same two units there, or a rebuild silently loses the
schedule — and a lost schedule is the exact failure B9 exists to catch.

### B9. Watch it — **check created and in the bundle, 2026-08-09** (added 2026-08-09)

`BACKUP_HEALTHCHECK_URL` is in `app_runtime_secrets` **v7**, and the URL was
validated with one live ping (HTTP 200; a wrong UUID answers 404, which would
otherwise mean an alarm that never fires and never says so). It stays inert
until the code that reads it deploys.

A backup nobody looks at is a backup nobody knows is broken. Two failures are
possible and they need different detectors:

| Failure | Signal | What catches it |
|---|---|---|
| the run fails | non-zero exit, journald | the `BackupRun` row, and the alarm's `/fail` ping |
| the run never happens | **nothing at all** | only the alarm, because it lives off this host |

The second is the dangerous one: silence and health look identical from the box.
Three things shipped against it, and they are not interchangeable.

**1. The upload is read back.** `upload_file` returning is not evidence the
object is there. The command now calls `head_object` and compares the size,
and fails if either is wrong. This removes a false-positive source *underneath*
whatever monitor sits on top.

**2. The record — a `BackupRun` row per run**, success or failure, shown on
`/insights/` with its age, size, object key and error text. Freshness is
measured from the newest **succeeded upload**: a failed run and a `--dest` drill
must not refresh the clock, and an empty table reads as stale rather than as
unknown. Stale after **26 hours** — one late run tolerated, two not.

**3. The alarm — a dead-man's switch.** Set `BACKUP_HEALTHCHECK_URL` in the
bundle. The run POSTs to it on success and to `<url>/fail` on failure, and the
service raises the alarm when a ping does not arrive. That polarity is the whole
point: you do not have to be right about which way it broke. A ping that fails
never fails the backup — the switch already alarms on silence, and reporting a
good backup as failed inverts the alarm.

To set it up:

1. Create a check at healthchecks.io (free tier). Period **1 day**, grace
   **2 hours**.
2. Copy its ping URL, then add one key to the bundle and restart:

```powershell
# same procedure as B4 — download, add "BACKUP_HEALTHCHECK_URL": "https://hc-ping.com/…", upload
gcloud secrets versions access latest --secret=app_runtime_secrets --project=codechronicle-487104 > bundle.json
gcloud secrets versions add app_runtime_secrets --data-file=bundle.json --project=codechronicle-487104
del bundle.json
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```

**What none of this proves.** A 979 KB encrypted object arriving daily could be
garbage, and every check above would call it healthy. Freshness is not
restorability. Only B8 answers that, which is why B8 stays.

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
| Secrets | Secret Manager: `app_runtime_secrets` (bundle), `database_url` (the app, `cc_app`), `database_url_owner` (migrations, the owner) |
| Cloudflare R2 | account `1606e553e771e417aab1107b4f3b7836` · assets bucket `codechronicle-assets-prod` · backups bucket `codechronicle-backups-prod` (B2) |
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
