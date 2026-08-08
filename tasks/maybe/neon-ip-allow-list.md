# Restrict where the Neon database accepts connections

Split out of `tasks/ao-security-hardening-rollout.md` (step A5) on 2026-08-08,
because the rest of that rollout is finishable and this is not. It sat in an
actionable card as a permanently blocked line, which made the card read as
further from done than it was.

## What would have to become true

**A paid Neon tier.** IP Allow is not on the free plan. Nothing else blocks
this — the steps below are short and the values are known.

The same upgrade unlocks database audit logging, which
`docs/security/breach-response-plan.md` §6 lists under "Planned remediation".
Judge the two together: one upgrade buys both, and neither alone is likely to
justify the line item.

## What it buys, and what it does not

Today `allowed_ips = []`, so the database accepts a connection from anywhere
that has a password.

**It does not protect the data from a stolen credential used from our own VM**,
and it is not what stops a leaked password being useful — the least-privilege
roles do that, and they are live. `cc_app` cannot run DDL, cannot TRUNCATE and
cannot CREATE in `public` (`tasks/ao-security-hardening-rollout.md`, A1 and A3).

**It does close the case where a credential leaks and is used from somewhere
else** — a laptop, a CI runner, a scanner. That is defence in depth on top of a
lockdown that already happened, which is why it is worth doing and not urgent.

## The steps, when the tier lands

1. Find the VM's egress IP:

```powershell
gcloud compute instances describe codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --format="get(networkInterfaces[0].accessConfigs[0].natIP)"
```

If the VM routes through Cloud NAT, take the NAT IP from the router instead.
The address above is the instance's own external IP, which is not the same
thing.

2. Neon console → Project → Settings → **Network Security / IP Allow**. Add
   that address.

3. ⚠️ **Add your own admin IP in the same edit.** Leaving it out locks you out
   of the SQL editor and of `psql`, and the console is then the only way back.

4. Re-check that the app still connects: `pg_stat_activity` must still show
   `cc_app` holding connections.

## Related

- `tasks/ao-security-hardening-rollout.md` — the rollout this came from.
- `docs/security/breach-response-plan.md` §6 and §8.
