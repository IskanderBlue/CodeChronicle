# Keep the promise: tell people when their edition lands

**Prefix:** `b-` — medium priority. The promise is already live; the
mechanism is not.

**Status: DONE 2026-08-07.** The mechanism is built. The send itself is not
work but an event, and it waits on a first request — it carries its own card,
`tasks/x-send-the-first-edition-announcement.md`, so the reminder is somewhere
a person still reads. A finished card is not read again, and "nobody
remembered to write" is the failure this card was about.

`notify_edition_requests`,
`EditionRequest.notified_at` / `notified_about` (migration 0052), and
`core/tests/test_notify_edition_requests.py` (16 tests). The command is
documented in `CLAUDE.md` beside the other commands. **No real send has gone
out**, and there is nobody to send to — see below.

Two things differ from the plan:

- **`notified_about` is a list, not one label.** A row may name two editions,
  and one stamp would spend it on the first. The list is also what makes a
  re-run safe after a part-way failure.
- **An unset `Site` row is refused.** Django ships it reading `example.com`,
  and `--search` would have built a dead link into a message that still sends.
  The only person who would find out is the reader.

## State on 2026-08-06

Two facts from prod, both of which change what "done" can mean:

- **`edition_requests` holds no rows.** Nobody has asked yet, so there is
  nobody to write to. The command can be built and tested; the "one real
  send" in **Done when** has no recipient and must wait for a first request.
- **OBC 1997 is loaded (3 154 provisions) but is outside the free scope.**
  `FREE_TIER_CODE_NAMES` is `OBC_2006` alone, and the prod bundle carries no
  override. So "your edition landed" leads a free reader to a 403. Either the
  first sentence says the edition needs Pro, or the send waits for a free-scope
  edition. Do not write a message that ends at a locked page.

The second fact is why the sentence-2 link matters more than the rest of this
card: a link that shows a completed search is the only way to show somebody a
text they cannot otherwise open.

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

## Decisions, 2026-08-06

- **`notified_at` is not enough on its own.** Add `notified_about`, holding
  the edition label we sent. The command skips a row it has told about *this*
  edition, not a row it has ever written to. One timestamp spends a row that
  names two editions, and that row then never hears about the second.
  `--force` overrides.
- **Two of the four sentences are fixed, two are not.** Sentences 3 and 4 —
  how to stop hearing from us, and who we are — live in the command as
  boilerplate. Sentence 1 says what shipped and is written per send. Sentence
  2 carries the link, which is per send as well; a helper can build the URL,
  but somebody chooses the search.
- **Group by address only inside one send.** If a send covers several rows
  from one address, write once and stamp all of them. If it does not, leave
  the other rows alone. They are still owed a message about their own edition.
- **Never send without an explicit instruction in that message.** The real
  send is probably not run from prod.
- **The new-account message is a separate card**:
  `tasks/x-welcome-email-new-accounts.md`.

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
