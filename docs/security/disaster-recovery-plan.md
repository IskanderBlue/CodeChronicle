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
- **Cloudflare R2, the assets bucket** — not backed up as user data because it
  *is* not user data; reproducible by re-running `manage.py sync_images --backend r2`
  against the CCM source. Treat its loss as a re-publish task, not a data-loss event.
- **Cloudflare R2, the backups bucket** — `codechronicle-backups-prod` holds the
  §7 dumps, encrypted to an age key whose private half is offline. A **bucket
  lock** makes the objects undeletable for the retention window, including by
  the credential that writes them; a 90-day lifecycle rule expires them after
  it. The lock outranks the lifecycle rule, so nothing expires early. Verified
  2026-08-09 with the real credential: `ObjectLockedByBucketPolicy`.
  ⚠️ **This also binds us.** An erasure request touching backup contents waits
  for the window to pass; it cannot be served by deleting an object.
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
1. Provision a fresh Postgres instance. The client must be Postgres **17**.
2. Decrypt the dump on your own machine, with the age private key:
   `age -d -i backup-key.txt -o restored.dump <object>.dump.age`.
3. `pg_restore --no-owner --no-privileges -d "<connection string>" restored.dump`.
   A restore that prints nothing is the pass mark. Count the foreign keys — the
   restored database must have **194**.
4. Re-load the corpus. The backup keeps the corpus schema and no rows, so this
   step is part of the restore, not an extra. One command does all of it —
   every edition oldest first, the province-to-code row, and the consolidation
   date ranges.

   > ⚠ **Set `DATABASE_URL` to the restored instance first.** The command runs
   > on your own machine and writes to whatever `DATABASE_URL` names. With your
   > usual environment it reloads your **local development database** and leaves
   > the restored instance with an empty corpus. Both commands then report
   > success, and the mistake only shows at step 5.

   ```
   # PowerShell
   $env:DATABASE_URL = "<restored instance connection string>"
   python manage.py load_edition --source ../CodeChronicleMapping/data/outputs --all
   ```
   The container cannot do this: it holds neither the CCM output directory nor
   `data/elaws_consolidations.json`. Every corpus load runs from an operator
   machine against the target's `DATABASE_URL` — the same way a production load
   runs today.
   > A bare `load_edition` loads **one** edition, the default `OBC_2012.json`.
   > Without `--all` the restored site holds one edition of three and looks
   > complete. The order is not a preference either: loading an edition deletes
   > the cross-edition rows that touch it, and the newer edition's payload is
   > what puts them back.
5. Update `database_url` in Secret Manager; restart (§3d); verify with a search.
   **The search is the check**, not the row counts: it is the only step that
   fails if the `province_codes` row is missing, and a missing row makes the
   site read as an empty corpus rather than a broken one.

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

> ⚠️ **Prove the branch is where you asked, before you believe any count.** The
> flag is `--parent` and it takes a name, an id, a timestamp or an LSN.
> `neonctl` accepts an unknown option **silently**, so a mistyped flag such as
> `--parent-timestamp` branches from *now*, prints a success table, and gives
> you a "restore" of the live database. Read `parent_timestamp` back from
> `branches list`, and check a marker that must not exist yet at the target
> time — a table added by a later migration is the cleanest one.

**5a. Database PITR drill:**
1. Pick a point-in-time within the retention window.
2. Restore it to a **new** branch/endpoint (not production).
3. Connect and verify: `users` and `search_history` row counts look right; a known
   account is present; corpus tables are populated.
4. Note how long it took (RTO) and how far back the window reaches (RPO).
5. Tear down the throwaway endpoint.
6. **Record the result in §6.**

**5b. Logical-backup drill (once §7 exists):** follow §3b against a scratch Postgres
17, and start from the **object in the bucket**, not from a dump the backup left on
disk. A drill that reads a local file proves the encryption and skips the two links a
real disaster tests first: the upload, and the bucket. Count the foreign keys (194),
compare the user-data row counts with production, and finish with a search — the
search is what tells you the corpus reload and the `province_codes` row are both
done.

**5c. Secret-rollback drill:** access a prior version of a non-critical secret to
confirm the rollback path works.

---

## 6. Restore-test log

> Stamp a row each time you actually run a drill (§5). **Do not pre-fill this** — an
> empty log honestly says "not yet tested," which is the truth until a drill runs.

| Date | Scenario (5a/5b/5c) | Restored from | Outcome | RTO observed | RPO (window reach) | Notes |
|---|---|---|---|---|---|---|
| 2026-08-07 | 5b (logical backup) | `pg_dump` of a branch of prod, taken as `cc_app` | **Fail, then pass** | ~4 min, unattended | n/a — the dump was taken during the drill | First run: 5 FK constraints not created, `pg_restore` exited 0 anyway (189 of 194). Cause: 4 kept tables referenced excluded corpus tables. Fixed in `CORPUS_TABLES`; second run silent, 194/194, dump 1.7 MB → 859 KB. User data intact: 6 users, 111 searches, 10,597 events, 11 sessions. Restored into a scratch Postgres 17, not a Neon branch. The corpus reload was **not** exercised. |
| 2026-08-09 | **5a (PITR)** | Neon branch `pitr-drill-inside`, parent timestamp 2026-08-09T03:58:09Z — 5 h 30 m back, near the edge of the window | **Pass** | **3 seconds** to a queryable branch; a real recovery adds the `database_url` repoint and restart (§3d) | **6 hours, confirmed by the server** | The first 5a row. The branch is genuinely at the requested time, checked by markers rather than by the command's exit: `backup_runs` **does not exist** (migration `0053` applied at 06:09Z), 104 tables not 105, newest migration 2026-08-07, and 54 consolidation rows because OBC 1997's twelve were loaded at 08:0xZ. User data intact: 6 users, 113 searches, 12 sessions. Events 16,135 against 17,304 on `main`. **The corpus is fully populated** (11,365 versions) — unlike the logical backup, PITR carries everything, so no `load_edition` is needed. **The boundary is real**: a request 8 h back was refused outright — `timestamp is before retention window; retention_window:"6h0m0s"`. That error is the RPO ceiling stated by the host, not copied from a config value. Trap found: `neonctl` silently ignores an unknown flag, so `--parent-timestamp` branched from *now* and reported success — see the warning above §5a. |
| 2026-08-09 | 5b (logical backup), full | The real R2 object `db-backups/cc-userdata-20260809T061136Z.dump.age`, 990,417 bytes, downloaded from the bucket | **Pass, with two defects found in the written procedure** | ~14 min, attended, and most of that is the corpus reload | 25 min (the backup ran at 06:11Z, the drill at 06:36Z) | End to end for the first time: the bucket copy, the age private key, `pg_restore`, the corpus reload and a search. `pg_restore` printed nothing and made **194 of 194** foreign keys, 105 tables. User data matches production exactly — 6 users, 113 searches, 12 sessions, 9 auth events, 1 backup run; 16,762 events against 16,805 now, which is 25 minutes of traffic. Corpus after the reload matches production on every table (9,744 provisions, 11,365 versions, 42,981 cross-references, 6,218 mappings, 227 dispositions, 1,444 tables). Two defects, both in the procedure and neither in the backup: **(1)** `load_edition` loads **one** edition for each run, so the single command in the old §3b left two editions of three missing; **(2)** `province_codes` is excluded as corpus but no loader recreates it, so search answered **0 matches** until the ON→OBC row was created by hand, and then **158**. §3b now states both. Also found: production holds 54 consolidation rows where a rebuild makes 66, because `load_consolidations` last ran before OBC 1997 was loaded. |

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
Django auth/admin/session plumbing, and the dj-stripe mirror.

Use `--exclude-table-data` on the corpus tables: it keeps their *schema* (so a
restore recreates the structure) but skips their *rows*.

> ⚠️ **The backed-up tables must be an FK island, and that is a rule to enforce, not
> a fact to assume.** An earlier draft of this section stated the island as given. A
> drill on 2026-08-07 disproved it: four kept tables held foreign keys into excluded
> ones, and **five constraints could not be created on restore**. `pg_restore` reported
> each as a *warning* and exited 0, so the restore looked clean and produced a database
> with 189 foreign keys where the original had 194.
>
> A kept table that references an excluded table references rows the restore does not
> have. The rule is one-directional: an excluded table may point at a kept table, since
> it has no rows to dangle. `core/tests/test_backup_userdata.py` now fails the build if
> a kept table gains a foreign key into an excluded one, so the island is checked on
> every commit instead of believed.

This is safe-by-default for *content*: any **new** table you add later is included in
the backup automatically. It is not automatically safe for *shape* — a new table that
references the corpus must join the exclude-list, which is what the guard test tells
you.

**The exclude-list lives in one place: `CORPUS_TABLES` in
`core/management/commands/backup_userdata.py`.** The PowerShell below is illustrative
only. Do not treat it as a second source of truth; a hand-kept copy is how a list like
this drifts out of date.

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
point `DATABASE_URL` at the restored instance and re-run
`python manage.py load_edition --source ../CodeChronicleMapping/data/outputs --all`
to refill the corpus → repoint `database_url` and restart (§3d). §3b step 4 says
why the `DATABASE_URL` is worth stating.

**Check the restore by counting, not by the exit code.** `pg_restore` exits 0 with
failed constraints, so the exit code cannot tell you the restore was faithful:

```sql
SELECT count(*) FROM pg_constraint WHERE contype = 'f';   -- must be 194
```

A silent run with the right count is the pass mark.

> **Dependency this introduces:** because the corpus is *not* in the dump, full
> recovery now relies on the **CCM source outputs still existing**. Make sure
> `CodeChronicleMapping/data/outputs` is itself durably stored (its own repo/backup) —
> otherwise you've protected the user data but made the corpus the new single point of
> failure. `data/elaws_consolidations.json` is the second such input, and it is
> committed to this repository, so it is already as durable as the code.

This converts the plan from "trust the host's window" to "we hold our own copy,"
narrows RPO below the host's retention limit, keeps the backup small, and makes the
insurance/compliance answer "mission-critical data is backed up off-site"
unambiguously true.
