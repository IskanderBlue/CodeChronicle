# Security hardening rollout — operator checklist

**Status: IN PROGRESS (4 of 14 done — A1, A4, A6, B5). One-time rollout.**
Implements the off-host backups in `docs/security/disaster-recovery-plan.md` §7 and
the DB lockdown in `docs/security/breach-response-plan.md` §8. The standing procedures
live in those two (permanent) docs; this file is the finite set of setup actions to
get there — **move it to `tasks/complete/` once A1–B8 are done.** The supporting code
(`core/auth_audit.py`, `manage.py backup_userdata`, `docs/security/db-roles.sql`)
already exists and is tested.

## Where this stands, 2026-08-07

**The next action is a deploy, not a step on this list.** A3 and B6 both wait on it,
and the repository holds work that must land first: the `Dockerfile` change (B5), the
`CORPUS_TABLES` fix, and migration `0052`.

| | |
|---|---|
| **Done** | A1 (roles live on prod), A4 (procedure written), A6 (TLS confirmed), B5 (in the `Dockerfile`) |
| **Waiting on a deploy** | A3, B6 |
| **Waiting on you** | B1 (age keypair), B2/B3 (Cloudflare), B4 (needs B1+B2), A5 (paid Neon tier) |
| **Rehearsed, not run for real** | B6 and B8's mechanics — see the notes under each |

**Three defects were found by rehearsing rather than by reading.** Each is written up
at the step it belongs to; together they are the reason this card is worth finishing
carefully:

1. **The card and `db-roles.sql` named the wrong database** (`neondb`, which is empty).
   A grant aimed at it succeeds and does nothing. *(gotcha 2)*
2. **A3 without A4 is an outage, not a rollback.** `migrate` runs at every container
   start, so the next pending migration crash-loops the container. *(A3, A4)*
3. **The backup could not restore its own foreign keys.** Four kept tables referenced
   excluded ones; `pg_restore` reported the failures as warnings and exited 0.
   *(B6, and `disaster-recovery-plan.md` §7)*

A theme worth carrying: in all three, the failing thing **reported success**. Check by
counting, not by exit codes.

> Everything **you** need to do. Steps are paste-ready. Legend: **[PASTE]** = run
> as-is (fill the obvious blanks); **[DASH]** = dashboard/UI action, no CLI;
> **🤖** = Claude can pre-validate on a throwaway Neon branch first, so you apply
> known-good values.

## Checklist (detail for each below)
- [x] **A1** Create `cc_app` / `cc_ro` roles — *done on prod 2026-08-07; verified across all 104 tables*
- [ ] **A2** Build the cc_app + owner connection strings
- [ ] **A3** Point the app at `cc_app` (rotate secret + restart) — *rollback-risky; **needs A4 and a deploy first***
- [x] **A4** Switch deploy `migrate` to the owner role — *procedure in `docs/edit-prod-settings.md`*
- [ ] **A5** IP allow-list (needs paid Neon)
- [x] **A6** Confirm TLS — *done: the server refuses `sslmode=disable`*
- [ ] **B1** Generate age keypair — private key offline
- [ ] **B2** Create R2 backups bucket + scoped token
- [ ] **B3** Bucket lifecycle/retention
- [ ] **B4** Add backup config to the secret bundle
- [x] **B5** Add `pg_dump`+`age` to the image — *in the Dockerfile; lands with the next deploy*
- [ ] **B6** Smoke-test + first full backup
- [ ] **B7** Schedule the cron
- [ ] **B8** Test a restore (and stamp recovery §6)

**Fixed values for this project (so you don't hunt for them):**

| Thing | Value |
|---|---|
| Neon project | `codechroniclenet` · id `restless-cell-46809886` · **db `codechroniclenet`** · PG 17 |
| DB owner role | `codechroniclenet_app` — owns the database and all 104 tables, and is what the app connects as today |
| Neon org | `org-bold-unit-61886633` (iskander.lee@gmail.com) |
| GCP | project `codechronicle-487104` · VM `codechroniclenet-vm` · zone `us-central1-a` · container `codechroniclenet-web` |
| Secrets | Secret Manager: `app_runtime_secrets` (bundle), `database_url` |
| PITR window | **6 hours** (`history_retention_seconds=21600`) — the reason for Part B |

---

## Part A — Database access lockdown (§8)

### A1. Create least-privilege roles 🤖 [PASTE/DASH] — **validated 2026-08-07**
Open the **Neon SQL Editor** (console.neon.tech → project → SQL Editor), connected to
**`codechroniclenet`** as **`codechroniclenet_app`**. Edit `docs/security/db-roles.sql`
to set two strong passwords, then paste its contents and run. (Or, with the owner
connection string:)
```powershell
psql "<OWNER_CONNECTION_STRING>" -v app_pw='<STRONG1>' -v ro_pw='<STRONG2>' -f docs/security/db-roles.sql
```
Run the verify queries at the bottom of that file — `cc_app` must have INSERT but not
TRUNCATE; `cc_ro` must have SELECT but not UPDATE.

> **Done on prod, 2026-08-07.** Both roles exist on `codechroniclenet`, and the verify
> block returns all sixteen expected values. Checked across the whole schema rather
> than one table: of 104 tables, `cc_app` is missing INSERT on **0** and `cc_ro` can
> UPDATE **0**; `cc_app` has USAGE on all 100 sequences. Neither role inherits
> anything. Nothing points at these roles yet — that is A3.
>
> ⚠️ **The two halves must both run.** The `CREATE ROLE` statements ran first and the
> grants some minutes later, and in between prod held two roles that could log in and
> read nothing. That state looks finished and is not: it passes "the roles exist" and
> fails every query. If A3 runs against it the site returns 500 on every page. Run the
> file whole, then run the verify block — the roles existing is not the test.
>
> **Drill result** (before the prod run). The whole script ran on `drill-db-roles-a1`, a branch of prod.
> Both roles came out right: `cc_app` = SELECT/INSERT/UPDATE/DELETE + sequence USAGE,
> no TRUNCATE, no CREATE on `public`; `cc_ro` = SELECT only. A table created afterwards
> was granted automatically, so the default privileges cover a future migration.
> Neither role inherits `neon_superuser`. `cc_app` logs in on **both** the direct and
> the pooled endpoint, and the app's own write paths — session, `SearchHistory`,
> `EngagementEvent` — all succeed through it while DDL is refused. So A3's rollback
> risk is now measured rather than assumed.

### A2. Build the two connection strings [PASTE]
Take your current `database_url` and swap in the new roles (keep the same host + db +
`sslmode=require`):
```
# runtime (the app) — least privilege:
postgresql://cc_app:<STRONG1>@<HOST>/codechroniclenet?sslmode=require
# migrate-only (deploys) — the owner role you already have:
postgresql://<OWNER>:<OWNER_PW>@<HOST>/codechroniclenet?sslmode=require
```
`<HOST>` is the host already in your current `database_url` — the pooled endpoint of the
`main` branch:

```
ep-shiny-boat-aivobvoc-pooler.c-4.us-east-1.aws.neon.tech
```

`cc_app` is confirmed to authenticate on the pooled host as well as the direct one, so
keeping the pooler is safe. Only the two passwords are missing from these strings, and
they are yours — do not paste them into a chat or a transcript.

### A3. Point the running app at `cc_app` [PASTE]

> ⚠️ **Do A4 first, and deploy the pending commits first.** `scripts/entrypoint.sh`
> runs `migrate --noinput` under `set -e` at **every container start**, not only at a
> deploy. Once `database_url` is `cc_app`, a start with a migration still pending stops
> before gunicorn and Docker restarts it into the same failure — a crash loop, not a
> degraded page. Migration `0052` is pending on prod right now, so doing A3 today and
> deploying tomorrow takes the site down.
>
> Measured on a branch on 2026-08-07, running the real entrypoint command as `cc_app`:
> with `0052` pending, `migrate` exits 1 with `must be owner of table edition_requests`;
> with nothing pending, it exits 0 and the site starts. (Migrations `0050` and `0051`
> applied without a fault — they alter a field's choices and write no DDL. Do not read
> that as safety; you cannot tell the two kinds apart from the deploy.)

Rotate the `database_url` secret to the **cc_app** string, then restart. No trailing
newline (a stray `\n` breaks parsing):
```powershell
$tmp = "$env:TEMP\dburl.txt"
[IO.File]::WriteAllText($tmp, "postgresql://cc_app:<STRONG1>@<HOST>/codechroniclenet?sslmode=require")
gcloud secrets versions add database_url --data-file=$tmp --project=codechronicle-487104
Remove-Item $tmp
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```
**Verify:** load the site, run a search, log in. If anything 500s on DB permissions,
roll back by re-adding the previous `database_url` version (Secret Manager keeps it) and
restart — then check which grant `cc_app` is missing.

### A4. Run migrations as the owner from now on — **written up; do it before A3**
The app role cannot run DDL, so `migrate` needs the owner string. `production.py` lets
an env var override the secret, so override it for the migrate command only.

**The procedure now lives in `docs/edit-prod-settings.md`**, under "Migrations, after
the app runs as `cc_app`" — it is a standing rule, not a one-time action, so it belongs
in a permanent doc rather than in a card that gets archived. Gotcha 7 asked for that
graduation on completion; it happened early, because A3 is unsafe without it.

Two corrections to the command this card used to give here:

- **`docker exec` into the running container is too late.** That container has already
  run the entrypoint's `migrate` and already failed. Run the migration from the new
  image with `docker run --rm`, **before** the new container starts.
- **Run it from the new image, not the running one.** The migration ships with the new
  code, so the old image does not contain it.

Day-to-day requests keep using the `cc_app` secret.

### A5. Restrict where the DB accepts connections [DASH] — needs paid Neon
Currently `allowed_ips = []` (open from anywhere). Find the VM's egress IP, then allow
only it (plus any IP you run `psql`/console from):
```powershell
# the VM's external/egress IP (if it routes via Cloud NAT, take the NAT IP from the router instead):
gcloud compute instances describe codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --format="get(networkInterfaces[0].accessConfigs[0].natIP)"
```
Then **[DASH]** Neon console → Project → Settings → **Network Security / IP Allow** → add
that IP. ⚠️ Include your own admin IP too, or you'll lock yourself out of direct SQL.
This is a **paid-tier** feature — lands together with the deferred DB audit logging
(breach plan §6 "Planned remediation").

### A6. Confirm TLS [PASTE] — **already confirmed 2026-08-07**
⚠️ **Do not check this with `SHOW ssl`.** Neon terminates TLS at its proxy, so the
compute reports `ssl = off` on a connection that is encrypted. The drill saw exactly
that: `ssl_in_use = True` on the client and `SHOW ssl = off` on the same connection.
Reading `off` as a failure sends you hunting a problem that is not there.

Ask the server instead, by trying to connect **without** TLS. It must refuse:
```powershell
# expects: "connection is insecure (try using sslmode=require)"
psql "postgresql://cc_app:<STRONG1>@<HOST>/codechroniclenet?sslmode=disable" -c "SELECT 1;"
```
A refusal proves the property that matters — that an unencrypted connection is not
available to anybody — which a positive `SHOW ssl` would not have proved anyway.

---

## Part B — Off-host encrypted backups (§7)

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

### B5. Put `pg_dump` + `age` in the container image — **done in the repo; needs a deploy**
The backup command runs inside `codechroniclenet-web`, so the image needs both binaries.
`postgresql-client-17` and `age` are now in the `Dockerfile`'s existing `apt-get` layer.

No PGDG repository is needed: the base image is Debian **Trixie**, not Bookworm, and
carries `postgresql-client-17` (17.10) and `age` (1.2.1) directly. Verified by running
the exact apt line in `python:3.12-slim`. The version is pinned to 17 rather than the
`postgresql-client` metapackage, because `pg_dump` must match the server's major
version and a base-image change should not be able to move it quietly.

**This lands with the next deploy**, so B6 waits on that push.

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
> before the site is usable. That is by design — see gotcha 6.

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

## Sequencing & gotchas

1. **Order inside Part A is now fixed: A1 → A4 → deploy → A3.** A4 used to read as
   tidy-up after A3. It is a precondition: the entrypoint runs `migrate` at every
   container start, so A3 without A4 turns the next pending migration into a crash
   loop. B4/B6 are independent of Part A unless you want the backup to run as `cc_app`.
   A5 waits on the paid tier.
2. **`neondb` is the wrong database and fails silently.** The project carries both
   `neondb` (Neon's empty default) and `codechroniclenet` (the 104 real tables).
   `GRANT … ON DATABASE neondb` succeeds, grants nothing this product uses, and leaves
   you with roles that look created and cannot read a row. Earlier drafts of this card
   and of `db-roles.sql` said `neondb` throughout; both are corrected.
3. **A3 is the one with rollback risk** — if `cc_app` is missing a grant, the app errors
   on DB writes. The previous `database_url` version is retained in Secret Manager; re-add
   it and restart to roll back instantly.
4. **The age private key (B1) is the only irreplaceable new secret.** Lose it → every
   backup is unreadable. It must never touch the repo, the VM, or any chat/transcript.
5. **`postgresql-client` major version must match the server (17).** A mismatched
   `pg_dump` refuses to dump a newer server.
6. **Corpus reproducibility is now a dependency** (recovery §7): keep
   `CodeChronicleMapping/data/outputs` durably stored, or it becomes the new single point
   of failure for the part of the DB the backup deliberately skips.
7. ~~**On completion**~~ — **done early.** The two *recurring* facts this rollout
   introduces now live in the permanent docs, so they survive the archive: the
   migrate-as-owner step (A4) is in `docs/edit-prod-settings.md`, and the
   restore-from-encrypted-backup procedure (B8) is already in the recovery plan §7.
   A4 moved early because A3 is unsafe without it.
8. **`corpus reproducibility` now includes `data/elaws_consolidations.json`**, not only
   the CCM outputs. The `consolidations` table is excluded from the backup, so that
   committed file is what rebuilds it. It is in this repository, so it is already as
   durable as the code.

> 🤖 **What Claude pre-validated on a throwaway branch** (`drill-db-roles-a1`, expired
> 2026-08-08): A1's grants, `cc_app` on both endpoints, the app's own write paths as
> `cc_app`, the entrypoint's `migrate` as `cc_app`, and a full `pg_dump` → `pg_restore`
> cycle. That work is folded into the steps above.
>
> **Still available, and not yet done:** a real PITR restore drill (recovery §5a) to add
> a second row to the §6 log. The 2026-08-07 row covers 5b (the logical backup) only, so
> the host's own recovery path is still untested. Ask, and it will create the branch,
> run the drill, and — with your OK — delete the branch.
