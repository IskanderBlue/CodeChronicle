# The guard height article

**Built and committed on 14 August 2026** (`0c74086`). The page is public at
`/guard-height-ontario/`. Four ops items are still open; see **Still open**.

The article answers one question a code consultant asks every month, and that
no free source answers: what is the minimum guard height for a stair inside a
house in Ontario? It does two jobs — it proves the product without a demo, and
it ranks for the long-tail question the product answers. Do not write a second
article until this one has run for 60 days.

## What shipped

| File | What it holds |
|---|---|
| `core/views/guard_height.py` | The view, `OPENING`, `TRANSITIONS`, the title and description |
| `templates/guard_height.html` | The prose, and the 2024 quotation |
| `templates/partials/_article_redline.html` | One amendment, drawn as `/compare/` draws it |
| `templates/partials/_compare_sides.html` | The side rows, shared with `/compare/` |
| `core/management/commands/verify_guard_height_article.py` | The corpus check, and `allows_800_mm` |
| `core/tests/test_guard_height_article.py` | 33 tests |
| `core/urls.py`, `core/sitemaps.py`, `core/views/__init__.py` | Wiring |

Checked on 14 August 2026: 33 tests pass, ruff and mypy clean, and
`verify_guard_height_article` passes against a corpus carrying all three
editions.

The page opens with the question and a table with a row per distinct answer,
then gives the oldest text in full with its attestation band and the 1997
scan, then one section per amendment. Each section draws the redline of that
one change and says what it did to the answer — including the two amendments
that did nothing to it, which is the fact a reader with two PDFs cannot get
without reading both in full.

## The answer the page gives

| In force | Flight | Landing | Spiral stair | What changed |
|---|---|---|---|---|
| 6 Apr 1998 to 30 Dec 2006 | 800 mm | 900 mm | 800 mm | The only text that allows 800 mm |
| 31 Dec 2006 to 31 Dec 2013 | 900 mm | 900 mm | 900 mm | The flight rises 100 mm; the article changes number |
| 1 Jan 2014 to 31 Dec 2021 | 900 mm | **1 070 mm** | 900 mm | A new sentence raises the landing |
| 1 Jan 2022 to 31 Dec 2024 | 900 mm | 900 mm | **1 070 mm** | The landing drops 170 mm; spiral stairs go the other way |
| 1 Jan 2025 to today | 900 mm | 900 mm | 900 mm | OBC 2024; the spiral-stair carve-out does not come with it |

## The seven texts

From the production database on 12 August 2026. Re-read them before you
publish anything new; do not copy a number from this card.

| Edition | Provision | Version | In force from | In the corpus |
|---|---|---|---|---|
| OBC 1997 | 9.8.8.2. | 0 | 6 April 1998 | Yes |
| OBC 2006 | 9.8.8.3. | 0 | 31 December 2006 | Yes |
| OBC 2006 | 9.8.8.3. | 1 | 1 January 2010 | Yes |
| OBC 2012 | 9.8.8.3. | 0 | 1 January 2014 | Yes |
| OBC 2012 | 9.8.8.3. | 1 | 1 July 2017 | Yes |
| OBC 2012 | 9.8.8.3. | 2 | 1 January 2022 | Yes |
| OBC 2024 | 9.8.8.3. | — | 1 January 2025 | No |

The stored windows are half-open. Use `core.seo.last_governed_day` for every
"until" date. Do not subtract a day by hand.

**The provision number moved.** In OBC 1997 guard height is 9.8.8.2. From
31 December 2006 it is 9.8.8.3., and 9.8.8.2. means *Loads on Guards*. So a
report that cites 9.8.8.2. for guard height is right for a 1999 permit and
wrong for a 2008 permit. The citation still resolves, and it now points at a
different rule. That is the failure the product prevents.

**"The 2012 code says" is not a sentence.** OBC 2012 holds three different
guard-height texts. That single fact defeats the reader's own workaround of
keeping one PDF.

## The readings the prose rests on

**Two minimums do not contradict each other. The higher one is the
requirement.** Four drafts of this card got this wrong before Rob corrected it
on 14 August 2026. Sentence (2) sets 900 mm inside a dwelling unit and
sentence (5)(b) sets 1 070 mm around landings; a guard at 1 070 mm satisfies
both, so there is no conflict and no tiebreak to hunt for. A landing inside a
house is **1 070 mm** from 1 January 2014 to 31 December 2021, and the flight
beside it stays at 900 mm.

**Only the except-formula creates a relaxation.** Sentence (1) opens "Except
as provided in Sentences (2) to (6)", which is what lets sentence (2)'s
900 mm displace the general 1 070 mm. Nothing of the kind sits between (2) and
(5). The 1997 article shows the same drafter writing displacement out where it
is meant: its (3) opens "Except as provided in Sentence (4)", and (4) is what
drops a stair inside a dwelling unit to 800 mm.

**Derive every spiral cell from a sentence. Never copy the column beside it.**
The figures match the flight column until 2022, and that is a result, not a
method.

| In force | Spiral | The sentence that gets you there |
|---|---|---|
| 1998–2006 | 800 mm | 9.8.8.2.(4) — "guards for **stairs** within dwelling units". The 1997 article never uses the word "flight" |
| 2006–2014 | 900 mm | 9.8.8.3.(2) — "all guards within dwelling units", shape-blind |
| 2014–2022 | 900 mm | (2) again |
| 2022–2024 | 1 070 mm | (2) excludes it, (4) cannot reach it, so (1) |
| 2025– | 900 mm | 2024 (2) — no spiral exclusion, and shape-blind |

Sentence (2) is shape-blind in every edition, which is what makes four of the
five cells robust. The shape only matters from 2022, which is the day the code
answers it in 9.8.3.1. Do not confuse two questions: whether a spiral stair is
a permitted *configuration* is arguable; how high its *guard* must be is
answerable, and the column asks the second.

**1 January 2022 is a relaxation of 170 mm, not a tidy-up**, and the corpus
proves it was a package. Sentence (5) was revoked — it keeps its number and
reads *Reserved* — so a landing that needed 1 070 mm on 31 December 2021
needed 900 mm the next day. O. Reg. 88/19 changes three provisions on that one
day: 9.8.3.1. is rewritten so a stair consists of "straight flights, curved
flights, **or spiral stairs**"; 9.8.4.5A. is created, requiring the outer
handrail at not less than 1 070 mm; and 9.8.8.3.(2) drops guards serving
spiral stairs.

**920 mm is disposed of in the prose, not in the table.** Two of these texts
set 920 mm for a required exit stair. An exit runs from a floor area to
outdoors and a stair inside a house is not one, so the figure answers a
different question — but a reader meets it in the redlines and must be told
why it is absent. The exception is a house with a secondary suite, where a
shared stair can be part of a required exit.

**Two findings are not on the page.** The same 2022 amendment narrowed
sentence (7) from "guards for stairs and landings" to "guards for flights",
which leaves a spiral-stair guard with a required height and no stated way to
measure it. And sentence (3) has no spiral carve-out, so an exterior spiral
stair serving a house within 1 800 mm of grade still gets 900 mm.

**The Part 3 history is off the page and stays off.** It was gathered to argue
that clause (b) meant something narrower than it said — an argument that died
when the composition rule above settled the question. Evidence gathered for a
discarded argument does not transfer, because it was selected to answer a
question nobody is asking. Do not bring it back.

## OBC 2024, which is not in the corpus

The article must give today's answer; a reader who cannot find the current
rule stops trusting the historical ones. OBC 2024 is one page: O. Reg. 163/24
adopts NBC 2020 plus an amendment document. Ontario replaces sentence (1) and
adds sentence (3.1); the rest is national text.

**The page quotes the article whole**, all five sentences, from the 2024
Building Code Compendium at
`CodeChronicleMapping/data/inputs/pdfs/ontario.ca/301880.pdf`. Rob decided
this on 13 August 2026. Two earlier shapes were worse: quoting only Ontario's
(1) and (3.1) left the reader meeting "Except as provided in Sentences (2) to
(3.1)" with the gap invisible, exactly where the sharpest claim lives; stating
the national three in our own words replaced that with a paraphrase, and a
paraphrase of a rule is an argument about the rule.

Quote from the Compendium and use its spacing: it prints "1 500 mm" where the
Amendment Document reads "1500 mm".

**The 900 mm allowance for a flight of steps is gone.** OBC 2012 sentence (4)
read "Guards for flights, except in required exit stairs, shall be not less
than 900 mm high", and OBC 2024 has no such sentence. This is recorded but
**not published** — the section carrying it came out on 14 August 2026 — which
is why it needs no sign-off before shipping. The 920 mm exit-stair guard was
Ontario's own and appears nowhere in the 2024 code.

**Where to get the current document.** The ministry does not put it on e-Laws.

1. `https://www.codenews.ca/OBC/OBC2024/Ontario%20Amendments%20to%20the%20National%20Building%20Code%20of%20Canada%20-%20YYYY-MM-DD.pdf`,
   where the date is the document's own date.
2. `Ontario.Amendment.Document@ontario.ca` replies with the current document.
   This is the ministry's own route and the one to cite.
3. The CodeNews newsletter announces each release, which is how you learn that
   a new date exists.

**Read the date out of the regulation, not out of a file listing.** Section 1
of O. Reg. 163/24 names the adopted document by date. The Word copy at
`https://www.ontario.ca/laws/docs/240163_e.doc` carries that text; the e-Laws
page loads it with a script and a fetch returns an empty shell.

**The section number is not stable across documents, and the article cites
it.** The guard-height amendment is section 341 in the October 2024 document
and section 344 in both 2026 documents. Three documents were checked — 8
October 2024, 1 April 2026 and 17 July 2026 — and all three amend 9.8.8.3. in
the same words. Re-read the section number whenever the adopted document
changes, not only the wording.

**Why the current answer is hard to get, and why that helps.** Ontario's
regulation is free and contains no guard height. The Amendment Document is
free on request and gives (1) and (3.1) only. Sentences (2), (3) and (4) come
from NBC 2020, which the National Research Council owns. The full text no
longer appears on e-Laws at all. State this carefully and without complaint:
it is the reason the product exists.

Sources to cite: O. Reg. 163/24 (<https://www.ontario.ca/laws/regulation/r24163>),
the Amendment Document, <https://www.ontario.ca/page/2024-ontario-building-code>
and <https://www.ontario.ca/page/building-code-updates>. Do not cite a railing
supplier's blog; several give the right number and none is a source a reader
can rely on.

Local copies in `CodeChronicleMapping/data/inputs/pdfs/ontario.ca/`, whose
filenames are load-bearing for CCM and must not be renamed: `301880.pdf`
(Compendium Volume 1, to 16 January 2025, holds 9.8.8.3.), `301881.pdf`
(Volume 2; page 1 is the licence), `301719.pdf` and `301720.pdf` (update
lists).

## What the Compendium licence permits

The terms are in `301881.pdf`, page 1, dated May 2024. This card reports them
and does not give legal advice.

> A non-commercial use is where you provide free access to the 2024 Building
> Code Compendium's material.

- **A free article is the permitted case.** The article is public and costs
  nothing to read.
- **A gated edition is the licensed case.** Putting OBC 2024 behind Pro is a
  commercial use and needs a licence from `buildingtransformation@ontario.ca`.
  That is a separate job.
- **The national text is a separate owner.** The grant covers "Crown
  copyrighted material". NBC 2020 belongs to the National Research Council, so
  sentences (2), (3) and (4) may sit outside it.

Conditions the page meets: reproduce accurately and without modification;
claim no official status; use no Ontario trademark; carry
`© King's Printer for Ontario, 2024. Reproduced with permission.`
`test_it_carries_the_compendium_attribution` pins the string, and
`test_it_quotes_the_2024_article_in_full` pins the reproduction. Nothing can
pin the rest.

**The fallback, if the quoting decision is ever reversed:** quote (1) and
(3.1) from the Amendment Document, which the ministry publishes for anybody,
and state the remaining rules as facts with a citation. A number is a fact;
the sentence carrying it is somebody's writing.

## How it is built

**The corpus text renders live; the analysis is hand-written.** The view asks
the database for the six versions and renders them through the partials the
reading pages use. A transcription never learns that the corpus changed, and
live rendering puts the real attestation band beside the text, which is the
thing no competitor can show.

**The changes render through the comparison page's own components.** Each
section includes `provenance/_compare_pane.html` with the diff
`api.formatters._diff_html_content` produces, above the shared side rows in
`partials/_compare_sides.html`, so `/compare/` and the article give one answer
to "what must be stated about a version before a redline of it is evidence".
The article leaves out the timeline, pairing basis and legend, and supplies
those in prose; each section's foot links to the page that carries them.

**The redline floor applies here too** (`core.compare.REDLINE_FLOOR`). Every
pair clears it — the closest is 1997 against 2006 at 38% — and the corpus
check fails if one drops under. An article that redlined a pair `/compare/`
refuses to redline would show the reader something the product does not do.

**A comparison link is gated on both sides**, so most open the teaser for an
anonymous reader, and the article marks each one rather than letting the
reader find out by clicking.

**The 1997 text is quoted in the article body**, because OBC 1997 is outside
the free tier and the article cannot prove its own argument behind a lock. The
permalinks stay locked and the page says so — that is where a reader decides
to subscribe.

**The article needs no gate exception, and must not add one.**
`core.access` answers one question: may this user open this *edition*. A view
decides and sets `locked_edition_name`; the partials render what the view
says. The article view leaves the flag unset. Do not add a provision-level or
version-level axis to `core/access.py`: that module works because there is one
question to ask, and a second axis is drift in the module written to stop
drift. This article would be its only caller.

**The call to action searches a free date.** It ran at 1 June 1999, which is
OBC 1997 and gated, so the one button sent a first-time reader to a locked
page. It now runs at 1 June 2008, inside OBC 2006.
`test_the_call_to_action_searches_a_free_date` reads the date out of the
rendered link and checks it against the editions the tier names, so moving
either one without the other fails. This is deliberately the opposite decision
from the body text: the article *shows* gated text, because that is the proof;
it must not *send* a reader to a gated page, because that is the invitation.

**The view sets `meta_title`, `meta_description` and `canonical_path`.** Do
not override `{% block title %}` instead. `base.html` resolves the title as
`{% firstof meta_title default_title %}`, and
`templates/partials/_social_meta.html` builds the Open Graph and Twitter tags
from the same two variables, so a block would change the browser tab only and
every forwarded link would carry the generic site card. This article travels
by forwarding. Check the card on a **sent** message; the compose box draws a
text-only preview that looks broken.

**The page carries no form.** One `{% csrf_token %}` attaches a `Set-Cookie`
header, and no shared cache stores such a response.

## Two checks, because one cannot do it alone

Live rendering has a single failure mode: the hand-written analysis says
"800 mm" while the rendered block no longer does.

- `core/tests/test_guard_height_article.py` builds its own corpus and proves
  the **view** surfaces each claim. It cannot prove the shipped corpus still
  says these things, because a fixture that asserts its own data is circular.
- `python manage.py verify_guard_height_article` reads a **real** database and
  fails when a claim stops holding. Run it after `load_edition`, and before
  the article ships or goes out by email.

**The tests pin behaviour, never content.** Four tests asserted phrases from
the article; between them they broke six times on rewordings that left every
claim intact, and caught no defect. A test earns its place by catching an
accident, and prose is changed on purpose. The two strict exceptions are
obligations rather than judgements: the King's Printer attribution and the
full reproduction.

A claim about what the *code* says belongs in `verify_guard_height_article`. A
claim about what the *page* says belongs to the author.

**Do not test the 800 mm allowance with a substring.** Every edition carries
"not more than 1 800 mm above the finished ground level", so `"800 mm" in
html` finds the 1997 allowance in all three editions and reports that it never
went away. `allows_800_mm` anchors on "less than" instead, and the fixture
keeps the 1 800 mm sentence on purpose so a check that falls into the trap
fails in the test rather than in public.

## Rules for the text

- Every figure for 1997, 2006 and 2012 comes from the database. Do not write
  one by hand.
- Every figure for 2024 comes from the regulation or the amendment document,
  and the article names which one. The article must not imply the product
  holds OBC 2024.
- Do not claim e-Laws shows only today's text. See `project_landing_page_rules`.
- Use "provision", not "section". Use "guard", not "railing".

## Still open

- **Put three readings to a building official.** Each reads the text as
  printed, and each is a number somebody could build to.
  1. A landing inside a house needed 1 070 mm from 2014 to 2022. Ask about
     this first: it is the answer most likely to differ from what was built,
     and the page states it without hedging.
  2. From 2022 a guard serving a spiral stair inside a house is 1 070 mm.
  3. A stair inside a house is not a required exit stair, so 920 mm does not
     apply to it.
- **Ask counsel one question.** The page quotes 9.8.8.3. in full under the
  King's Printer attribution, which the Compendium licence permits for
  non-commercial use. Three of the five sentences are NBC 2020. What is left
  is whether reproducing published national text this way needs anything from
  the National Research Council. It is a lawyer's call.
- **Consider restoring the permit-window section.** "Why the 2012 text is
  still live work" came out on 14 August 2026, and with it gone the page never
  says why an old text matters to a live file. O. Reg. 163/24 section 2 keeps
  OBC 2012, as it read on 31 December 2024, in force where a permit was issued
  by that date, or the drawings were substantially complete by it and somebody
  applied by 31 March 2025. Both doors closed in 2025, so do not write that
  OBC 2012 is "still in force" without that limit. What continues is the
  project that already entered: a framing inspection, an occupancy permit, a
  revision or a dispute all read the version of 1 January 2022. The larger
  reason is unbounded — an alteration, an insurance claim or a lawsuit asks
  what the code required on the day the building went up.
- **A voice pass on the prose.** The draft is deliberately plain.
- **Send it to at least 20 people by direct email**, not only to the site. See
  the outreach plan.

## To undo

This card is ops. Removing the article means deleting the page, removing the
name from `STATIC_PAGE_NAMES` in `core/sitemaps.py`, and letting the sitemap
rebuild. An email that is sent cannot be undone.

## Related

- `tasks/complete/landing-page.md` — the copy rules this article obeys.
- `tasks/complete/keywords-from-the-query-first.md` — the search work this
  article's call to action produced.
- `core/insights.py` — the query list. Check it before the next article, in
  case readers ask for another subject more often.
