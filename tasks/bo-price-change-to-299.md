# Change the Pro price to $299 CAD/month

**Prefix:** `bo-` — medium priority ops, actionable now. There are no paid
subscribers yet, so nothing must be grandfathered and nothing can break for a
customer. That will not be true for long.

## Status

**The code half is written.** The repository holds no price at all now.

- `c2a2e09` — the page reads the price from the mirrored dj-stripe row.
- 18 August 2026 — the last figure, the fallback amount, is gone. **Written,
  not yet deployed.**

**One deploy, then no more.** The fallback removal must reach production
before the secret changes; see step 2. After that the repository holds nothing
that a price change can make wrong, so every later change is a Stripe
operation alone.

**The Stripe half is open.** See "2. Change the price" below.

## 1. Make the page read the price from Stripe — done

`core/pricing.py` reads the local dj-stripe `Price` row, keyed by
`settings.STRIPE_PRO_PRICE_ID` — the same setting
`core.views.billing.create_checkout_session` passes to Stripe. One setting
means the page and the charge cannot name different prices. dj-stripe keeps
the row current through the `price.updated` webhook, so a dashboard change
reaches the page with no deploy and no network call on the render path.

The page prints the currency beside the figure. "$29" is ambiguous to a
Canadian buyer and wrong to an American one.

### There is no fallback figure, and that is the point

The first version kept `FALLBACK_AMOUNT = "29"`, on the argument that a stale
number beats a page that errors. That argument fails at exactly this moment.
After the price moves, the stand-in advertises $29 while checkout takes $299 —
the original bug, in the one place the card set out to remove it from. A
number in the repository is a number free to disagree with Stripe.

So `get_pro_price()` answers `ProPrice` **or `None`**. `None` means "we cannot
state the price", and the page then states no price.

Two states, and they are not the same state:

| State | Can a reader pay? | What the page shows |
|---|---|---|
| Price id set, mirrored row missing | **Yes.** Checkout sends the id to Stripe, and Stripe is the authority | No figure. "Price shown at checkout", above the purchase button |
| Price id empty | **No.** `create_checkout_session` answers an error | No figure and no purchase button. The feature comparison stays |

`checkout_is_configured()` makes the second test, and it is the same test the
checkout view makes. The page cannot offer a button that view refuses.

## 2. Change the price — open

The target is **$299 CAD, monthly** (`unit_amount: 29900`, `currency: cad`,
`recurring.interval: month`).

**Deploy the fallback removal before you touch the secret.** On today's
production code the stand-in figure is still live, so between the secret
change and the webhook mirroring the new row, the page says $29 while checkout
takes $299. That gap may be empty, but it is the one day it can happen. The
new code renders "Price shown at checkout" instead, and charges correctly
throughout. The deploy is safe on its own: against the current price id the
new code reads the existing $29 row and prints $29, so nothing changes until
the secret does.

1. Create a **new** price on the existing product in the Stripe dashboard.
   Never edit an existing price. Stripe prices are immutable by design, and an
   edit is how subscribers get re-billed silently. Create it in **live** mode:
   `core.views.billing._use_stripe_key` picks the key by `DEBUG`, so a
   test-mode id fails every production checkout.
2. Deploy. Then load `/pricing/` on production. It must still say **$29**.
   That proves the new code is live and nothing else moved.
3. Set the new price id in the `app_runtime_secrets` bundle in Secret Manager
   as `STRIPE_PRO_PRICE_ID`. It must start with `price_`, not `prod_`. See
   `docs/edit-prod-settings.md` and the memory note
   `project_gcp_prod_config_channel`.
4. `docker restart codechroniclenet-web`.
5. Load `/pricing/` and confirm **$299 CAD/mo**. Start a checkout and confirm
   Stripe shows the same figure.
6. Destroy the superseded secret versions, keeping the one from before step 3
   until step 5 passes. Secret Manager bills each **active** version; the
   state it reports is lowercase, so read the column rather than filter on it.
7. Archive the old price in Stripe once nothing references it.

### How to undo it

Record the values before you change them. Nothing else remembers.

| Item | Value to restore |
|---|---|
| `STRIPE_PRO_PRICE_ID` | `price_1Th2woPX18JmcZjWnAlKPLbw` ($29 CAD/month, live on 2026-08-01) |
| Secret Manager | The bundle version number that held it |
| Stripe | Do not archive the old price until the new one is confirmed. An archived price cannot start a new subscription |

A rollback is step 3 and step 4 again with the old id. No deploy either way.

### Watch the webhook

Between step 3 and the `price.updated` webhook landing, the new id has no
mirrored row. `/pricing/` then shows "Price shown at checkout" rather than a
wrong number, and checkout charges $299 correctly. That window is safe, but it
is visible. If it lasts, the webhook is the thing to look at.

## What earns the new price

The card required three pieces of work before the rise, so that $299 buys a
different product rather than the same product at a higher price. All three
have shipped:

- `tasks/complete/a-general-comparison-ui.md` — cross-edition comparison.
- `tasks/complete/b-provision-exports.md` — the four exports.
- `tasks/complete/this-is-wrong-reports.md` — a reply from a person when a
  reader disputes a text.

## Grandfathering — not needed now, needed later

There are no paid subscribers today, so this change grandfathers nobody.
**The policy is written down anyway**, because the second price change will
have customers:

1. An existing subscriber keeps the price they signed up at, for as long as
   the subscription runs without a break. Stripe does this by itself — a
   subscription holds its own price, and a new price does not touch it.
2. A subscriber who cancels and returns pays the current price. The old price
   is archived by then, so this needs no decision.
3. We tell subscribers at least 30 days before a price change reaches them.
   `templates/terms_of_service.html` already promises this. Honour it.

Point 1 is not in the Terms today, and putting it there is a public promise
plus a `TERMS_VERSION` bump. That is a business decision, not a code one.

## Deliberately not done

**The price lookup is not cached.** The earlier card asked for a brief cache.
It is one indexed lookup by primary key on a page nobody hammers, and a cache
would delay the dashboard change this whole card exists to make immediate. A
cache earns its place when `/pricing/` shows up in the slow queries.

## Done when

- [x] `/pricing/` prints the figure, the currency and the interval from the
  dj-stripe row.
- [x] Every hard-coded price is gone, the fallback included.
- [x] The page says nothing about the amount when Stripe cannot be read, and
  withholds the purchase when nobody can take the money.
- [ ] The new price is live in Stripe and in the secrets bundle, and checkout
  and the page agree.
- [ ] The old price is archived.

## Related

- `core/pricing.py`, `core/views/pages.py`, `core/views/billing.py`,
  `templates/pricing.html`, `core/tests/test_pricing.py`.
