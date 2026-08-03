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
deliberately-abandoned plans move to `obsolete/`; ideas whose case is not made
move to `maybe/`. Subdirectories are not covered by this convention, so a card
in one of them carries no prefix.

A card in `maybe/` is not a backlog item. It says what would have to become
true before the idea is worth picking up, so that the reasons for saying no
survive and nobody re-argues them from scratch.
