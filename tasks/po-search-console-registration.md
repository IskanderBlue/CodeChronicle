# Register with Google Search Console and Bing Webmaster Tools

**Prefix:** `p-` — high priority, actionable now, but only **after** the
sitemap is live on production. A submitted sitemap that returns 404 starts the
property at a deficit.

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
- You need access to the DNS records for `codechronicle.ca`.

## Steps — Google

1. Open `search.google.com/search-console`. Sign in.
2. Add a property. Choose **Domain**, not URL prefix. A Domain property covers
   `www`, non-`www`, `http` and `https` together. A URL-prefix property covers
   one of them, and you will forget which.
3. Google shows a TXT record. Add the record to the DNS for
   `codechronicle.ca`. Do not delete the record later — Google re-checks it.
4. Wait for verification. This takes up to one hour.
5. Open **Sitemaps**. Enter `sitemap.xml`. Submit. Google reads the index and
   follows both sections.
6. Wait. A new property shows useful data after some weeks, not some days.

## Steps — Bing

1. Open `bing.com/webmasters`.
2. Use **Import from Google Search Console**. This carries the verification
   across and takes about two minutes.
3. Confirm the sitemap came across. Submit it manually if it did not.

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
- The count Google read is close to the count in `/sitemap-provisions.xml`.

## Related

- `core/sitemaps.py`, `templates/robots.txt`, `core/seo.py`.
- `tasks/c-json-ld-structured-data.md`.
