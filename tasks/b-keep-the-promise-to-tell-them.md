# Keep the promise: tell people when their edition lands

**Prefix:** `b-` — medium priority, actionable now. The promise is already
live; the mechanism is not.

## The gap

The edition-request band says, in so many words:

> Tell us the code and the year you work with, and we will tell you when it
> lands.

Nothing tells them. `EditionRequest` stores the address, `/insights/` lists
the rows, and there the trail ends. The first time an edition ships, the
addresses will be months old and nobody will remember to write.

A promise on the front page with no mechanism behind it is worse than no
promise. It is also the cheapest trust we will ever lose.

## What to build

Deliberately small. Do **not** build a mailing-list system.

1. **A management command**, `notify_edition_requests`, that takes the text to
   send and the rows to send it to, prints who it would write to, and only
   sends with an explicit flag. Run by hand, when an edition ships. Prod
   already has SMTP configured (`code_chronicle/settings/production.py`), so
   there is no new infrastructure.
2. **A `notified_at` column** on `EditionRequest`, so a row is never written
   to twice and so the command can be re-run safely after a failure.
3. **A matching rule that is a human, not a parser.** The command takes the
   row ids or a search string; it does not try to decide by itself that
   "the 1990 OBC" matches an OBC 1997 load. Free text is free text; see
   [[feedback_clean_data]] for why we do not normalise it on the way in
   either.
4. **A plain-text email.** Four sentences: what shipped, a link to a search
   already run against it, how to stop hearing from us, and who we are. No
   template, no images, no tracking pixel.

## Rules

- **Only write to somebody about the thing they asked for.** A request for
  the BC code is not permission to announce an Ontario feature. The Privacy
  Policy now says this explicitly, so it is a promise as well as good manners.
- **Every send records `notified_at`.** A duplicate announcement reads as a
  mailing list, which is what we said this was not.
- **Include an unsubscribe line even though this is not a mailing list.** One
  sentence with an address to write to is enough, and it costs nothing.
- **Print, then send.** The command must default to a dry run. An accidental
  send to every address in the table is not recoverable.

## Also worth doing at the same time

Nothing is sent to a **new account** either. A signup gets the allauth
confirmation email and then silence. One short message a day later — here is
what the free tier covers, here is one search worth trying, reply if a text
looks wrong — would cost an afternoon and is the first chance to start the
conversation the higher price depends on. Decide whether that belongs here or
in its own card after the first fifteen customer conversations
(`tasks/a-first-customer-conversations.md`).

## Done when

- `notify_edition_requests` exists, defaults to a dry run, and is documented
  in `CLAUDE.md` beside the other commands.
- `notified_at` exists, with a migration, and the command sets it.
- A test proves a notified row is skipped on a second run.
- One real send has gone out, and you have read it yourself first.

## Related

- `core/views/demand.py`, `core/models.py` (`EditionRequest`).
- `templates/privacy_policy.html` — "Requests and Corrections You Send Us".
