# Security hardening rollout — operator checklist

**Status: NOT STARTED. One-time rollout.** Implements the off-host backups in
`docs/security/disaster-recovery-plan.md` §7 and the DB lockdown in
`docs/security/breach-response-plan.md` §8. The standing procedures live in those
two (permanent) docs; this file is the finite set of setup actions to get there —
**move it to `tasks/complete/` once A1–B8 are done.** The supporting code
(`core/auth_audit.py`, `manage.py backup_userdata`, `docs/security/db-roles.sql`)
already exists and is tested.

> Everything **you** need to do. Steps are paste-ready. Legend: **[PASTE]** = run
> as-is (fill the obvious blanks); **[DASH]** = dashboard/UI action, no CLI;
> **🤖** = Claude can pre-validate on a throwaway Neon branch first, so you apply
> known-good values.

## Checklist (detail for each below)
- [ ] **A1** Create `cc_app` / `cc_ro` roles
- [ ] **A2** Build the cc_app + owner connection strings
- [ ] **A3** Point the app at `cc_app` (rotate secret + restart) — *rollback-risky*
- [ ] **A4** Switch deploy `migrate` to the owner role
- [ ] **A5** IP allow-list (needs paid Neon)
- [ ] **A6** Confirm TLS
- [ ] **B1** Generate age keypair — private key offline
- [ ] **B2** Create R2 backups bucket + scoped token
- [ ] **B3** Bucket lifecycle/retention
- [ ] **B4** Add backup config to the secret bundle
- [ ] **B5** Add `pg_dump`+`age` to the image
- [ ] **B6** Smoke-test + first full backup
- [ ] **B7** Schedule the cron
- [ ] **B8** Test a restore (and stamp recovery §6)

**Fixed values for this project (so you don't hunt for them):**

| Thing | Value |
|---|---|
| Neon project | `codechroniclenet` · id `restless-cell-46809886` · db `neondb` · PG 17 |
| Neon org | `org-bold-unit-61886633` (iskander.lee@gmail.com) |
| GCP | project `codechronicle-487104` · VM `codechroniclenet-vm` · zone `us-central1-a` · container `codechroniclenet-web` |
| Secrets | Secret Manager: `app_runtime_secrets` (bundle), `database_url` |
| PITR window | **6 hours** (`history_retention_seconds=21600`) — the reason for Part B |

---

## Part A — Database access lockdown (§8)

### A1. Create least-privilege roles 🤖 [PASTE/DASH]
Open the **Neon SQL Editor** (console.neon.tech → project → SQL Editor), connected to
`neondb` as the **owner** role. Edit `docs/security/db-roles.sql` to set two strong
passwords, then paste its contents and run. (Or, with the owner connection string:)
```powershell
psql "<OWNER_CONNECTION_STRING>" -v app_pw='<STRONG1>' -v ro_pw='<STRONG2>' -f docs/security/db-roles.sql
```
Run the verify queries at the bottom of that file — `cc_app` must have INSERT but not
TRUNCATE; `cc_ro` must have SELECT but not UPDATE.

### A2. Build the two connection strings [PASTE]
Take your current `database_url` and swap in the new roles (keep the same host + db +
`sslmode=require`):
```
# runtime (the app) — least privilege:
postgresql://cc_app:<STRONG1>@<HOST>/neondb?sslmode=require
# migrate-only (deploys) — the owner role you already have:
postgresql://<OWNER>:<OWNER_PW>@<HOST>/neondb?sslmode=require
```
`<HOST>` is the host already in your current `database_url` (the `…us-east-1.aws.neon.tech` pooled endpoint).

### A3. Point the running app at `cc_app` [PASTE]
Rotate the `database_url` secret to the **cc_app** string, then restart. No trailing
newline (a stray `\n` breaks parsing):
```powershell
$tmp = "$env:TEMP\dburl.txt"
[IO.File]::WriteAllText($tmp, "postgresql://cc_app:<STRONG1>@<HOST>/neondb?sslmode=require")
gcloud secrets versions add database_url --data-file=$tmp --project=codechronicle-487104
Remove-Item $tmp
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```
**Verify:** load the site, run a search, log in. If anything 500s on DB permissions,
roll back by re-adding the previous `database_url` version (Secret Manager keeps it) and
restart — then check which grant `cc_app` is missing.

### A4. Run migrations as the owner from now on [PASTE]
The app role can't run DDL, so `migrate` needs the owner string. `production.py` lets an
env var override the secret, so override it just for the migrate command:
```powershell
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker exec -e DATABASE_URL='postgresql://<OWNER>:<OWNER_PW>@<HOST>/neondb?sslmode=require' codechroniclenet-web python manage.py migrate"
```
(Fold this into your deploy routine. Day-to-day requests keep using the `cc_app` secret.)

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

### A6. Confirm TLS [PASTE] — should already pass
```powershell
# expects: ssl=on
psql "postgresql://cc_app:<STRONG1>@<HOST>/neondb?sslmode=require" -c "SHOW ssl;"
```

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

### B5. Put `pg_dump` + `age` in the container image [PASTE — Dockerfile]
The backup command runs inside `codechroniclenet-web`, so the image needs both binaries.
Add to the Dockerfile and redeploy:
```dockerfile
# postgresql-client must be v17 to match the server; add Bookworm's pgdg repo if needed.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-17 age \
 && rm -rf /var/lib/apt/lists/*
```

### B6. Smoke-test the pipeline, then a full run [PASTE]
```powershell
# local-only (no upload) — proves pg_dump + age work end to end:
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker exec codechroniclenet-web python manage.py backup_userdata --dest /tmp"
# full run — dump → encrypt → upload to R2:
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker exec codechroniclenet-web python manage.py backup_userdata"
```
Confirm the object appears under `db-backups/` in the bucket.

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
```

---

## Sequencing & gotchas

1. **Do Part A before B4/B6** only if you want backups to run as `cc_app`; otherwise order
   is independent. A1→A3 is the high-value core; A5 waits on the paid tier.
2. **A3 is the one with rollback risk** — if `cc_app` is missing a grant, the app errors
   on DB writes. The previous `database_url` version is retained in Secret Manager; re-add
   it and restart to roll back instantly.
3. **The age private key (B1) is the only irreplaceable new secret.** Lose it → every
   backup is unreadable. It must never touch the repo, the VM, or any chat/transcript.
4. **`postgresql-client` major version must match the server (17).** A mismatched
   `pg_dump` refuses to dump a newer server.
5. **Corpus reproducibility is now a dependency** (recovery §7): keep
   `CodeChronicleMapping/data/outputs` durably stored, or it becomes the new single point
   of failure for the part of the DB the backup deliberately skips.
6. **On completion, before archiving to `tasks/complete/`:** graduate the two *recurring*
   facts this rollout introduces into the permanent docs, so they survive the archive —
   the migrate-as-owner deploy step (A4) → `docs/edit-prod-settings.md`, and the
   restore-from-encrypted-backup procedure (B8) is already in the recovery plan §7.

> 🤖 **What Claude can pre-validate on a throwaway branch** before you touch prod:
> A1 (run `db-roles.sql`, confirm cc_app=CRUD/no-DDL, cc_ro=read-only, default-privileges
> cover a new table) and a real PITR restore drill (recovery §5a) to stamp the §6 log.
> Ask and it'll create the branch, validate, and (with your OK) delete it.
