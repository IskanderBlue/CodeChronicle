# Privacy Breach Response Plan

> **Status:** active operational procedure.
> **Owner:** Robert Lee (Founder) — rob@codechronicle.ca · 226-700-3295.
> **Legal basis:** PIPEDA (federal, applies to commercial activity in Ontario),
> breach-of-security-safeguards provisions in force since 2018-11-01.
> **Last reviewed:** 2026-06-13

This plan exists so that, if personal data is exposed, the response is a checklist
to follow — not a decision to improvise under pressure. It is deliberately short.

---

## 1. What counts as a breach

A *breach of security safeguards* is the loss of, unauthorized access to, or
unauthorized disclosure of personal information resulting from a failure of our
safeguards (or absence of safeguards). Examples relevant to CodeChronicle:

- The production database is accessed, copied, or dumped by someone unauthorized.
- A leaked credential (GCP, Neon/database, Stripe, GitHub, Cloudflare, email) gives
  a third party access to a system holding personal data.
- The Django `SECRET_KEY` leaks (enables session forgery → account takeover).
- A laptop or device with a live database connection / saved credentials is lost or stolen.
- A misconfiguration exposes the database, an admin endpoint, or logs publicly.
- A third-party processor we rely on (Stripe, Neon, Cloudflare, the email relay)
  notifies us of a breach on their side affecting our users.

A near-miss with no actual access (e.g. a blocked intrusion attempt) is **not** a
breach, but log it anyway (§6) — patterns matter.

---

## 2. Personal information we hold (know this before a breach, not during)

| Data | Location | Sensitivity |
|---|---|---|
| Email addresses | `users.email` (Postgres) | Identifier — moderate |
| Password **hashes** | `users.password` (Postgres) | Low — Django PBKDF2-SHA256, salted + iterated; not plaintext |
| Stripe customer ID + mirrored billing | `users.stripe_customer_id`, dj-stripe `Customer`/`Subscription` (Postgres) | Links to billing; **no card numbers here** (Stripe holds those) |
| IP addresses | `search_history.ip_address`, `engagement_events.ip_address`, `auth_events.ip_address` (Postgres) | Personal info under PIPEDA — low/moderate |
| Search queries (free text) | `search_history.query`, `query_cache.raw_query` (Postgres) | Usually benign, but a user *could* type personal detail into a query |
| Engagement events | `engagement_events` (Postgres) | Behavioural — low |
| Auth events (login / logout / failed login) | `auth_events` (email + IP + outcome + timestamp) (Postgres) | Security audit log — emails + IPs; low/moderate |

**We do NOT store:** payment card numbers (held by Stripe), government IDs, health
data, or special-category data. This keeps the harm ceiling low for most scenarios.

**Where it all lives:** a single PostgreSQL database (production `DATABASE_URL`).
That database is the one asset a breach plan has to protect. Cloudflare R2 holds only
building-code images (no personal data); GitHub holds only code.

---

## 3. Immediate response — first hours (CONTAIN, then ASSESS)

Do these in order. Don't wait for certainty to start containing. The exact
commands are inline below — these are meant to be copy-pasted under pressure.
Set the project/zone once so every command can be pasted as-is:

```powershell
$P  = "codechronicle-487104"          # GCP project
$Z  = "us-central1-a"                  # VM zone
$VM = "codechroniclenet-vm"           # VM name
$C  = "codechroniclenet-web"          # container name
# helper: run a command inside the prod container
function dexec($cmd) { gcloud compute ssh $VM --zone=$Z --project=$P --tunnel-through-iap --command="sudo docker exec $C $cmd" }
function vssh($cmd)  { gcloud compute ssh $VM --zone=$Z --project=$P --tunnel-through-iap --command=$cmd }
```

**Contain:**

1. [ ] **Preserve evidence FIRST — before you rotate or stop anything.** Rotation and
   restarts roll logs; capture them while they exist. (You can do this in the same
   minute as containment — just grab logs before the restart, not after.)
   ```powershell
   # App/container logs → local file
   vssh "sudo docker logs --timestamps $C" > "breach-container-$(Get-Date -Format yyyyMMdd-HHmm).log" 2>&1
   # GCP infra/audit logs (widen --freshness / --limit as needed)
   gcloud logging read "resource.type=gce_instance" --project=$P --freshness=2d --limit=500 > "breach-gcp-$(Get-Date -Format yyyyMMdd-HHmm).log"
   ```
   Also pull, from each dashboard (no CLI): **Stripe** → Developers → Events/Logs;
   **GitHub** → github.com/settings/security-log; **Cloudflare** → Audit Log;
   **Neon** → Monitoring / connection activity (paid tiers only).

2. [ ] **Kill switch — stop serving if data is actively at risk:**
   ```powershell
   vssh "sudo docker stop $C"     # take the app offline; restart with: vssh "sudo docker start $C"
   ```

3. [ ] **Rotate the exposed credential.** Do the one(s) that leaked:

   - **Database (`DATABASE_URL`) — the most likely and most serious:**
     1. In the **Neon dashboard**, reset the role's password → copy the new
        connection string (this instantly invalidates the old one).
     2. Push it into Secret Manager and restart. Write via a temp file with **no
        trailing newline** (a stray `\n` in `DATABASE_URL` breaks parsing), then
        delete it — same pattern as `docs/edit-prod-settings.md`:
        ```powershell
        $tmp = "$env:TEMP\dburl.txt"
        [IO.File]::WriteAllText($tmp, (Read-Host "New DATABASE_URL"))   # no newline appended
        gcloud secrets versions add database_url --data-file=$tmp --project=$P
        Remove-Item $tmp                                                # don't leave the live URL on disk
        vssh "sudo docker restart $C"
        ```
   - **`SECRET_KEY` leak (enables session forgery):** generate, store, restart.
     This also invalidates every session and password-reset token — intended.
     ```powershell
     $newkey = python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
     $newkey | gcloud secrets versions add django_secret_key --data-file=- --project=$P
     vssh "sudo docker restart $C"
     ```
   - **GCP:** revoke/rotate the affected service-account key or user access in IAM;
     `gcloud iam service-accounts keys list/delete` if a key leaked.
   - **Stripe / GitHub / Cloudflare / email relay:** rotate that service's API key
     from its dashboard and revoke active sessions/tokens there.

4. [ ] **Force every user session closed (logout-all)** — use after any `SECRET_KEY`
   or account-credential compromise. Clears all DB-backed sessions immediately
   (single-quoted Python so the quoting survives PowerShell → ssh → docker → python):
   ```powershell
   dexec "python manage.py shell -c 'from django.contrib.sessions.models import Session; print(Session.objects.all().delete())'"
   ```

5. [ ] **Force password resets** — only if user *credentials* (not just hashes) are at
   real risk. Sets passwords unusable so the next login must go through email reset;
   combine with the §4 notification telling users to reset. Written as one expression
   (no embedded newlines) for the same quoting-survival reason:
   ```powershell
   # ALL users (blunt). For specific users, swap U.objects.all() for U.objects.filter(email__in=[...])
   dexec "python manage.py shell -c 'from django.contrib.auth import get_user_model as g; U=g(); print(sum(1 for u in U.objects.all() if (u.set_unusable_password() or u.save() or True)))'"
   ```
   If any one-liner misbehaves through the quoting layers, fall back to an interactive
   shell and paste the Python directly: `vssh "sudo docker exec -it $C python manage.py shell"`.

**Assess (the RROSH test):**

6. [ ] **First, scope what was actually reachable — and know our logging blind spot.**
   What we *do* have: app-mediated **content** access is logged — `search_history`
   and `engagement_events` record which user/IP ran each search and opened each
   provision/regulation, with timestamps; Django admin *writes* are captured by the
   framework's built-in `LogEntry`. What we **don't** have: ⚠️ **no row-level access
   logging at the database, and no pgAudit or Postgres statement logging.** So an
   attacker with the database credential connects *beneath* the app — bypassing the
   `record_event` trail entirely — and leaves at most a *connection-level* trace in
   Neon's logs (that a connection occurred, from an IP, on paid tiers) — **never which
   tables or rows were read.** (Authentication events — logins, logouts, failed logins
   — *are* now logged to `auth_events`, so app-layer credential abuse leaves a trail;
   it's only the direct-DB path that's blind.) Consequence: when a database credential
   is compromised,
   you **cannot** prove a narrow scope, so per OPC guidance you **assume the worst
   case — the entire §2 inventory was exposed** — and assess RROSH on that. Only scope
   *down* if you have positive evidence the access was limited (e.g. it was a single
   leaked read-only view, or the credential was revoked before any connection
   succeeded).

   > **Planned remediation (deferred):** add database-level audit logging (pgAudit
   > and/or connection logs) when we move to a Neon paid tier — or to another provider
   > that supports it — so a future DB-credential breach can be *scoped* instead of
   > assumed total. Until then, the worst-case assumption above stands. (Auth-event
   > logging — the cheap, provider-independent half — is **done**: see `auth_events`
   > and `core/auth_audit.py`.)

7. [ ] **Decide whether there is a Real Risk of Significant Harm (RROSH)** — the legal
   trigger for notification. Weigh two factors:
   - **Sensitivity** of the information involved, and
   - **Probability** the information is/will be misused (was it encrypted? a targeted
     theft, or a leaked-then-immediately-revoked key? has it appeared anywhere?).

   Significant harm includes: identity theft, fraud, financial loss, damage to
   reputation, humiliation. For our data: **email + password hash** exposure is the
   realistic worst case (credential-stuffing risk if a user reused their password) —
   treat that as RROSH-positive. **IPs / search queries / Stripe customer-IDs alone**
   are lower; judge case by case. **Hashes only, no emails**, or **revoked-before-use
   credential with no evidence of any connection** → likely no RROSH, but record the
   reasoning. When scope is unknown (the blind spot above), default to RROSH-positive.

---

## 4. Notification — if RROSH is present

PIPEDA requires notification **"as soon as feasible"** after you conclude a breach
posing RROSH occurred. There is no fixed hour count under PIPEDA — but act in days,
not weeks. (If **any EU/UK residents** are affected, GDPR's **72-hour** clock to the
relevant supervisory authority also applies — assume the tighter deadline then.)

1. [ ] **Report to the Office of the Privacy Commissioner of Canada (OPC).**
   - Use the OPC's *PIPEDA breach report form* (priv.gc.ca → "Report a breach").
   - OPC info line: **1-800-282-1376**.
   - The report covers: circumstances, when it occurred, personal info involved,
     number of individuals affected, what you've done to reduce/mitigate harm, and
     how you're notifying individuals.
2. [ ] **Notify affected individuals** directly (email to the address on file),
   as soon as feasible. The notice must let them understand the significance and take
   protective steps. Include:
   - what happened and when, in plain language;
   - exactly what information of *theirs* was involved;
   - what we've done in response;
   - **what they should do** — for an email+password-hash breach: *change your
     CodeChronicle password now, and change it anywhere you reused it*;
   - how to reach us (rob@codechronicle.ca) and how to reach the OPC.
3. [ ] **Notify other organizations that can reduce harm**, where relevant:
   - **Stripe** — if any billing linkage was exposed (they can watch for fraud).
   - **Neon / GCP / Cloudflare / GitHub** — the host of the breached system, to
     investigate and rotate at their layer.
4. [ ] Force a **password reset** for affected accounts if credentials were involved.

---

## 5. After the immediate response

- [ ] Write up root cause and the fix that prevents recurrence (e.g. close the
  exposed port, add the missing IAM condition, stop committing the credential).
- [ ] If the cause was an exposed secret, audit *all* secrets for similar exposure.
- [ ] Update this plan if the breach revealed a gap in it.

---

## 6. Breach register (KEEP FOR 24 MONTHS — legally required)

PIPEDA requires a record of **every** breach of security safeguards — reportable or
not — kept for **24 months** after you determine the breach occurred, and produced to
the OPC on request. Knowingly failing to report or keep records carries penalties up
to **$100,000**. Log every breach and near-miss below.

| # | Date determined | What happened | Data / individuals affected | RROSH? (+ reasoning) | OPC reported? | Individuals notified? | Resolved / root cause |
|---|---|---|---|---|---|---|---|
| _e.g._ | _2026-00-00_ | _(none yet — this is a template row; delete once real entries exist)_ | | | | | |

> Keep this register here (or in a private, access-controlled location) and never
> delete rows inside the 24-month window. If you move it off this repo, leave a
> pointer here to where it lives.

---

## 7. Key contacts

| Who | For | Contact |
|---|---|---|
| OPC (Privacy Commissioner of Canada) | Mandatory breach report | priv.gc.ca · 1-800-282-1376 |
| Stripe | Billing-data exposure, fraud watch | dashboard → Support; security@stripe.com |
| Neon / database host | DB credential rotation, access logs | provider dashboard → Support |
| GCP | Service-account/IAM rotation, VM logs | Cloud Console → Support; project `codechronicle-487104` |
| Cloudflare | R2 / DNS / token rotation | dashboard → Support |
| GitHub | Repo/audit log, token rotation | github.com → Support |
| Legal counsel | Notification wording, liability | _(fill in when retained)_ |
| Cyber-insurer (if/when carried) | First-party breach-response coverage | _(fill in policy # + 24h claims line)_ |

---

## 8. Preventive hardening — shrink the DB-credential blast radius

The worst-case scenario this plan keeps returning to is a leaked `DATABASE_URL`,
because we *can't scope it* (the §6 blind spot). The most effective answer is not more
detection but **prevention**: make the stolen credential useless or low-value. These
are mostly config, not code, and each one shrinks the blast radius independently.

- [ ] **Restrict where the database accepts connections.** If the host supports IP
      allow-listing (Neon: IP Allow / "Allowed IPs" on paid tiers; or a private
      networking option), limit connections to the prod VM's egress IP. A
      `DATABASE_URL` leaked from a laptop or a log then **doesn't work from anywhere
      else** — it turns "full exposure, unprovable scope" into "the key doesn't even
      turn." This is the single highest-value item here.
- [ ] **Run the app on a least-privilege role**, not the Postgres superuser/owner. The
      app needs CRUD on its tables — not `DROP DATABASE`, not role management. A
      least-privileged app role caps what a leaked credential can *do* (read/write
      rows, yes; nuke the schema or read server config, no).
- [ ] **Consider a separate read-only role** for any analytics/reporting access, so
      day-to-day querying never travels with write/delete power.
- [ ] **Require TLS** on database connections (Neon enforces `sslmode=require` by
      default — keep it; never downgrade the connection string to disable SSL).
- [ ] **Secret hygiene** — the credential only leaks if it's somewhere it shouldn't be:
      keep `DATABASE_URL` solely in Secret Manager (never in `.env` committed to git,
      never echoed into logs); the `bundle.json` workflow already deletes the local
      copy after edits (`docs/edit-prod-settings.md`) — keep doing that.
- [ ] **Rotate on a schedule, not just on incident** — an occasional planned rotation
      bounds the useful lifetime of any copy that leaked without your knowledge.

> Why this lives in the breach plan: detection (logging, §6) tells you *after* the
> fact and we've documented why ours is limited; prevention changes the *probability*
> and *impact* up front. For a low-PII, solo operation, prevention is the better
> investment — a leaked key that only works from one IP and can't drop tables is a
> near-non-event, regardless of what the logs can or can't tell you.
