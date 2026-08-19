# LinkedIn: the company page, and your own profile

**Prefix:** `b-` — medium priority, actionable now. About two hours, once.

## Why LinkedIn and not the others

It is the one platform where the buyer — a code consultant, a construction
lawyer, a plans examiner in Ontario — is present in their professional
identity. It is also where somebody checks that a new tool is real before they
trust it with a question that can end in court.

Two jobs, and the personal profile is the more important of the two. People
trust a person. A logo posting about building codes is noise.

## Part 1 — your profile

This is what somebody opens after your outreach email arrives. It has to
answer "is this person real, and do they know this subject" in about eight
seconds.

- **Headline.** Say what you do for whom, not a job title. Something in the
  shape of "Building the searchable record of the Ontario Building Code, 1997
  to today". Avoid "founder" as the first word.
- **Current role.** Add CodeChronicle, linked to the company page once it
  exists, so the two connect in both directions.
- **About.** Three short paragraphs: the problem (a permit was issued in
  1999; which text applies?), what you built, and what it covers today. Use
  the real coverage figures from the site, not round numbers.
- **Featured.** Pin the demo video and the proof article once they exist
  (`tasks/bo-demo-video-and-cpd-talk.md`,
  `tasks/complete/guard-height-article.md`).
- **Photo.** A plain head-and-shoulders photo against a plain wall is enough.
  No photo reads as an empty account.

## Part 2 — the company page

Mostly a credibility artefact: it exists so that a search for "CodeChronicle"
finds something official. Set it up, then leave it.

- Name, logo, and the tagline the site already uses — "The reference of record
  for in-force building code provisions". Do not invent a second tagline.
- Website link to `https://www.codechronicle.ca`.
- Industry: legal services or software. Location: Ontario.
- The About text can be the landing page's opening, shortened.

Claim the page even if you never post to it. A name you do not hold is a name
somebody else can take.

## Part 3 — posting, at a low rate

Do not commit to a schedule you will not keep. An abandoned account with three
posts from last year is worse than no account.

Post only when there is something real:

- The demo video, once.
- The proof article, once.
- Each new edition loaded — this is genuine news to this audience.
- Occasionally, a short observation from the corpus. "The 1997 rule on X read
  like this; here is what replaced it." These are the posts that get shared,
  because they teach something in the post itself.

Post from **your profile**, and let the company page reshare. Personal posts
reach people; company posts largely do not.

## Also worth doing

Join the Ontario building-code and construction-law groups and read them for a
month before saying anything. The same listening rule as
`tasks/co-reddit-listening.md`: answer questions properly, link rarely, say who
you are.

## What is live now (18 August 2026)

The company page exists and is complete.

| Field | Value |
|---|---|
| URL | `linkedin.com/company/codechronicle-ca` |
| Page id | 143347987 |
| Name | CodeChronicle |
| Tagline | The reference of record for in-force building code provisions |
| Website | `https://www.codechronicle.ca` |
| Industry | Information Services |
| Size | 0-1 employees |
| Type | Privately Held |
| Location | Kitchener, Ontario. No street address. |
| Year founded | 2026 |
| Logo | The stacked wordmark: `Code` over `Chronicle`, ink on paper, oxblood rule |
| Overview | The three paragraphs the owner wrote |
| Specialties | Ontario Building Code, historical building codes, building code research, forensic engineering, code compliance |
| Posts | One, from 19 August 2026: the guard-height post, embedded from the profile. LinkedIn offers to post each page edit. Refuse that. |

**To undo:** a page admin deletes the page in Settings, or edits any field in
Edit Page. The public URL can change later. Nothing here is permanent.

## The profile, as at 19 August 2026

| Field | Value |
|---|---|
| Public URL | `linkedin.com/in/robert-lee-codechronicle` (was `robert-lee-11544590`) |
| Headline | Making historical building codes searchable by date - starting with Ontario |
| Position | Founder, CodeChronicle, Kitchener Ontario, from February 2026, current. No employment type. Linked to the page. |
| Featured | The guard-height article, with the site's own title, description and card image |
| Location | Kitchener, Ontario. LinkedIn sets the city from a postal code. |
| About | Replaced 19 August 2026. Five paragraphs: the person, the day job, CodeChronicle, what building it required, the skills line. |

Three things to know before the next edit:

- **The old public URL stops working.** LinkedIn does not redirect it, so any
  link somebody saved to `robert-lee-11544590` is now dead.
- **Adding the position overwrote the headline** with "Founder at
  CodeChronicle". Set the headline again *after* any position edit, and check
  it.
- **The intro card now names CodeChronicle, not Woodbury Solutions.** LinkedIn
  made the new position the current one by itself. The Woodbury position is
  still on the profile; only the intro line changed.

**The About section is about the person, not the product.** The company page
carries the product text. The profile's About covers the whole of the work -
the day job and CodeChronicle - because somebody reads it to answer "who is
this person". The headline, the Founder position and Featured already name
CodeChronicle three times. The previous About is saved as
`about_previous.txt` in the session scratchpad; copy it into `.tmp/` to keep
it.

**The About text names tools, so it can go stale.** It states Surya and
Tesseract, BM25F, Terraform, GCP, Cloudflare Workers and R2. Read it again
when any of those changes. It states no figures, on purpose, so an edition
load does not date it.

**A long text must not be typed key by key.** The `type` action drops
characters - it produced "th flight" and "in-fore" in the Featured
description. Select the field's contents and use `document.execCommand`
with `insertText`, which the editor accepts as real input. Then read the
saved text back.

## The first post, 19 August 2026

The first post is out, from the personal profile.

| Field | Value |
|---|---|
| URL | `linkedin.com/feed/update/urn:li:share:7495731898812649472` |
| Subject | The guard-height article |
| Body | The question, the flight/landing/spiral distinction, five lines of dates and heights, and the article link |
| Image | The article's own height table, captured from `/guard-height-ontario/` at 878x353. The file is deleted; capture it again if you need it. |
| Alt text | The five rows written out as sentences |
| Link preview | None. LinkedIn takes one attachment, and the image took it. |

**LinkedIn attaches a link preview by itself.** A URL in the body makes one,
and that preview takes the single attachment slot. The photo control then
disappears. Remove the preview first, and the photo control comes back.

**The post carries the table twice, and it needs both copies.** The image is
the table as the product draws it. The five text lines are the copy a reader
reads on a phone, because the feed draws a wide image small. LinkedIn re-served
the image at 681x273, down from 878x353, so a larger capture buys nothing.

**The composer is inside a shadow root.** A query on `document` finds no
editor, no dialog and no file input, while the composer is on screen. Find the
shadow host first, then read and write through `host.shadowRoot`.

**Do not let the file picker open.** The photo control fires a hidden
`input[type=file]`, and the OS dialog stops the browser tools. Replace
`HTMLInputElement.prototype.click` first, to catch that input and open no
dialog. Then move the input into the page, so the upload tool can address it.

**LinkedIn rewrites the link.** The body shows `lnkd.in/gcetAchk`, not
`codechronicle.ca`. The link still opens the article, but the post no longer
shows the domain. Put the domain in the words if the reader must see it.

**The company page carries the post as well.** The page cannot repost a member
post: the repost composer offers no way to change the author. Do it from the
page's own composer instead. Open the page as an admin, click Start a post, and
paste the post URL. LinkedIn embeds the original, and the page is the author.

That makes a second post, not a second view of the first one. Reactions and
comments collect on whichever copy the reader meets. Read both when you measure
the reach.

**To undo:** the author deletes the post from the post's own menu. A deleted
post does not come back, and the URL dies with it.

## The cover image: what we know

The cover shows the attestation rail from a real provision page, because the
logo already shows the wordmark and the cover must show the product.

The cover is uploaded and done. What the work taught, for the next time:

- **LinkedIn keeps a 761x129 canvas**, not the documented 1128x191. Read it in
  the browser console: the banner image's `naturalWidth`/`naturalHeight` give
  the stored file, and `getBoundingClientRect` gives the slot on screen.
- **The editor crops, it does not scale.** A 1128x191 upload came back as a
  761x129 window over the same pixels, holding the left two thirds. So the
  editor asks which part to keep whenever the image is larger than the canvas.
- **Do not pad the rail to reach a ratio.** The rail is 6.5:1 and the canvas is
  5.9:1, so filling the canvas needs more height. Padding inside the border
  stretches the "WAS IN FORCE" flag, and the cover then shows a shape the
  product does not draw. Take the extra height from the page around the rail.
- **The rail stacks below 854 px.** Its container query collapses the wide
  layout and drops the timeline, so 854 px is the narrowest useful capture.
- **Capture with the `zoom` action, not `screenshot`.** The `zoom` action saves
  PNG at CSS-native resolution; `screenshot` saves JPEG and the compression
  destroys the mono type and the hairlines.
- **Hide the sticky provenance column** before the capture. It paints over the
  band's right end, and a higher `z-index` does not stop it.

Two browser-tool problems, seen many times: `resize_window` reports success and
does nothing; a click on "Edit cover image" often does nothing and the page
then times out. The owner uploads the file by hand when that happens.

## The About text goes stale

Two sentences in the About text state something that is true today and will
stop being true:

- **The figures.** The coverage range, the edition count, the regulation count
  and the version count all come from the live landing page. A new edition
  changes each one.
- **"Each code edition is also rebuilt a second time."** This holds only while
  every loaded edition has e-Laws consolidations to compare against. An
  edition without them breaks the sentence, and the word "each" must change.

Read both when an edition lands, at the same time as the post this card asks
for. Nothing else reminds you.

## Done when

All three are met, on 19 August 2026.

- The profile headline, About and current role name CodeChronicle.
- The company page exists, is linked from the profile, and links back to the
  site.
- One post has gone out, from the personal profile.

The card stays open for the two texts that go stale: the profile About section,
and the figures in the company page Overview.

## Related

- `tasks/complete/a-social-preview-cards.md` — done. Every link you post here
  carries a title, a description and a card image. Slack's crawler confirms
  it, and LinkedIn reads the same tags.
