# "This looks wrong" — reader reports on any provision

**Prefix:** `a-` — high priority, actionable now.

## Goal

Let any reader — free, Pro or anonymous — tell us that a specific provision
version is wrong, from the page that shows it. Give ourselves a queue to
triage the reports, and reply to the reader when we act.

Free for everybody, on purpose. A reader who reports a discrepancy is doing
our verification for us, and a product that invites correction reads as more
trustworthy than one that does not. That is the same argument the site already
makes on the Sources page and the verification-rail guide.

## The model

`ProvisionFeedback`:

- The target: edition, division, provision id, version. Stored as text, not as
  a `ForeignKey` — `load_edition` replaces provision and version primary keys
  wholesale on reload, and a report must outlive a reload. This is the same
  reasoning `EngagementEvent.object_id` already uses.
- `note` — what the reader says is wrong.
- `email` — optional. A report we cannot answer is still a useful report.
- `user`, `ip_address`, `surface`, `created_at`.
- `status` — `new` / `reviewed` / `fixed` / `not_a_defect`.
- `resolution` — free text, our note back to ourselves.

Not a general contact form. A report tied to a version is actionable; "the
dates look wrong somewhere" is not. The form pre-fills the target and cannot
be submitted without one.

## The trigger

A link reading **"This looks wrong"**, in the attestation rail, beside the
existing "How to read this" link.

The rail is where the page makes its claim about trustworthiness. An
invitation to dispute that claim belongs in the same place, in the same
typographic register — the `.ui-action` affordance from
`project_interactive_taxonomy`. Not a floating widget, not a coloured badge.

Clicking opens a dialog with the provision and version already named, one
textarea, and an optional email field. One shared partial, used on all three
surfaces, so the wording cannot drift:

1. The provision permalink (`regulation/provision_permalink.html`).
2. The regulation detail page (`regulation/detail.html`).
3. Each expanded search result (`partials/_result_expanded.html`).

## The queue

A section on `/insights/`, staff only: the note, the target as a link to the
provision, the reader's email, the age, and the status. Newest first, `new`
first.

A report with no triage view becomes a table nobody opens. The queue is not
optional scope.

## Replying

When a report is resolved and the reader left an email, send a short reply
naming what changed. This is the "answer from a person" that justifies the
Pro price, and it costs one paragraph.

Do not build an automated reply. A form letter about a legal text is worse
than silence.

## Abuse

Same shape as `core/views/demand.py`: a soft per-IP daily ceiling, over-limit
posts accepted silently and discarded. Do not add a CAPTCHA. The volume will
be tiny, and a CAPTCHA in front of "tell us we are wrong" defeats the point.

## Done when

- The model, the migration and the endpoint ship.
- One shared partial appears on all three surfaces.
- The `/insights/` queue lists reports with a working status control.
- Anonymous, free and Pro readers can all file a report, with tests for each.
- No privacy-policy edit is needed. The "Requests and Corrections You Send Us"
  section already covers provision-feedback reports as well as edition
  requests. Confirm that before shipping, and read the version rule in
  `tasks/complete/privacy-copy-for-collected-email.md` if you do change it.

## Related

- `core/views/demand.py` — the same shape, already built. Reuse its structure.
- Memory: `project_interactive_taxonomy`, `feedback_reuse_dont_transcribe`.
