# Disaster Recovery & Backup Plan

> **Status:** active operational procedure.
> **Owner:** Robert Lee (Founder) — rob@codechronicle.ca · 226-700-3295.
> **Scope:** how CodeChronicle's data is backed up, and the tested steps to
> restore service after data loss, corruption, or a host failure.
> **Last reviewed:** _(stamp when you read/revise this)_

A recovery plan only counts as "tested" once you have actually restored from a
backup and recorded it (§5–6). Until the log in §6 has a real row, treat recovery
as *designed* but *unverified*.

---

## 1. Systems & data inventory

| System | What it holds | Criticality | Reproducible from elsewhere? |
|---|---|---|---|
| **PostgreSQL (prod `DATABASE_URL`)** | All user data + the building-code corpus | **Critical** — the one irreplaceable store | Corpus: yes (re-loadable from CCM). **User data: NO — this is the only copy.** |
| **GCP Secret Manager** (`app_runtime_secrets`, `database_url`, `django_secret_key`, `anthropic_api_key`) | All runtime secrets & config | **Critical** | No — but versioned by Secret Manager |
| **Cloudflare R2** (`codechronicle-assets-prod`) | Building-code images | Important (availability) | **Yes** — re-syncable from CCM via `sync_images` |
| **GCE VM** `codechroniclenet-vm` + container `codechroniclenet-web` | Compute (stateless) | Important | Yes — rebuildable from image + Secret Manager |
| **GitHub repo** | Application code | Important | Yes — local clones + GitHub |
| **Stripe** | Subscriptions, card data | Critical (billing) | Held by Stripe; their durability, not ours |

**The headline:** only the **PostgreSQL database** contains data we cannot rebuild
from somewhere else. The corpus inside it is re-loadable from CodeChronicleMapping
(`load_edition`); the **user data is not**. Everything in this plan centres on that
database.

---

## 2. Backup reality (per system)

- **PostgreSQL** — the managed Postgres host (Neon) provides automated continuous
  backup with point-in-time restore (PITR) within its **retention window**.
  ⚠️ **The retention window is your real RPO ceiling.** Measured on this project
  (2026-06-13): the window is **6 hours** (`history_retention_seconds = 21600`) —
  tighter than the ~24 h rule of thumb. Corruption or a malicious delete discovered
  *more than 6 hours later* is unrecoverable via PITR. → See §7: add an independent
  logical backup so recovery doesn't depend solely on this short window.
- **Secret Manager** — every `versions add` keeps prior versions; you can access any
  past version, so a bad edit is reversible. Effectively self-backing.
- **Cloudflare R2** — not backed up as user data because it *is* not user data;
  reproducible by re-running `manage.py sync_images --backend r2` against the CCM
  source. Treat R2 loss as a re-publish task, not a data-loss event.
- **Code** — GitHub remote + every local clone.

---

## 3. Recovery procedures (by scenario)

### 3a. Database corruption / accidental data loss (PITR)
1. Identify the last-good timestamp (before the corrupting event).
2. In the database host console, **restore to that point in time** (Neon: create a
   branch/restore from history at the chosen timestamp). Restore into a **new**
   branch/endpoint first — never overwrite the live one blind.
3. Verify the restored data (row counts for `users`, `search_history`; a known
   account exists; corpus intact).
4. Repoint production at the restored endpoint: update `database_url` in Secret
   Manager, then restart the container (§3d).
5. Record the event in §6 and in the breach register if personal data was involved.

### 3b. Total database loss (host gone) — restore from logical backup
*(Requires the §7 logical backup to exist.)*
1. Provision a fresh Postgres instance.
2. `pg_restore` (or `psql`) the latest dump into it.
3. Re-load the corpus if the dump predates the latest `load_edition`
   (`python manage.py load_edition --source ../CodeChronicleMapping/data/outputs`).
4. Update `database_url` in Secret Manager; restart (§3d); verify.

### 3c. Lost secrets / bad secret edit
1. In Secret Manager, access the previous good **version** of the affected secret
   (or `app_runtime_secrets` bundle) and re-add it as the latest.
2. Restart the container (§3d).
- If `database_url` itself is lost: retrieve the connection string from the database
  host's dashboard and re-add the secret.

### 3d. Compute/container failure — rebuild the web tier (stateless)
The VM and container hold no unique state; recovery is redeploy + secrets.
```
# Restart the existing container:
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a \
  --project=codechronicle-487104 --tunnel-through-iap \
  --command="sudo docker restart codechroniclenet-web"
```
If the VM itself is gone: recreate the VM, pull the app image, supply the
container env (`GCP_PROJECT_ID`, `DJANGO_SETTINGS_MODULE`, `ALLOWED_HOSTS`); the app
reads everything else from Secret Manager at boot.

### 3e. Asset (R2) loss
Re-publish from the CCM source — no user data at risk:
```
python manage.py sync_images --backend r2
```

---

## 4. Recovery targets

| Metric | Target | Reality today |
|---|---|---|
| **RTO** (time to restore service) | < 4 hours | Achievable: stateless compute + managed DB restore |
| **RPO** (max acceptable data loss) | < 24 hours | **Bounded by the DB host's PITR window — currently only 6 h** on this project; §7's off-host dump narrows it |

These are starting targets for a solo, pre-scale operation — tighten as the user base
grows.

---

## 5. Restore-test procedure (the drill — run this to make the plan "tested")

Run at least the database restore (5a) **before** relying on this plan, then on a
recurring basis (quarterly is reasonable at this stage). A drill must use a **real
backup restored to a throwaway target** — never test against production.

**5a. Database PITR drill:**
1. Pick a point-in-time within the retention window.
2. Restore it to a **new** branch/endpoint (not production).
3. Connect and verify: `users` and `search_history` row counts look right; a known
   account is present; corpus tables are populated.
4. Note how long it took (RTO) and how far back the window reaches (RPO).
5. Tear down the throwaway endpoint.
6. **Record the result in §6.**

**5b. Logical-backup drill (once §7 exists):** restore the latest dump into a local
or scratch Postgres and run `python manage.py migrate --check` + a smoke query.

**5c. Secret-rollback drill:** access a prior version of a non-critical secret to
confirm the rollback path works.

---

## 6. Restore-test log

> Stamp a row each time you actually run a drill (§5). **Do not pre-fill this** — an
> empty log honestly says "not yet tested," which is the truth until a drill runs.

| Date | Scenario (5a/5b/5c) | Restored from | Outcome | RTO observed | RPO (window reach) | Notes |
|---|---|---|---|---|---|---|
| _(none yet — run §5a and record it here)_ | | | | | | |

---

## 7. Recommended improvement — independent logical backup (irreproducible data only)

Right now, database recovery depends entirely on the **host's** PITR window. A single
managed backup mechanism is one account-suspension or one expired-window away from
being useless. Add a second, host-independent backup.

**Back up only the irreproducible data, not the whole database.** The corpus tables
(provisions, versions, clauses, tables, mappings — the bulk of the DB) are fully
re-loadable from CCM via `load_edition`, so dumping them is wasted storage and
bandwidth on every run. The data we *cannot* rebuild is the user/operational data:
`users`, `search_history`, `engagement_events`, `auth_events`, the LLM-cache tables,
Django auth/admin/session plumbing, and the dj-stripe mirror. Those tables form a
**clean FK island** — none of them reference the corpus tables (e.g.
`EngagementEvent.object_id` is a loose integer by design), so they dump and restore
independently of the corpus.

Use `--exclude-table-data` on the corpus tables: it keeps their *schema* (so a
restore recreates the structure) but skips their *rows*. This is safe-by-default —
any **new** table you add later is included in the backup automatically; only the
known-reproducible corpus tables are skipped.

```powershell
$DBURL = "<prod DATABASE_URL>"
# Reproducible-from-CCM corpus tables — keep schema, skip the bulky data:
$corpus = @(
  "codes","code_editions","province_codes",
  "regulations","regulation_clauses","regulation_assets",
  "code_edition_provisions","code_edition_provision_versions",
  "code_edition_provision_version_clauses","provision_version_tables",
  "provision_mappings","provision_dispositions","edition_transitions","corpus_currency"
)
$ex = $corpus | ForEach-Object { "--exclude-table-data=public.$_" }
pg_dump $DBURL @ex -Fc -f "cc-userdata-$(Get-Date -Format yyyyMMdd).dump"
```

Checklist:
- [ ] Schedule this dump (daily or weekly).
- [ ] Store it **off the database host** — an R2 bucket or other cloud storage — with
      sensible retention (e.g. 30 daily + 12 monthly).
- [ ] **Encrypt at rest** — this dump is now *concentrated* personal data (all the PII,
      none of the public corpus diluting it), so treat it at least as carefully as the DB.
- [ ] Add the restore-from-dump path to the §5b drill rotation.

**Restore from this dump:** provision a fresh Postgres → `pg_restore` the dump
(recreates all tables + the user data, and preserves `django_migrations` history) →
re-run `python manage.py load_edition --source ../CodeChronicleMapping/data/outputs`
to refill the corpus → repoint `database_url` and restart (§3d).

> **Dependency this introduces:** because the corpus is *not* in the dump, full
> recovery now relies on the **CCM source outputs still existing**. Make sure
> `CodeChronicleMapping/data/outputs` is itself durably stored (its own repo/backup) —
> otherwise you've protected the user data but made the corpus the new single point of
> failure.

This converts the plan from "trust the host's window" to "we hold our own copy,"
narrows RPO below the host's retention limit, keeps the backup small, and makes the
insurance/compliance answer "mission-critical data is backed up off-site"
unambiguously true.
