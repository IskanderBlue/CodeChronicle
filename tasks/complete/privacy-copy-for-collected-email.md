# Privacy copy for the new collection points — DONE 2026-08-01

**Status:** complete. Kept as the record of what changed and why, because the
next person to edit the Privacy Policy needs the version rule below.

## What prompted it

Two surfaces began collecting an optional email address from visitors with no
account:

1. **Edition requests** — `EditionRequest` (`core/views/demand.py`), on the
   landing page and both rate-limit surfaces. Live 2026-08-01.
2. **"This looks wrong" reports** — `ProvisionFeedback`, still to come; see
   `tasks/a-this-is-wrong-reports.md`.

`templates/privacy_policy.html` described account email, search history and
payment data. It said nothing about an address given by somebody who never
made an account.

## What was done

**A new section, "Requests and Corrections You Send Us"**, in the Information
We Collect part of `templates/privacy_policy.html`. It states what we record
(the text, the IP address, the date), that the email is optional and that
leaving it blank still records the request, that we use the address only to
answer that request, that it does not become a mailing list and is not used to
advertise, a two-year retention period, and the address to write to for
removal. The Data Retention section names the same two-year period.

The wording covers provision-feedback reports as well, so that feature needs
no second edit here.

**"Last updated" moved to August 1, 2026.**

## The version rule — read this before the next edit

The signup clickwrap covers **both** documents in one checkbox, and it used to
stamp both with one `TERMS_VERSION`. That forced a choice with no right answer
whenever only one document changed: bump the stamp and the acceptance record
dates the *unchanged* document falsely, or leave it and the record points at
text that has since been rewritten. Both corrupt the evidence the record
exists to be.

So the stamp was split:

- `settings.TERMS_VERSION` — matches the Terms' own "Last updated" line.
- `settings.PRIVACY_VERSION` — matches the Privacy Policy's own line.
- `TermsAcceptance.privacy_version` — new column, migration `0047`.
- `User.has_accepted_privacy(version)` — the counterpart to
  `has_accepted_terms`.

**Bump only the document that changed, and only when the change is
substantive.** A typo fix is not a new agreement.

Migration `0047` backfills pre-split rows with `"2026-06-17"`. That is not a
guess: the Privacy Policy carried "Last updated: June 17, 2026" from then
until this change, so every earlier acceptance was against exactly that text.

## Still open

Re-acceptance is **not** implemented. Nothing prompts an existing user to
accept a newer version of either document, and nothing compares a user's
stamped versions against the current ones. The data now supports it — that is
what `has_accepted_privacy` is for — but no surface uses it. If a future
change to either document needs existing users to re-accept, that prompt is
new work.

## Files

- `templates/privacy_policy.html`
- `code_chronicle/settings/base.py` (`TERMS_VERSION`, `PRIVACY_VERSION`)
- `core/models.py` (`TermsAcceptance.privacy_version`,
  `User.has_accepted_privacy`)
- `core/forms.py` (`CustomSignupForm.signup`)
- `core/migrations/0047_termsacceptance_privacy_version_and_more.py`
- `core/tests/test_clickwrap.py` — 9 tests
