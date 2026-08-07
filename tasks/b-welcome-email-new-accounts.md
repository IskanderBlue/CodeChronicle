# Say something to a new account

**Prefix:** `b-` moderate priority. Code, and actionable now.

The card first waited on the first fifteen customer conversations, on the
grounds that they decide what the message says. That gate is lifted (decision,
7 August 2026): the message can be written now and improved after the
conversations. Silence in the meantime is worse than a first draft.

Split out of `tasks/b-keep-the-promise-to-tell-them.md`, which raised it as
"also worth doing at the same time" and then said to decide later. It is a
different promise to a different person, so it is a different card.

## The gap

A signup gets the allauth confirmation email, and then silence. Nothing tells
a new reader what the free tier covers, or what to try first.

The free scope is one edition, OBC 2006. A reader who signs up and searches a
1997 date meets a locked page. Nobody has explained the shape of the product
to them at that point, so the lock reads as a fault.

## What to build

One short message, one day after the signup. Four things:

1. What the free tier covers, in one sentence, naming OBC 2006.
2. One search worth running, as a link.
3. An invitation to reply when a text looks wrong.
4. Who we are.

## Rules

- **One message, not a sequence.** A drip sequence is a mailing list, and the
  Privacy Policy says we do not run one.
- **Wait for the link that shows a completed search.** Sentence 2 needs it.
  See `tasks/b-keep-the-promise-to-tell-them.md`, which has the same
  dependency.
- **Do not send to an unconfirmed address.** allauth holds the confirmation
  state; read it rather than the signup date alone.

## Open

How it runs. A management command needs somebody to run it every day, which
nobody will do. A signal on the confirmation, with a delay, needs a task
runner the project does not have. Decide this when the card starts.

## Related

- `tasks/a-first-customer-conversations.md` — the trigger.
- `tasks/b-keep-the-promise-to-tell-them.md` — the same link dependency.
- `templates/privacy_policy.html` — "Requests and Corrections You Send Us".
