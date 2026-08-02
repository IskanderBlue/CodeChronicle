# Change the Pro price, and stop hard-coding it

**Prefix:** `b-` — medium priority, actionable now. There are no paid
subscribers yet, so nothing must be grandfathered and nothing can break for a
customer. That will not be true for long.

## Two jobs, in this order

### 1. Make the page read the price from Stripe

Today `/pricing/` prints `"29"`, hard-coded in `_pricing_plans()`
(`core/views/pages.py`). Stripe holds the real price. Two numbers for one
fact, and only one of them takes money — so the page can lie and checkout will
still charge correctly, which is the worst version of this bug.

**Read it from the local dj-stripe `Price` row**, not from the Stripe API.
dj-stripe already mirrors it: verified on production 2026-08-01, the row
`price_1Th2woPX18JmcZjWnAlKPLbw` holds `unit_amount: 2900`, `currency: cad`,
`recurring.interval: month`. The `price.updated` webhook keeps it fresh, so a
change in the Stripe dashboard reaches the page with no deploy.

- Look the row up by `settings.STRIPE_PRO_PRICE_ID` — the same setting
  checkout uses, so the page and the charge cannot name different prices.
- Read `unit_amount`, `currency` and `recurring.interval` out of
  `stripe_data`. Divide the amount by 100; Stripe stores cents.
- Show the currency. "$29" is ambiguous to a Canadian buyer and wrong to an
  American one. Print "CAD".
- **Fall back to a constant when the row is missing**, and log it. A pricing
  page that 500s because a webhook has not landed is worse than a stale
  number. Never render a blank price.
- Cache the lookup briefly. The pricing page must not do a database round trip
  per render for a number that changes twice a year.

Test with the row present, the row absent, and a non-monthly interval.

### 2. Change the price

Once the page reads Stripe, the change is a Stripe operation, not a deploy.

1. Create a **new** price on the existing product in the Stripe dashboard.
   Never edit an existing price — Stripe prices are immutable by design, and
   editing is how subscribers get silently re-billed.
2. Set the new price id in the `app_runtime_secrets` bundle in Secret Manager
   as `STRIPE_PRO_PRICE_ID`. It must start with `price_`, not `prod_`. See the
   memory note `project_gcp_prod_config_channel`.
3. `docker restart codechroniclenet-web`.
4. Load `/pricing/` and confirm the new figure. Start a checkout and confirm
   Stripe shows the same figure.
5. Archive the old price in Stripe once nothing references it.

## Also change the offer, not only the number

Raising the price alone makes a worse deal. The higher tier should carry:

- Cross-edition comparison (`tasks/a-general-comparison-ui.md`).
- Exports (`tasks/b-provision-exports.md`).
- A reply from a person when a reader disputes a text
  (`tasks/complete/this-is-wrong-reports.md`).

Those three cards are what make the new price a different product rather than
the same product costing more.

## Grandfathering — not needed now, needed later

There are no paid subscribers today, so skip it. **Write the policy down
anyway**, because the second price change will have customers: existing
subscribers keep their price permanently, and are told so in advance. The
Terms already promise 30 days' notice of a price change
(`templates/terms_of_service.html`). Honour it.

## Done when

- `/pricing/` prints the figure, the currency and the interval from the
  dj-stripe row, with a tested fallback.
- The hard-coded `"29"` is gone.
- The new price is live in Stripe and in the secrets bundle, and checkout and
  the page agree.
