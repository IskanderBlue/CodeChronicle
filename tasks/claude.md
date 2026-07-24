# tasks/ filename prefixes

A prefix classifies why each card sits here and when to pick it up
(same convention as CCM's `tasks/future/claude.md`):

- `n-` — **needs new ingestion** before it's actionable (another code or
  edition: NBC, other provinces, pre-1997 OBC print editions, a
  commercial edition, …).
- `x-` — **no case in current data/state requires it**; gated on a
  trigger event (the card should say what that trigger looks like).
- `a-` — **high priority**, actionable now.
- `b-` — **medium priority**, actionable now.
- `c-` — **low priority**, actionable now.

One prefix per file. Finished cards move to `complete/`; superseded or
deliberately-abandoned plans move to `obsolete/`. Subdirectories are not
covered by this convention.
