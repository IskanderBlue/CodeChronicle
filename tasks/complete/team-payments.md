# Sell a subscription to a firm, not only to a person

**Done. Built 21 August 2026, deployed 22 August 2026.** A firm buys seats on
one invoice, an administrator manages them, and each seat is a separate login.

The purchase-order path is deliberately not built; see "The invoiced sale".
The last two sections, "Domain capture" and "SSO", are **not in scope**. They
are written down so the answer is ready if a firm asks. Do not build them, and
do not build a part of them.

## The problem it solved

A code consultant works in a firm. The product could sell to one person at a
time, so a firm of six had no supported way to buy six.

Nothing stopped six people buying six subscriptions on one card. What stopped
them was administration: six checkouts from six logins, six invoices, six
renewal dates, no administrator who could see them, and `quantity` hard-coded
to 1. The subscription attached to the **person**. A firm needs it to attach to
the **firm**, with people hanging off it.

## Why this and not seat enforcement

Seat enforcement means technical measures against one login used by several
people: a cap on concurrent sessions, binding a login to a device, refusing a
sign-in from a second city.

Do not build that.

- It fights a reader who has no supported way to do the right thing. Fix the
  supported way first, and most of the sharing stops paying for itself.
- It produces false positives that cannot be told apart from the real thing. A
  consultant on a laptop, a desktop and a phone looks exactly like two people.
- A blocked session is not a sale. Enforcement costs engineering and earns
  nothing; a seat earns a seat.

Keep the one-account-one-person clause in the Terms. It makes sharing a breach
and gives us ground to stand on. That is what a clause is for. It does not need
code behind it to be worth having.

There is a measurement reason too, and it is the stronger one. A shared account
makes six readers look like one very busy reader — which is the shape a bulk
copy makes (`b-reading-ledger-for-the-website.md`). Seats separate those two
signals. Enforcement does not.

## The decisions

1. **A firm gets one invoice and separate logins.** That is the product. A
   firm that wants one login for six people wants a cheaper price, and the
   answer to that is no.
2. **The `Organization` is the dj-stripe subscriber model.** Every
   subscription hangs on an organization, and an individual buyer gets an
   organization of one. This was chosen over keeping `core.User` as the
   subscriber, because one billing path is cheaper to hold than two, and
   because there were no paying customers. The same change costs real money in
   a year.
3. **An organization is created at checkout, not at signup.** A free reader
   has no organization row, so free accounts need no backfill.
4. **An individual never reads the word "organization".** The organization of
   one is named after the person and shows nowhere in the interface. Hide the
   control; do not explain the absence.
5. **A removed member drops to free tier and keeps their history.** The
   account's `SearchHistory` is that person's own work.
6. **A role that reads is a role that is paid for.** The office manager who
   buys and never reads must not cost a seat, and that exemption is a
   **third role**, not a property of being an administrator.

   | Role | Seat | Access | Manages |
   |---|---|---|---|
   | `member` | yes | yes | no |
   | `admin` | yes | yes | yes |
   | `billing` | no | **no** | yes |

   The two-role version of this decision — "an admin consumes no seat" — was
   wrong, and was corrected while building. A firm could make all six people
   admins and pay for nothing. So the exemption comes with no access.
   `Membership.SEAT_ROLES` is one name for both lists, because two lists can
   drift into a free-access role.
7. **The seat check runs at the invite**, never at sign-in. A gate at sign-in
   locks out somebody who did nothing wrong.
8. **Stripe owns the proration.** Adding and removing a seat is a `quantity`
   change on the subscription item. Do not compute a partial month.
9. **No admin sees what a colleague read.** There is no per-seat reading
   report, in any form. An admin who can see which provisions a colleague
   opened is a surveillance feature that we would build for somebody else. If
   a firm asks for it, consider it then. Do not design an answer in advance,
   and do not build a reduced version to be ready.
10. **The access gate keeps one home.** `core.access.user_is_unrestricted` is
    the only thing that answers "may this account read everything".
    **`core/access.py` did not change in this work.** The change happened one
    level below it, in `User.has_active_subscription`.
11. **The search allowance stays per account.** `API_SEARCHES_BEFORE_THROTTLE`
    (200, `api/auth.py`) counts the account, not the organization. Six seats
    are six accounts, and each one is a person who searches. A shared
    allowance makes the service useless to a large firm, which is the opposite
    of the point.
12. **The price comes from Stripe, and no figure lives in the repo.**
    `core/pricing.py` reads one mirrored `Price` row. A per-seat price is a
    second price id, read the same way. The rule that there is **no fallback
    figure** survives without change: when a row does not read, the page
    states no price.
13. **The first seat is Pro. Every seat after it is cheaper.** A team
    subscription is two Stripe line items: `STRIPE_PRO_PRICE_ID` at quantity
    1, and `STRIPE_TEAM_PRICE_ID` at quantity `seats - 1`. Three reasons:
    - A firm of one **is** a Pro subscription. Nothing has to stop somebody
      buying a single discounted seat, because one seat is priced as Pro.
    - A Stripe **tiered** price carries no `unit_amount`, and Stripe leaves
      the `tiers` array out of the `Price` object unless the caller expands
      it. The mirrored row would hold no figure, so the page would print none
      — or the repo would hold a literal, which decision 12 forbids.
    - `Organization.seats_bought` already sums the quantities across items,
      so `1 + (seats - 1)` answers as `seats` with no model change.
14. **Seat count does not separate Team from Custom.** Custom is a purchase
    order, negotiated terms and a quote. A large firm that pays by card buys
    Team; a firm of three that needs a signed agreement buys Custom. Sorting
    the two by head count puts several real firms in the wrong column, so no
    sentence on the page names a seat ceiling.
    `MAX_SELF_SERVE_SEATS` (50) is only a **guard against a typing mistake**,
    and it bounds the seat input and the checkout clamp alone. A low ceiling
    would refuse money a buyer was ready to give: whether a firm can put four
    figures a month on a card is the firm's own constraint, and a firm that
    cannot goes to Custom by itself.
15. **`TEAM_MEMBERSHIPS_ENABLED` sets a reader's membership aside.** A
    development switch, read through `core.teams.team_memberships_enabled`,
    and an interface one only: `access_membership` answers `None` and
    `administered_organizations` answers empty, so the settings page draws no
    team panel and the pricing page reads Team as something to buy. It exists
    so both states are reachable without making and destroying an
    organization each time. It does **not** hide the Team column, does not
    stop a firm buying seats, and does not revoke access — the gate is
    `User.has_active_subscription`, and this is not that gate.

    `conftest.py` pins it on. `base.py` calls `load_dotenv`, so a developer
    who turns it off in `.env` would otherwise turn three tests red.

## The models

All three are in `core/models.py`.

**`Organization`** — `name`, `email`, `created_at`.

`email` is required, and not for our benefit: dj-stripe refuses a subscriber
model that has no `email` attribute. The invoice needs an address anyway.

Two fields are deliberately absent.

- **No `stripe_customer_id`.** dj-stripe's `Customer.subscriber` points at the
  organization, and that is the one link. A second copy can disagree with the
  first. The same reasoning removed the column from `User`; see "What the
  deploy taught".
- **No seat count.** The count is the `quantity` on the mirrored Stripe
  subscription, read through `Organization.seats_bought`. Both payload shapes
  are read — the subscription item, and the older top-level `quantity` — so no
  upgrade of dj-stripe can quietly make it answer zero.

**`Membership`** — `organization`, `user`, `role`, `created_at`, with
`unique_together = ("organization", "user")`. The three roles and what each
one costs are in decision 6. `Membership.SEAT_ROLES` is the single list behind
both `consumes_seat` and `grants_access`.

**`Invite`** — `organization`, `email`, `role`, `lookup`, `hashed_token`,
`invited_by`, `created_at`, `expires_at`, `accepted_at`, `revoked_at`.

Only the hash of the token is stored, and `lookup` holds the first 11
characters in clear to find the row in one indexed query — the shape
`core.models.ApiKey` uses. A link lasts 14 days. A withdrawn link, a spent
link and an invented link all answer `None`, so none of them tells the holder
that any of the others exists.

## The gate

`User.has_active_subscription` answers True when **either** of these holds:

1. `self.pro_courtesy` is True.
2. An organization that this user has a `Membership` in has a `Subscription`
   with `stripe_data__status` in `["active", "trialing"]`.

The branch that tested a personal `Customer.subscriber` link did not survive
this work. Every subscription now reaches a person through a `Membership`,
including the buyer's own.

The answer is cached on the request object. This property runs on gated page
renders, and nearly all traffic is crawlers, so an uncached join would make
every provision page pay for it.

## What was built, and where it lives

| File | What it holds |
|---|---|
| `core/models.py` | `Organization`, `Membership`, `Invite`, and the rewritten `User.has_active_subscription` |
| `core/teams.py` | The seat operations: who joins, who may manage, what an invitation costs |
| `core/views/teams.py` | Invite, withdraw, remove, and the page where a person takes a seat |
| `core/views/billing.py` | Checkout with a seat count, and the portal, both keyed to the organization |
| `core/pricing.py` | `get_team_price` and `team_checkout_is_configured`, the per-seat price read the same way as Pro |
| `core/migrations/0057…`, `0058…`, `0060…` | The tables, the subscriber move, the dropped column |
| `templates/partials/_team.html` | The administrator panel in Settings |
| `templates/team_invite.html` | What an invited person sees before they take the seat |
| `core/management/commands/link_stripe_customers.py` | The repair, and the invoiced sale |
| `core/tests/test_teams.py` | The gate, the seat count, the invitation, and who may press what |
| `core/tests/test_link_stripe_customers.py` | That the repair writes nothing without `--apply`, and never guesses |

Two settings are new: `STRIPE_TEAM_PRICE_ID` and
`DJSTRIPE_SUBSCRIBER_MODEL_MIGRATION_DEPENDENCY`. Both must be re-resolved in
`production.py`; `base.py` reads `os.environ`, which the container does not
have.

## What the deploy taught

Three findings worth keeping. The step-by-step deploy plan is spent and is not
repeated here.

**dj-stripe's subscriber model rewrites recorded history rather than producing
a migration.** The column is declared `to=DJSTRIPE_SUBSCRIBER_MODEL`, read from
settings when the migration module is **imported**. So model state and
migration state agree, `makemigrations` reports nothing, and the foreign key in
the database goes on pointing at `users`. A deploy looks clean and fails on the
first write. `core.0058` is hand-written for exactly this reason.

The same mechanism forces the migration order. Once the setting changes, the
already-applied `djstripe.0001` declares a dependency on `core.0057`, and any
deploy carrying both meets `InconsistentMigrationHistory` before touching
anything. `0057` was therefore applied by an operator command with
`DJSTRIPE_SUBSCRIBER_MODEL=core.User`, and the ordinary deploy applied `0058`.
The feature cannot be split at the commit instead:
`User.has_active_subscription` queries `customer__subscriber__memberships`, so
a release carrying the models without the setting breaks the access gate on
every page. **A fresh database needs neither step**, which is why the suite
never saw any of it.

**A migration that changes rows in a table it also alters must drop the
constraint first.** The first deploy failed applying `0058`:

```
psycopg.errors.ObjectInUse: cannot ALTER TABLE "djstripe_customer"
because it has pending trigger events
```

Django creates a foreign key as `DEFERRABLE INITIALLY DEFERRED`, so the
`UPDATE` that repoints `subscriber_id` queues a deferred trigger event for each
row it touches, and Postgres refuses to `ALTER` a table holding pending events.
`SET CONSTRAINTS ALL IMMEDIATE` is not the alternative: it would run the
deferred checks while the column already names an organization and the key
still names a user. The key cannot survive the rewrite in any order, so it goes
first and the rows change with no key in place. The reverse carried the same
fault, and a rollback is the worst moment to meet it.

**An empty test database cannot tell you so.** 1452 tests passed and the deploy
still failed, because with no customer row there is no `UPDATE` and no pending
event. Production held one row, and one is enough. The fix was rehearsed on a
database built the way production was, with a customer row present.

**The failure shipped nothing.** The workflow migrates before it replaces the
container, so the site went on serving the previous image and `0058` stayed
unapplied. That property is why the order exists.

## The double-subscription case

A person already pays for themselves. The firm then buys a team plan and
invites that person. Both subscriptions must not run.

At the invite acceptance, do all three of these:

1. Find the personal subscription, and say so plainly.
2. Offer one action: end the personal subscription at the period end, and take
   the seat now. Stripe issues the credit. Do not compute one.
3. Never end a paid subscription without the person's click.

A person can belong to two organizations, their own and the firm's. The gate
answers True when **any** organization has an active subscription, so this is
safe to read. Only the second charge is wrong.

## The invoiced sale

A firm that pays on a purchase order needs no new product. Make the customer
and the subscription in the Stripe dashboard with
`collection_method="send_invoice"` and `days_until_due=30`, and put the
purchase-order number on the invoice. Stripe sends it and marks it paid.

The one thing that customer cannot have is the metadata naming an
organization, because it never passed through our checkout. So nothing links
it, and the firm pays while nobody can read. `link_stripe_customers` is what
supplies the answer:

```bash
python manage.py link_stripe_customers --customer cus_ABC --organization 7 --apply
```

That command is also the repair for any customer that missed all three
automatic links (the success page, the webhook, and `core.0058`). With no
arguments it reads what Stripe already holds and links what resolves:

```bash
python manage.py link_stripe_customers            # report only
python manage.py link_stripe_customers --apply    # write the links
```

Three rules it keeps:

- **It writes nothing without `--apply`.** A link grants every edition to
  everybody in the organization, which is the same weight as the destructive
  commands here.
- **`--organization` writes the id back to Stripe.** A link that existed only
  in our database would be lost by a rebuild of the mirror.
- **A customer that names nothing is left alone**, and named in the report. A
  guessed link hands a stranger every edition; a missing one locks somebody
  out, which a person notices and fixes.

What is **not** built is the self-serve version: a quote request, an order
form to sign, stored payment terms, a tax identifier. That waits on a firm,
because what they ask for decides the shape. Until then the pricing page
points at `support@codechronicle.ca`, which is where a firm too large for the
seat band already writes.

## If the dj-stripe tables have to be rebuilt

Stripe is the source of truth and dj-stripe is a mirror, so
`python manage.py djstripe_sync_models Product Price Customer Subscription`
pulls the mirror back. The link to a person comes back too, because
`create_checkout_session` writes `metadata={"django_user_id": ...}` onto the
Stripe customer. Keep writing that field.

Until the resync finishes, a subscriber reads as free tier and the pricing page
states no price. Both are the fail-safe behaviour working. Only the dj-stripe
webhook event records do not come back, and they record *when* Stripe told us
something, not the state itself.

To read the link as it now stands:

```sql
SELECT c.id AS customer, o.id AS organization, u.email
FROM djstripe_customer c
JOIN organizations o ON o.id = c.subscriber_id::bigint
JOIN organization_memberships m ON m.organization_id = o.id AND m.role = 'admin'
JOIN users u ON u.id = m.user_id;
```

## What is left

Nothing blocks a sale. Two things wait on a firm.

- **The self-serve quote and order flow**, when a firm asks for terms. The
  invoiced sale itself is possible today.
- **The first real seat purchase.** Nobody has bought seats yet, so the
  two-line-item subscription and the portal's quantity control are proven in
  test mode only.

Record the first firm that asks, including how many people. It decides nothing
about the shape now, but it is the first evidence of whether the seat count
people buy matches what was built for.

## Domain capture, if a firm asks

Domain capture answers "which organization does this person belong to". It is
not SSO, which answers "how does this person prove who they are". Build either
without the other.

Two parts.

**Verify the domain.** The admin enters `example.com`. Generate a random
string, and the admin proves control in one of two ways: a DNS TXT record that
holds the string, or a confirmation link sent to a role address (`admin@`,
`postmaster@`, `webmaster@`). The DNS record is the stronger proof, because it
proves control of the domain and not of one mailbox. Store the domain, the
date and the method on the `Organization`.

**Match at signup, and let an admin approve.** Somebody signs up with an
address at a verified domain. Show them that the firm is here, and let them
ask to join. An admin approves, and the approval creates the `Membership`.

Do **not** let a matching address join by itself. Decision 7 puts the seat
check where a person is added. With no approval step there is no such place,
so the eleventh person joins a ten-seat plan.

Three traps:

- **Refuse the free mail domains** at the verification step. `gmail.com`,
  `outlook.com`, `yahoo.com`, and the rest. Somebody who verifies `gmail.com`
  captures a large part of the user base. Keep an explicit list.
- **Do not match a subdomain** unless the firm verifies that subdomain too.
- **An existing account is not captured.** A person who already has an account
  joins by accepting an invite, not because their address matched.

## SSO, if a firm asks

**Prefer OIDC. Refuse SAML until somebody insists.** django-allauth is already
the socialaccount framework here, so an OpenID Connect provider is
configuration, not a new library. Microsoft Entra ID speaks OIDC, and that is
what a mid-size Canadian firm runs. OIDC also has **no certificate to install**
— it reads the signing keys from the provider's JWKS endpoint and rotates them
by itself. The X.509 certificate, its expiry, and the per-customer metadata URL
are SAML costs, and they are what makes SSO expensive to keep.

If SAML does get built, use the library's signature validation. Never write
that check. A missed signature or audience test is an authentication bypass.

**SSO changes the seat rule, and this is the part to plan for.** SSO brings
just-in-time provisioning: the identity provider says a person exists, and the
account is created at first sign-in. That path never passes the invite, which
is where decision 7 puts the seat check. So a JIT sign-in must create a
`Membership` only when a seat is free, and otherwise tell the person to ask
their administrator for a seat. That is a second home for the seat check, and
it is the only place where the enterprise tier changes the seat model instead
of sitting beside it.
