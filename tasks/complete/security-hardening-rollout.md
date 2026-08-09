# Security hardening rollout — operator record

**Complete. 2026-08-07 to 2026-08-09.** Part A locked down database access
(`docs/security/breach-response-plan.md` §8). Part B added off-host encrypted
backups (`docs/security/disaster-recovery-plan.md` §7).

This card is the record of what changed on production and how to undo it. The
**standing procedures live in the two permanent documents** and in
`docs/edit-prod-settings.md`; nothing here needs to be read to operate the
system. A5, the Neon IP allow-list, needs a paid tier and moved to
`tasks/maybe/neon-ip-allow-list.md`.

## What is true on production now

| | |
|---|---|
| The app connects as `cc_app` | SELECT/INSERT/UPDATE/DELETE and sequence USAGE, nothing else |
| `cc_app` cannot | run DDL, TRUNCATE any table, or CREATE in `public` |
| `cc_ro` exists | SELECT only, for a read-only session |
| Neither role inherits | no path to `neon_superuser` |
| Migrations run as the owner | in `publish.yml`, before the container is replaced |
| TLS is required | the server refuses `sslmode=disable` |
| A backup runs daily | 07:00 UTC, `cc-backup.timer`, encrypted to an age key, uploaded to R2 |
| Each upload is read back | `head_object` plus a size comparison, or the run fails |
| Each run is recorded | a `BackupRun` row, shown on `/insights/` with its age |
| Silence raises an alarm | a healthchecks.io dead-man's switch |
| The backup credential cannot delete | an R2 bucket lock, whole-bucket — verified 2026-08-09 |
| Objects expire after 90 days | an R2 lifecycle rule, which the lock outranks |
| The host's PITR reaches 6 hours | measured against the server, not a config value — verified 2026-08-09 |

Verified across the whole schema, not one table: of 104 tables, `cc_app` is
missing a needed privilege on **0** and holds TRUNCATE on **0**; `cc_ro` can
UPDATE **0**; `cc_app` has USAGE on all 100 sequences.

## Fixed values

| Thing | Value |
|---|---|
| Neon project | `codechroniclenet` · id `restless-cell-46809886` · **db `codechroniclenet`** · PG 17 |
| App role | `cc_app`, on the **pooler** host `ep-shiny-boat-aivobvoc-pooler.c-4.us-east-1.aws.neon.tech` |
| DB owner role | `codechroniclenet_app`, on the **direct** host `ep-shiny-boat-aivobvoc.c-4.us-east-1.aws.neon.tech` |
| GCP | project `codechronicle-487104` · VM `codechroniclenet-vm` · zone `us-central1-a` · container `codechroniclenet-web` |
| Secrets | `app_runtime_secrets` (bundle), `database_url` (`cc_app`), `database_url_owner` (migrations), `cf_origin_cert`, `cf_origin_key` — **6 active versions**, the free ceiling |
| Cloudflare R2 | account `1606e553e771e417aab1107b4f3b7836` · assets `codechronicle-assets-prod` · backups `codechronicle-backups-prod` |
| PITR window | **6 hours** (`history_retention_seconds=21600`) — the reason Part B exists |

## How to undo it

**Part A — put the app back on the owner role.** A retreat, not a fix: find
which grant `cc_app` is missing before you leave it there. Rebuild the string
from `database_url_owner`, because the pre-A3 `database_url` version 1 is
destroyed (it was byte-identical — same sha256 — so nothing was lost).

```powershell
$tmp = "$env:TEMP\dburl_rollback.txt"
$owner = gcloud secrets versions access latest --secret=database_url_owner --project=codechronicle-487104
[IO.File]::WriteAllText($tmp, $owner)
gcloud secrets versions add database_url --data-file=$tmp --project=codechronicle-487104
Remove-Item $tmp
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```

**Part B — the bundle.** `app_runtime_secrets` **v7** carries the backup keys
(five from B4, plus `BACKUP_HEALTHCHECK_URL`). **v6** is the rollback, and holds
the five without the healthcheck URL. Add the old version as a new one and
restart; never edit in place. Full procedure: `docs/edit-prod-settings.md`.

**Part B — the schedule.** `sudo systemctl disable --now cc-backup.timer` stops
it on the running VM, and removing the two units from
`CodeChronicleTerraform/modules/compute/startup.sh` stops a rebuild restoring
them. Both are needed.

## What each step changed

| Step | Date | Change |
|---|---|---|
| A1 | 2026-08-07 | Created the roles from `docs/security/db-roles.sql`, after a full drill on `drill-db-roles-a1`, a branch of prod |
| A2 | 2026-08-07 | Built the two connection strings |
| A3 | 2026-08-08 | Rotated `database_url` to `cc_app`; `cc_app` held connections 44 s after the secret was written |
| A4 | 2026-08-08 | Moved migrate-as-owner out of prose and into `publish.yml` |
| A6 | 2026-08-07 | Confirmed TLS by being refused without it |
| B1 | 2026-08-08 | Generated the age keypair. **The private key is offline and is the only irreplaceable secret here** |
| B2 | 2026-08-09 | Created `codechronicle-backups-prod` and a bucket-scoped **Account** API token |
| B3 | 2026-08-09 | 90-day object lifecycle rule |
| B4 | 2026-08-09 | Five R2/age keys into the bundle (v6) |
| B5 | 2026-08-08 | `postgresql-client-17` and `age` in the image; the container answers `pg_dump` 17.10, `age` 1.2.1 |
| B6 | 2026-08-09 | First real backup: 979,171 bytes in the bucket |
| B7 | 2026-08-09 | `cc-backup.timer` installed, enabled, proven, and mirrored into Terraform (`28d3adf`) |
| B9 | 2026-08-09 | Verification, the `BackupRun` record and the dead-man's switch |
| B8 | 2026-08-09 | The restore drill. Stamped in the recovery plan §6 |
| B10 | 2026-08-09 | The bucket lock, verified; and the PITR drill, the first 5a row in §6 |

## What the rehearsals found

Seven defects, and **every one of them exited 0**. That is the single most useful
thing this rollout learned: check by counting, never by an exit code.

1. **A grant aimed at `neondb`.** The project carries both `neondb` (Neon's
   empty default) and `codechroniclenet` (the 104 real tables).
   `GRANT … ON DATABASE neondb` succeeds, grants nothing, and leaves roles that
   look created and cannot read a row.
2. **A dump that dropped five foreign keys.** The exclude-list held 14 tables
   and missed four whose rows reference excluded corpus tables. `pg_restore`
   reported each failure as a warning and exited 0 — 189 foreign keys where the
   original had 194. Fixed; adding the four also halved the dump.
   `core/tests/test_backup_userdata.py` now fails if a kept table gains a
   foreign key into an excluded one.
3. **Settings the container never read.** `backup_userdata` reads Django
   settings that `base.py` fills from `os.environ`, and the prod env-file
   carries three variables, none of them an R2 key. The command aborted naming
   a setting the bundle plainly held. `production.py` now resolves all six
   through the bundle, guarded by `core/tests/test_production_settings.py`.
4. **`load_edition` loaded one edition for each run.** The restore procedure
   said `--source <dir>` and nothing else, which loads the default
   `OBC_2012.json`. A restored site would have held one edition of three and
   looked complete. `--all` now loads every edition, oldest first.
5. **`province_codes` was excluded as corpus and no loader recreated it.** The
   one row maps ON to OBC. Without it a search answers **0 matches**; with it,
   **158**. The site reads as an empty corpus rather than a broken one.
   `Command.CODE_PROVINCES` now seeds it on every load.
6. **A reload deleted consolidation rows nothing put back.** `Consolidation` has
   a foreign key to `CodeEdition` with CASCADE, so loading an edition wipes its
   rows. Production carried **0** rows for OBC 1997 — every 1997 provision read
   as reconstruction-only — because the follow-up step was skipped once.
   `load_edition` now calls `load_consolidations` itself. Production was
   corrected on 2026-08-09; all three editions now match the source file.

7. **`neonctl` ignored an unknown flag and reported success.** `--parent-timestamp`
   does not exist; the correct flag is `--parent`. The branch was created from
   **now**, the success table printed, and it read as a point-in-time restore of
   a database that was simply live. Found in B10. Prove a branch is where you
   asked with a marker that cannot exist yet.

The drills also proved both restores work. B8: the bucket copy downloads, the
private key decrypts it, `pg_restore` prints nothing and makes **194 of 194**
foreign keys, the user data matches production exactly, and a search answers.
B10: a point-in-time branch 5 h 30 m back in 3 seconds, corpus included.

## Gotchas that outlive this card

1. **The age private key is irreplaceable.** Lose it and every backup is
   unreadable. It must never touch the repository, the VM, or any transcript.
2. **`cc_app` cannot run DDL, and `scripts/entrypoint.sh` runs `migrate` at
   every container start.** An unapplied migration stops the container before
   gunicorn, and Docker restarts it into the same failure — a crash loop, not a
   degraded page. **Do not remove the `publish.yml` migrate step, and do not
   reorder it after the deploy step.**
3. **`database_url_owner` must keep existing.** The migrate step runs on every
   deploy, not only ones carrying a migration. Without the secret the step
   cannot connect, and the container is never replaced. The site stays up on old
   code and nothing ships.
4. **The owner uses the direct endpoint; the app uses the pooler.** A
   transaction-mode pooler cannot carry session-level DDL such as
   `CREATE INDEX CONCURRENTLY`. Do not tidy the two hosts into one.
5. **A 200 does not prove the app changed roles.** `pg_stat_activity.usename` is
   the only check that answers "as whom".
6. **A bucket lock, not the token's scope, is what stops a delete.** R2's
   *Object Read & Write* includes delete, so scoping the token to one bucket
   contains the damage from a compromised VM but does not make the objects
   immutable. The bucket lock does. Do not remove it, and remember it also
   outranks the lifecycle rule: nothing expires inside the retention window.
   The lock also means an erasure request against backup contents waits for the
   window to pass.
7. **A corpus load runs from an operator machine, never in the container.** The
   image holds neither the CCM output directory nor
   `data/elaws_consolidations.json`. Point `DATABASE_URL` at the target first —
   with your usual environment the command reloads your development database and
   reports success.
8. **Corpus reproducibility is a dependency.** Keep
   `CodeChronicleMapping/data/outputs` durably stored, or it becomes the single
   point of failure for the part of the database the backup deliberately skips.
9. **A card is a memory of prod, not prod.** This card claimed a migration was
   pending for a day after it had applied, and held A4 back for no reason. Read
   `django_migrations` before you trust a sentence here.

---

# The steps, as run

Kept verbatim. A step that reads as an instruction is what makes it
repeatable — for a second deployment, or for reading what was actually
done rather than a summary of it.

## Part A — how the owner secret was made

The rest of Part A is dashboard and SQL work, recorded above and in
`docs/security/db-roles.sql`. The A3 rollback is under "How to undo it".

### A4's owner secret

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

> ⚠️ **This is how it was done, not how to do it again.** `database_url`
> version 1 is destroyed. To recreate the secret now, take the string from
> `database_url_owner` itself, or rebuild it from the Neon console using the
> **direct** host.

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
bucket, and the B3 lifecycle rule does not protect them either — it deletes as
well. The B3 bucket lock is what closes this.

A Wrangler route exists (`npx wrangler login`, then
`npx wrangler r2 bucket create codechronicle-backups-prod`) and makes the bucket only.

### B3. Set retention on the bucket — **both rules live 2026-08-09** [DASH]
Cloudflare → R2 → `codechronicle-backups-prod` → Settings → **Object lifecycle rules** →
delete objects older than e.g. 90 days. (Preferred over the command's `--keep` flag.)

Then, in the same Settings panel, a **bucket lock**. This is the part that makes
the backups survive an attacker who owns the VM: a lifecycle rule and a scoped
token both still allow a delete, and a lock does not. Managing a lock needs the
*edit R2 bucket configuration* permission, which the B2 token deliberately lacks.

**Verified 2026-08-09**, with the real backup credential, against two throwaway
objects — one under `db-backups/`, one at the root, so a whole-bucket rule could
be told apart from a prefix-scoped one:

```
CONFIG get_object_lock_configuration: DENIED/ABSENT (AccessDenied)
DELETE db-backups/_locktest-delete-me.txt: REFUSED (ObjectLockedByBucketPolicy)
DELETE _locktest/_locktest-delete-me.txt:  REFUSED (ObjectLockedByBucketPolicy)
```

**Test with throwaway objects, never a real backup.** A true test has to attempt
the delete, and a lock that turns out not to be there would destroy the thing
being protected.

⚠️ **The two test objects cannot be deleted either** — that is the lock working.
They stay until the retention window passes. Anything that picks "the newest
object in the bucket" must filter to the `cc-userdata-` prefix, or it will pick
one of them up.

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
> with their schema and no rows, so `load_edition --all` must run before the site is
> usable. That is by design — see the gotchas above.

### B7. Schedule it (daily) — **DONE on prod 2026-08-09** [PASTE — run on the VM]

Installed and enabled: `cc-backup.timer` next fires 07:02:10Z (the randomized
delay), and `cc-backup.service` was triggered once by hand to prove it —
`Result=success`, `ExecMainStatus=0`, and the journal shows the full pipeline
through the upload. **Run the unit once after you install a timer.** An
untested schedule is a schedule that fails at 07:00, to nobody.

The units are also in `CodeChronicleTerraform/modules/compute/startup.sh`
(commit `28d3adf`, pushed), so a rebuild keeps them. No `terraform apply` was
needed — the units were already live on the VM.

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

⚠️ **A unit written by hand into `/etc` is drift.** `startup.sh` in
`CodeChronicleTerraform/modules/compute/` rebuilds this VM, the same way it owns
`nginx.conf`. The two units are there now; if you change them on the VM, change
them there too, or a rebuild silently loses the schedule — and a lost schedule
is the exact failure B9 exists to catch.

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

### B8. Periodically test a restore — **DONE 2026-08-09** [PASTE]

Ran end to end and passed. Stamped in `docs/security/disaster-recovery-plan.md`
§6, and §3b there now carries the corrected procedure. What it proved, in order:
the object in the bucket downloads; the age private key decrypts it;
`pg_restore` prints nothing and makes **194 of 194** foreign keys across 105
tables; the user data matches production exactly; the corpus reload rebuilds
every corpus table to production's counts; and a search answers **158 matches**.

Start from the **object in the bucket**, not from a dump left on disk. A drill
that reads a local file proves the encryption and skips the two links a real
disaster tests first: the upload, and the bucket.

Decrypt with the **private** key, on your own machine. It must not reach the VM.

```powershell
age -d -i backup-key.txt -o restored.dump <downloaded>.dump.age
pg_restore --no-owner --no-privileges -d "<scratch_or_branch_connection_string>" restored.dump
```

⚠️ **Point `DATABASE_URL` at the restored instance before the next command.** It
runs on your machine and writes to whatever `DATABASE_URL` names, so your usual
environment reloads your **development** database and leaves the restore empty —
and every command still reports success.

```powershell
$env:DATABASE_URL = "<scratch_or_branch_connection_string>"
# --all loads every edition oldest first, seeds the province-to-code row, and
# restores the consolidation date ranges.  Without --all you load one edition.
python manage.py load_edition --source ../CodeChronicleMapping/data/outputs --all
```

The corpus reload is part of the restore, not an extra: the corpus tables are
excluded from the backup, so they come back with their schema and no rows.

**A restore that prints nothing is the pass mark.** `pg_restore` reports a failed
constraint as a warning and still exits 0, so an exit code proves nothing. Count the
foreign keys instead — the restored database must have **194**:
```sql
SELECT count(*) FROM pg_constraint WHERE contype = 'f';
```

**Then run a search.** It is the only check that fails when the `province_codes`
row is missing, and a missing row makes the site read as an empty corpus rather
than a broken one.

### B10. Test the host's own recovery — **DONE 2026-08-09** [PASTE]

B8 tests the backup we make. This tests the one the **host** keeps, which is a
different mechanism and was never exercised. It is the first 5a row in
`docs/security/disaster-recovery-plan.md` §6.

Neon can branch from history at a timestamp. `neonctl` is needed: the Neon MCP's
`create_branch` takes a `parentId` but **no timestamp**, so it cannot do
point-in-time at all.

```bash
npx neonctl auth   # the stored credential expires; this opens a browser
IN=$(date -u -d '-5 hours 30 minutes' +"%Y-%m-%dT%H:%M:%SZ")
npx neonctl branches create --project-id restless-cell-46809886 \
    --name pitr-drill-inside --parent "$IN"
# prove it landed where you asked, then delete it:
npx neonctl branches list --project-id restless-cell-46809886 --output json
npx neonctl branches delete <branch-id> --project-id restless-cell-46809886
```

**Results.** A queryable branch 5 h 30 m back in **3 seconds**, holding 6 users,
113 searches and 12 sessions — and **11,365 corpus versions**. That last figure
is the point of running this at all: PITR carries the corpus, so it needs no
`load_edition`, where a B8 restore needs ten minutes of one. Inside six hours
PITR is the better tool; outside them it is no tool at all, and the B8 backup is
the only one.

**The window is real, and the host says so.** A request 8 h back was refused:
`timestamp is before retention window; retention_window:"6h0m0s"`. Read the RPO
off that error, never off a config value written down months ago.

⚠️ **`neonctl` accepts an unknown flag in silence.** The first attempt here used
`--parent-timestamp`, which does not exist. The branch was created from **now**,
the success table printed, and it read as a working point-in-time restore of a
database that was simply live. The flag is `--parent`.

**So prove the branch is where you asked, with a marker that cannot exist yet.**
Read `parent_timestamp` back from `branches list`, then check a table a later
migration added. Here `backup_runs` was **absent** (migration `0053` applied at
06:09Z), there were 104 tables not 105, the newest migration was 2026-08-07, and
the consolidation count was 54 rather than 66 because OBC 1997's twelve rows
landed at 08:0xZ. Four independent markers, all agreeing on the requested time.

⚠️ **A branch costs storage and compute until it is deleted.** Both drill
branches were removed the same day.

---

## Deliberately not done

- **The Neon IP allow-list**, in `tasks/maybe/neon-ip-allow-list.md`.

The two other items that sat here are done: the bucket lock (B3) and the PITR
drill (B10), both on 2026-08-09.
