# Lineage anchor text: name the subject, but only when the subject changes

**Prefix:** `c-` — low priority, actionable now. Small, and it improves the
page for a reader as much as for a crawler.

## The rule

A link's text is a claim about **what the target page is about**. So the text
depends on what the link changes:

- **The link goes to a different provision.** Put the provision id and the
  title in the link. `3.2.5.7. Fire Department Access Routes`. Put the
  version, the dates and the amending regulation beside the link, as plain
  text.
- **The link goes to the same provision at another version.** Leave the link
  as it is. The date and the version number are what the reader chooses
  between, so they stay in the link. Put the title in the link hover.

## Why the rule has two halves

An earlier draft of this card asked for the title in every link. That is wrong
for a version list.

- **The id and the title do not change down an amendment chain.** Every row is
  the same provision. A title in each link makes every link read the same, and
  repeats the page heading directly above the rail. The date is the only fact
  that tells the rows apart, so the date is what the reader clicks.
- **A date is not decoration here.** CodeChronicle answers "what did the code
  say on this date". A rail where no date is clickable argues against the
  product.
- **The version pages are not canonical.** `core/seo.py` makes the highest
  version canonical, and `core/sitemaps.py` emits one URL for each provision.
  So the chain rows point at pages that the site already asks a crawler not to
  rank on their own. Subject words in those links buy nothing.
- **A version number still means nothing.** "v2" is an internal ordinal. It is
  a correct link text only because the date sits next to it.

Where the link goes to a **different** provision, the first half of the rule
holds for the reason the earlier draft gave. A column of `3.2.5.1. 3.2.5.2.
3.2.5.3.` is a table of contents with the contents removed.

## Watch out for

- **The title can change between versions.** So a hover must show the title of
  **the version that link points at**, never the latest title. The viewer nav
  takes the latest title on purpose (`core/views/search.py`), which is safe for
  a nav label and wrong for a per-version hover.
- **A version with no title.** Fall back to the provision id alone. Never
  render an empty link, and never render an empty hover.
- **Space.** The rail is narrow (`--ws-rail`, 19rem). A long title must
  truncate with an ellipsis and keep the full text in a `title` attribute. It
  must not wrap to four lines.
- **Do not measure the rail and write down a width.** Read the token. See the
  memory note `project_working_measure_tokens`.

## Where to change it

### Put the title in the link

| Site | Link today |
|---|---|
| `templates/partials/_viewer_edition_nav.html` | `continues as 3.2.5.7.` |
| `templates/regulation/_permalink_nav_item.html` | `3.2.5.7.`, and `v0` `v1` chips |
| `templates/regulation/provision_permalink.html` (the prev/next pager) | `← 3.2.5.6.` |
| `templates/partials/_cross_ref_list.html` (entry and alternate) | `C 3.2.5.7. v2` |
| `templates/regulation/detail.html` (the clause targets) | `3.2.5.7.` |

The title is already loaded at four of these five sites. `_cross_ref_list.html`
holds `entry.title` and `alt.title` and shows them only in the hover.
`_clause_targets` holds the version row, so `v.title` costs nothing. Only the
lineage links need a new query: `LineageLink` carries a version **number**, not
a version row, so an annotator must stamp the title in the same way
`annotate_lineage_locks` stamps `locked`.

The alternate row keeps its qualifier. Its hover says "Reading we believe was
intended"; the title goes in the link, and the qualifier stays in the hover.

### Put the title in the hover

`templates/partials/_provenance_rail.html` — the base row, each amendment chain
row, the next-version row, **and the lineage rows**. Each hover shows that
version's own title. The hover says "View this version" today, which tells the
reader nothing.

The lineage rows are the exception to the first half of the rule, and the
exception is about the surface, not the link. A lineage row does name a
different provision, so by the rule the title belongs in the link. But this
rail is 19rem wide and every other row in the box is an id and a date. One
line of prose in the middle read as an intruder, and it crowded the track.
The title is worth more here as a hover than as the thing that breaks the
box. The same link on the viewer nav keeps its title on screen, because that
surface is a list of destinations and has the room.

### Change nothing

| Site | Why |
|---|---|
| `core/cross_refs.py` (`linked_html`) | The link text is the code's own citation wording. To rewrite it is to rewrite the regulation. |
| `templates/partials/_result_document_block.html` | "Open full provision record" goes to the version the reader already reads. |
| `templates/partials/_commencement_modal.html` | The next-version link is the same provision at another version. |
| `templates/regulation/chain.html` | The links name regulations, not provision versions. |
| `templates/partials/_version_timeline.html` | The ticks are marks. Their hovers already name the id, the version and the date. |
| `templates/landing.html` (the named-differences band) | The link points at evidence for the difference class beside it. A title stretches a tight row and misstates what the link shows. |

`templates/landing.html` already follows the rule at the specimen link, which
reads `3.2.5.7., "Fire Department Access Routes"`.

## Done when

- Every link to a **different** provision names the provision.
- Every link to **another version of the same** provision keeps its date, and
  names the provision in the hover.
- The hover shows the linked version's title, not the latest title.
- The untitled-version fallback has a test, for the link and for the hover.
- The rail still renders at its narrowest width without wrapping.
