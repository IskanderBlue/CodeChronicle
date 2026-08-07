# tasks/ filename prefixes

A prefix classifies why each card sits here and when to pick it up
(same convention as CCM's `tasks/future/claude.md`):

**Gated — something must happen first. The card says what.**

- `n-` — **needs new ingestion** before it's actionable (another code or
  edition: NBC, other provinces, pre-1997 OBC print editions, a
  commercial edition, …).
- `x-` — **no case in current data/state requires it**; gated on a
  trigger event (the card should say what that trigger looks like).
- `p-` — **needs a push to prod first**. The work is built and merged; what
  is left can only run against the deployed site. An external validator that
  fetches a URL cannot read a working tree.

**Actionable now.**

- `a-` — **high priority**.
- `b-` — **medium priority**.
- `c-` — **low priority**.

One prefix per file, plus the `o` suffix below when the card is not code. Finished cards move to `complete/`; superseded or
deliberately-abandoned plans move to `obsolete/`; ideas whose case is not made
move to `maybe/`. Subdirectories are not covered by this convention, so a card
in one of them carries no prefix.

A card in `maybe/` is not a backlog item. It says what would have to become
true before the idea is worth picking up, so that the reasons for saying no
survive and nobody re-argues them from scratch.

# The `o` suffix: ops

A card whose work is **not editing this repository** takes an `o` after its
prefix letter: `ao-`, `bo-`, `co-`, `no-`, `po-`, `xo-`. Everything that is
not code is ops — a secret, a container restart, a Stripe dashboard change, a
Search Console registration, a management command run by hand, an article, a
talk, a conversation with a customer.

The letter still means what it meant. `ao-` is a high-priority ops card;
`xo-` is an ops card gated on a trigger. The suffix adds the second axis
without taking anything from the first.

Why it earns a place in the filename. A code card is done when the tests
pass, and a wrong step is a revert. An ops card changes something no test can
see, and often something no revert can reach: a message that has been sent, a
post that has been read. So an ops card must record **what it changed and how
to undo it** — the secret version to roll back to, the previous value of a
setting — and it must say so in the card, because nothing else will remember.

A card that ends in a code change is code, even when it starts with reading
something. `x-exports-60-day-review` reads the export counts and then deletes
what nobody used, so it stays code.
