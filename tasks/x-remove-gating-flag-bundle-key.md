# Remove FREE_TIER_GATING_ENABLED from the prod secret bundle

**Trigger: the gating-flag-removal commit (see
`tasks/complete/remove-free-tier-gating-flag.md`) is deployed to prod.**
Do NOT do this before that deploy: the currently-running container still
reads the key, and removing it early would flip that old code to its
default-off branch (gating silently off in prod until the next deploy).

## The step

Pull the `app_runtime_secrets` bundle, delete the
`"FREE_TIER_GATING_ENABLED": "true"` entry, add the new version, restart:

```powershell
gcloud secrets versions access latest --secret=app_runtime_secrets --project=codechronicle-487104 > bundle.json
# edit bundle.json: remove the FREE_TIER_GATING_ENABLED key
gcloud secrets versions add app_runtime_secrets --data-file=bundle.json --project=codechronicle-487104
del bundle.json
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```

Why bother: a stale key in the bundle reads as still-load-bearing to the
next person editing it. `FREE_TIER_CODE_NAMES` (if present) STAYS — it is
the scope definition, not the switch.

## Verify

Site up, anonymous search still scoped to OBC 2006 (teaser on a 2014
as-of date), `/pricing/` serves the plan cards.
