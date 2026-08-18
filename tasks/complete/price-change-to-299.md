# Change the Pro price to $299 CAD/month

**Done on 18 August 2026.** The live price is `price_1U5erJPX18JmcZjW4wIWjMJr`,
$299 CAD monthly. `/pricing/` prints it from Stripe.

## The result

The repository holds **no price at all**. Every later price change is a Stripe
dashboard operation with no deploy.

| Piece | Where |
|---|---|
| The figure, currency and interval | `core/pricing.py`, from the mirrored dj-stripe row |
| Whether Pro can be bought | `core.pricing.checkout_is_configured()` |
| The plan cards | `core.views.pages._pricing_plans` |

Two commits: `c2a2e09` made the page read Stripe; the second removed the last
literal, `FALLBACK_AMOUNT = "29"`.

### There is no fallback figure, and that is the point

A stand-in number looks like safety and is not. After a price change it
advertises the old figure while checkout takes the new one — the original bug,
in the one place this card set out to remove it from.

So `get_pro_price()` answers `ProPrice` **or `None`**, and the page states no
price rather than a wrong one. Two states, and they are not the same state:

| State | Can a reader pay? | What the page shows |
|---|---|---|
| Price id set, mirrored row missing | **Yes.** Checkout sends the id to Stripe, and Stripe is the authority | No figure. "Price shown at checkout" |
| Price id empty | **No.** `create_checkout_session` answers an error | No figure and no purchase button |

`checkout_is_configured()` makes the second test, and the checkout view makes
the same one, so the page cannot offer a button that view refuses.

## The outage, and what it teaches

The secret change took production down for about 25 minutes. Two separate
traps, and the second one is why it lasted.

**1. PowerShell `>` writes UTF-16LE.** The download-edit-upload procedure in
`docs/edit-prod-settings.md` told the operator to redirect with `>`. In
Windows PowerShell 5.1 that writes UTF-16LE with a BOM. `production.py`
`_get_secret` decodes as UTF-8, catches the error and answers `""`, and
`_get_bundled_secret` turns that into `{}`. **Every** key went empty at once,
not only the price id, so `ASSET_SIGNING_KEY` was empty, `core.E001` failed
the system check, and the container never started.

The signature is the byte count: version 9 was 2336 bytes against version 8's
1131, and started `ff fe` rather than `7b`.

**2. `latest` is the most recently CREATED version.** Not the most recently
enabled one. Disabling the bad version did not fall back to the good one — it
made `latest` unreadable, which looks exactly like an empty bundle. The log
said so plainly, and nobody read the log until the second attempt failed:

```
Failed to fetch secret app_runtime_secrets: 400 Secret Version [.../versions/9] is in DISABLED state.
```

**The fix was to add version 10.** Version 9 held the right content in the
wrong encoding, so it was re-enabled, decoded as UTF-16, checked against
version 8 (16 keys either side, one changed value, nothing empty) and written
back as UTF-8.

`docs/edit-prod-settings.md` is rewritten around both traps. It now edits the
bundle over the REST API in base64 — no file, no editor, no console encoding —
and it requires a key count and a byte count **before** the upload. That one
check would have stopped this.

## The claim that was not true

The comparison table sold Pro "Direct API access". The endpoints and the paid
gate in `api/views.py` are real, and `_require_paid_api_access` admits a Pro
reader. But there is **no API key and no token**: authentication is the Django
session, so a subscriber's only route is to replay a browser cookie. The page
also contradicted itself, inviting an enquiry about API access sixty lines
below the row that sold it.

The row is deleted. The promise moved to the top of the roadmap, where it is a
promise.

The roadmap now comes from `PRICING_ROADMAP` and is numbered by position.
Six hand-written blocks each carrying a printed digit meant a reorder was a
renumbering exercise, and a wrong one prints two items numbered 4. Delivered
work leaves the list: "Ontario codes back to 1997" had sat at the top for
months after OBC 1997 went live.

## Grandfathering — the policy, for the next change

This change grandfathered nobody, because there were no paid subscribers. The
policy is recorded because the second price change will have customers:

1. An existing subscriber keeps the price they signed up at, for as long as
   the subscription runs without a break. Stripe does this by itself — a
   subscription holds its own price, and a new price does not touch it.
2. A subscriber who cancels and returns pays the current price.
3. We tell subscribers at least 30 days before a price change reaches them.
   `templates/terms_of_service.html` already promises this. Honour it.

Point 1 is not in the Terms. Putting it there is a public promise plus a
`TERMS_VERSION` bump, and that is a business decision.

## What is not done

- **Nobody has run a real checkout.** The page and the charge read the same
  setting, so they cannot name different prices, but the end-to-end purchase
  is unconfirmed.
- **The old price is not archived.** `price_1Th2woPX18JmcZjWnAlKPLbw`, $29 CAD
  monthly. Archive it in Stripe once a checkout is confirmed. An archived
  price cannot start a new subscription, which is why it is still active.
- **The price lookup is not cached.** The card asked for a brief cache. It is
  one lookup by primary key on a page nobody hammers, and a cache would delay
  the dashboard change this card exists to make immediate. It earns its place
  when `/pricing/` appears in the slow queries.

## Rollback

| Item | Value |
|---|---|
| Old `STRIPE_PRO_PRICE_ID` | `price_1Th2woPX18JmcZjWnAlKPLbw` |
| Method | Add a **new** bundle version holding it. Never disable |
| Deploy needed | None |

## Related

- `core/pricing.py`, `core/views/pages.py`, `core/views/billing.py`,
  `templates/pricing.html`, `core/tests/test_pricing.py`.
- `docs/edit-prod-settings.md` — the bundle procedure, rewritten here.
- `tasks/complete/a-general-comparison-ui.md`,
  `tasks/complete/b-provision-exports.md`,
  `tasks/complete/this-is-wrong-reports.md` — the work that earns the price.
