# Send the first edition announcement

**Prefix:** `xo-` — ops, and nothing in the current data requires it. You run
a command against prod and write to real people. **There is no undo**: a sent
message cannot be recalled, so the dry run is the only safety there is. `edition_requests`
held no rows on 7 August 2026, so there is nobody to write to.

**Trigger: an edition ships while `edition_requests` holds a row with an
address.** Check the queue on `/insights/`.

## Why this card exists

The mechanism is built and tested — see
`tasks/complete/keep-the-promise-to-tell-them.md`. What is not done is the
thing the promise was about: writing to somebody.

The original card said it plainly. The first edition to ship would find the
addresses months old and nobody remembering to write. A finished card in
`complete/` is not read again, so the reminder stays here until a real send
goes out.

## The step

```powershell
python manage.py notify_edition_requests `
    --about "OBC 1997" `
    --news "<what shipped, in one sentence>" `
    --search "<a question this edition answers>" --date <YYYY-MM-DD> `
    --match <what the requesters typed>
```

Read the printed message. Then add `--send`.

## Before you send

- **Read the report, name by name.** The command prints each reader's own
  words beside their address. Only write to somebody about the thing they
  asked for; a request for the BC code is not permission to announce an
  Ontario edition.
- **`--date` is not optional in practice.** The AS-OF picker overrides the
  date the parser reads out of the query text, so a link without one searches
  at the corpus default and can answer a 1999 question with a later edition.
- **The `Site` row must not read `example.com`.** `--search` refuses in that
  case, because the link would be dead and the message would still send.
- **A locked edition is acceptable.** OBC 1997 is loaded but outside the free
  scope, so a free reader meets a 403 and can then sign up. Say in sentence 1
  that the edition needs an account, so the wall is expected rather than a
  fault.

## Done when

One real send has gone out, and you read it yourself first. Then this card
moves to `complete/`.
