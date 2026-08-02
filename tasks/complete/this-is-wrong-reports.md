# "This looks wrong" — reader reports on any provision

**Status: done.** Built as planned, with three departures recorded at the end
of this card. The suite is green (650 tests).

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
- No privacy-policy edit is needed. **Confirmed before shipping:** the
  "Requests and Corrections You Send Us" section already names the case in
  words — "or report that a provision looks wrong" — and states the retention
  and the deletion route. `PRIVACY_VERSION` therefore does not move; the text
  the reader accepted is still the text that governs.

## What was built

| Piece | Where |
|---|---|
| Model + migration | `core/models.py` (`ProvisionFeedback`), `0048` |
| Endpoints | `core/views/feedback.py` — `/report/`, `/report/<pk>/status/` |
| Trigger + dialog | `templates/partials/_report_problem.html` |
| Swappable panel | `templates/partials/_report_problem_panel.html` |
| Queue row | `templates/partials/_feedback_row.html` |
| Queue + metric | `core/insights.py`, `templates/insights.html` |
| Full triage | `core/admin.py` — where the resolution note gets written |
| Tests | `core/tests/test_feedback.py` (25) |

## Three departures from the plan

1. **The trigger is opt-in per surface**, through an `allow_report` flag on the
   provenance band, rather than always-on. The band is also mounted as a
   landing-page specimen and as a verification-guide example, and a report
   filed from either would name a provision nobody was reading. Two tests hold
   that line.
2. **A regulation report is its own target shape.** The regulation page shows a
   whole instrument and no single provision, so it stores `reg_id` instead of
   the provision fields. The queue resolves either shape back to a URL. The
   regulation number, not the row pk, for the same reload reason as the rest.
3. **The band's no-rail branch carries the trigger too.** A never-in-force
   version, and any page with no query date, renders no attestation rail — and
   those are exactly the versions whose dates a reader is most likely to
   dispute, so that branch must not be the one that drops the invitation.

## One thing worth knowing

The status control's selected state is a component class
(`.ui-btn-ghost.is-current` in `base.html`), not `text-secondary` on the
element. Tailwind v4 emits utilities inside `@layer utilities`, and base.html's
unlayered `.ui-btn-ghost` beats a layered rule whatever the source order — so
the utilities rendered and did nothing, and every button in the group looked
identical. Only a screenshot showed it. See `project_tailwind_hidden_display_order`,
which is the same cascade fact in its `display` form.

## Not done, on purpose

The reply is manual. A resolved report with an email gets a short note from a
person, written in the admin. No automated reply: a form letter about a legal
text is worse than silence.

## Related

- `core/views/demand.py` — the same shape, already built. Reuse its structure.
- Memory: `project_interactive_taxonomy`, `feedback_reuse_dont_transcribe`,
  `project_tailwind_hidden_display_order`.
