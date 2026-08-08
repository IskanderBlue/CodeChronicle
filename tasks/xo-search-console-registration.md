# Register with Google Search Console and Bing Webmaster Tools

**Prefix:** `xo-` — ops, gated on a trigger. **The trigger is a crawler
reading the sitemap.** Both engines report a queued status, and no step here
can make that happen sooner. The card becomes actionable again on 2026-08-11,
or on the day either engine reports a count.

It was `po-` first, gated on a push to prod, because a submitted sitemap that
returns 404 starts the property at a deficit. **That gate lifted on
2026-08-07:** `/robots.txt` returns 200 and names the sitemap, and all three
sitemap URLs return 200 on production. A second gap closed on 2026-08-08, when
plain HTTP stopped answering 522; that one is written up below, because a
Domain property makes it this card's problem and nobody else's. It ran as
`ao-` for one day, on 2026-08-08, which is the day both registrations
happened.

## Status — both registered, waiting on the crawlers

**Both halves are done, on 2026-08-08.** Nothing here needs a person today.

| | Property | Sitemap | Reported status |
|---|---|---|---|
| Google | Domain, verified by TXT | `https://www.codechronicle.ca/sitemap.xml` | **Couldn't fetch** |
| Bing | Imported from Google | Carried across | **Processing** |

Both statuses mean the same thing: the file is accepted and unread. Neither
is a failure, and neither reports an attempt that went wrong.

Bing needed only the *verification*, which was already done. It never waited
on Google's sitemap fetch.

Two dates to come back on, for both:

- **2026-08-11.** Google must read "Success" and Bing must leave
  "Processing". If Google still reads "Couldn't fetch", press **See details**,
  and work the section below on what that status means.
- **2026-09-08.** The first read that says anything. Compare the URL count
  each reports to 3,225, and work the four reports listed under "What to
  read".

## Why

Search Console is the only place that tells you what people searched for,
which of our pages they saw, and which they did not click. `/insights/` shows
what people typed into our own box. Search Console shows what they typed into
Google and never reached us. The two lists together decide what to write next.

Bing matters for a second reason: Bing's index feeds ChatGPT search and
Microsoft Copilot. An unindexed site is invisible to both.

## Before you start

- The sitemap must return 200 on production: `/sitemap.xml`,
  `/sitemap-pages.xml`, `/sitemap-provisions.xml`.
- `/robots.txt` must return 200 and name the sitemap.
- **Plain HTTP must redirect, not fail.** See the section below.
- You need access to the DNS records for `codechronicle.ca`. Cloudflare holds
  them: `lana.ns.cloudflare.com` and `buck.ns.cloudflare.com`.

All of these were confirmed on 2026-08-08. The sitemap held 8 page URLs and
3,225 provision URLs. Write the provision count down before you submit,
because the "Done when" test compares it to a count Google reports days later.

## Plain HTTP answered 522, and a Domain property makes that matter

Found on 2026-08-08, while confirming the list above. Every plain-HTTP
request returned Cloudflare's 522:

```
http://codechronicle.ca/                -> 522
http://www.codechronicle.ca/            -> 522
http://www.codechronicle.ca/sitemap.xml -> 522
```

HTTPS was unaffected, so no reader met this. **The cause:** Cloudflare passed
port 80 through to the origin, and the origin answers only on 443. A 522 means
the edge reached the origin and the origin did not answer; it is not a DNS
fault and not a proxy fault.

**Why this card owns it.** A Domain property tells Google that `http://` is
yours. Google then crawls the `http://` forms it finds in old links and in
other people's pages, and it records each 522 as a server error. Repeated
server errors make Google reduce the crawl rate for the whole property. You
would register the site and start it at a deficit — the deficit the old `po-`
gate existed to prevent.

**The correction**, applied on 2026-08-08: Cloudflare → SSL/TLS → Edge
Certificates → **Always Use HTTPS**. The edge writes the 301 itself, so the
origin's port 80 can stay shut and the VM needs no change and no deploy.

**To undo:** switch **Always Use HTTPS** off in the same place. That restores
the 522, so undo it only to reproduce the fault.

**Verified after the change.** All four HTTP forms return 301 and land on 200.
The redirect keeps the path and the query — `?q=…&d=…` arrives intact, which
matters because a CodeChronicle search link carries the whole search in the
address. The 301 carries `Server: cloudflare`, which proves the edge answers
and the origin is never contacted.

## Steps — Google

1. Open `search.google.com/search-console`. Sign in.
2. Add a property. Choose **Domain**, not URL prefix. A Domain property covers
   `www`, non-`www`, `http` and `https` together. A URL-prefix property covers
   one of them, and you will forget which.
3. Google shows a TXT record. Add it in Cloudflare: DNS → Records → Add
   record → TXT, Name `@`, Content the string Google gives you.
4. Do not delete the record later. Google re-checks it.
5. Wait for verification. This takes up to one hour.
6. Open **Sitemaps**. Enter the **whole URL**, with the scheme:
   `https://www.codechronicle.ca/sitemap.xml`. Submit. Google reads the index
   and follows both sections.
7. Wait. A new property shows useful data after some weeks, not some days.

**Step 6 rejects a shorter form**, with "Invalid sitemap address. Please enter
a valid path to a sitemap in your site." A Domain property covers four hosts,
so its field paints no grey prefix and Google will not pick a host for you.
`www.codechronicle.ca/sitemap.xml` has no scheme and does not parse. The
message says "path", which invites `/sitemap.xml`; that fails for the same
reason. Google has fetched nothing at this point, so the complaint is about
the string and never about the file.

**Use `www`, not the apex.** `https://www.codechronicle.ca/sitemap.xml`
answers 200 directly. The apex answers 301 to it, and the index names `www`
inside. A submitted apex form makes Google resolve a redirect before it reads
anything, and Google warns on that.

## "Couldn't fetch" — what it means, and when to worry

Search Console shows this the moment a sitemap is accepted. It means Google
has queued the read and not done it, and it is the normal first state. It does
**not** mean Google tried and failed.

Do nothing for three days. If it still reads "Couldn't fetch" after that,
press **See details** and read the reason. Check these three, in this order:

1. Fetch the URL yourself and confirm it returns 200. Do this first, because
   it is the only cause that is ours.
2. Confirm the submitted string names `www` and carries `https://`. A stored
   apex form still resolves, but it reports oddly.
3. Confirm Cloudflare is not challenging Googlebot. Cloudflare → Security →
   Events, filtered to the sitemap path. A bot rule that questions an unknown
   agent will block a crawler as readily as a scraper.

If all three pass, wait. A new property with no history is read slowly, and
there is no control that makes Google hurry.

**Checks 1 and 3 already passed on 2026-08-08**, an hour after the
submission. A request carrying Googlebot's user agent received 200 and real
content from `/robots.txt`, both sitemaps and a provision page — no challenge,
and no reduced body. So a "Couldn't fetch" that survives to 2026-08-11 is
Google's queue and not our edge. Re-run the check anyway; a Cloudflare rule
can be added after this date.

## Steps — Bing

Run these as soon as the Google property verifies. They do not wait for the
sitemap fetch.

1. Open `bing.com/webmasters`.
2. Sign in **with the same Google account** that owns the Search Console
   property. Bing offers Google sign-in for this reason.
3. Use **Import from Google Search Console**. Grant the permission Google
   asks for. This carries the verification across and takes about two minutes.
4. Read the host Bing recorded. Bing has no equivalent of a Domain property,
   so it takes one host from the import. It must be
   `https://www.codechronicle.ca`. Add that host by hand if Bing took the
   apex, because the apex only redirects.
5. Confirm the sitemap came across. Submit
   `https://www.codechronicle.ca/sitemap.xml` by hand if it did not. Enter the
   whole URL here too.

**A different account signs in and finds nothing.** The import reads the
properties that account owns. An empty list means the wrong account, and not
a failed import.

**Expect the import to fail, and retry it.** On 2026-08-08 it asked for the
sign-in several times, then failed to connect to Google, then failed again
during the import itself. The same steps succeeded on a later try, with
nothing changed. So a failure here is Bing's, and it is not a sign that the
Google side is wrong. Retry before you investigate anything.

Bingbot is not blocked at our edge. A request carrying bingbot's user agent
received 200 and real content from `/robots.txt`, both sitemaps and a
provision page on 2026-08-08. `robots.txt` names no per-agent rule, so
bingbot reads the same `User-agent: *` block that every crawler reads.

## What to read, and how often

Check monthly, not daily. The four reports that matter:

- **Performance → Queries.** What people searched. Sort by impressions with a
  low click rate: those are pages whose title or description is not
  answering the question. Fix the copy, not the ranking.
- **Pages → Indexed / Not indexed.** How many provision pages Google kept.
  A large "Crawled — currently not indexed" group means the pages look
  duplicate; check the canonical tags (`core/seo.py`).
- **Sitemaps.** Discovered against submitted. A large gap is a crawl problem.
- **Experience → Core Web Vitals.** Only act if it reports a failure.

## Done when

- Both properties are verified.
- The sitemap is submitted in both, and each reports the URL count it read.
- The count Google read is close to 3,225, the provision count on 2026-08-08.
  Re-count first if an edition has loaded since that date.

## Related

- `core/sitemaps.py`, `templates/robots.txt`, `core/seo.py`.
- `tasks/complete/co-json-ld-structured-data.md`.
