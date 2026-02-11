# Stripe / Pricing Implementation Plan

## Overview

Complete the Stripe subscription integration for CodeChronicle. The foundation is in place (dj-stripe installed, pricing page, checkout view, rate limiting); this plan covers the remaining gaps.

### Current State (already done)

- `dj-stripe` dependency installed, `djstripe.urls` mounted at `/stripe/`
- Settings: `STRIPE_LIVE_SECRET_KEY`, `STRIPE_TEST_SECRET_KEY`, `DJSTRIPE_FOREIGN_KEY_TO_FIELD`, `DJSTRIPE_USE_NATIVE_JSONFIELD`
- `User` model: `stripe_customer_id`, `pro_courtesy`, `has_active_subscription` property
- `RateLimitMiddleware` enforces tiers (anon: 1/day, auth: 3/day, pro: unlimited)
- `pricing` view renders 2 plans (Free $0, Pro $29/mo)
- `create_checkout_session` view creates a Stripe Checkout session
- `pricing.html` template with plan cards and checkout form

### Key Design Decisions

- Rely on dj-stripe's webhook ingestion rather than building custom webhook views
- Keep `has_active_subscription` as a dynamic property (no denormalization needed at this scale)
- Use Stripe Customer Portal for cancel/update billing (avoids building PCI-sensitive UI)

---

## Phase 0 — Config & Env Vars (~30 min)

### 0.1 Add missing env vars and settings

**Files:** `.env.example`, `code_chronicle/settings/base.py`

Add to `.env.example`:
```env
STRIPE_PRO_PRICE_ID=price_...
DJSTRIPE_WEBHOOK_SECRET=whsec_...
```

Add to `base.py` under Stripe section:
```python
DJSTRIPE_WEBHOOK_SECRET = os.environ.get("DJSTRIPE_WEBHOOK_SECRET", "")
STRIPE_PRO_PRICE_ID = os.environ.get("STRIPE_PRO_PRICE_ID", "")
DJSTRIPE_SUBSCRIBER_MODEL = "core.User"
```

### 0.2 Run dj-stripe migrations

```bash
python manage.py migrate
# Optional for dev: python manage.py djstripe_sync_models
```

---

## Phase 1 — Fix Checkout Flow (~2 hr)

### 1.1 Link Checkout to a real Stripe Customer

**File:** `core/views.py` → `create_checkout_session`

Currently uses `customer_email=` only, which creates orphan Stripe customers not linked to the Django user.

**Changes:**
- If `request.user.stripe_customer_id` exists, reuse it
- Otherwise create a Stripe Customer, store `stripe_customer_id` on the user
- Pass `customer=` (not `customer_email=`) to Checkout
- Pass `client_reference_id=request.user.id` and metadata for reconciliation
- Use `settings.STRIPE_PRO_PRICE_ID` instead of `os.environ.get()` with hardcoded fallback

```python
@login_required
@require_POST
def create_checkout_session(request):
    import stripe
    stripe.api_key = settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY

    price_id = settings.STRIPE_PRO_PRICE_ID
    if not price_id:
        return render(request, "pricing.html", {"error": "STRIPE_PRO_PRICE_ID not configured"})

    customer_id = request.user.stripe_customer_id
    if not customer_id:
        cust = stripe.Customer.create(
            email=request.user.email,
            metadata={"django_user_id": str(request.user.id)},
        )
        customer_id = cust["id"]
        request.user.stripe_customer_id = customer_id
        request.user.save(update_fields=["stripe_customer_id"])

    checkout_session = stripe.checkout.Session.create(
        customer=customer_id,
        client_reference_id=str(request.user.id),
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        allow_promotion_codes=True,
        success_url=request.build_absolute_uri(reverse("core:stripe_success"))
            + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=request.build_absolute_uri(reverse("core:stripe_cancel")),
    )
    return redirect(checkout_session.url, code=303)
```

### 1.2 Add success/cancel endpoints

**Files:** `core/urls.py`, `core/views.py`, new templates

Add URLs:
```python
path("stripe/success/", views.stripe_success, name="stripe_success"),
path("stripe/cancel/", views.stripe_cancel, name="stripe_cancel"),
```

**Success view behavior:**
- Require login
- Retrieve the Checkout Session by `session_id` query param
- Verify it belongs to this user (via `customer == request.user.stripe_customer_id` or `client_reference_id`)
- Show "Pro enabled shortly" message (don't rely on immediate webhook timing)
- Optionally kick off a dj-stripe sync for that customer/subscription

**Cancel view:** simple redirect back to pricing with a "Checkout cancelled" banner.

---

## Phase 2 — Webhooks (~2 hr)

### 2.1 Confirm webhook endpoint + secret

dj-stripe provides a webhook endpoint under the `/stripe/` include. In Stripe Dashboard, configure a webhook to:
```
https://yourdomain.com/stripe/webhook/
```

Set `DJSTRIPE_WEBHOOK_SECRET` in `.env`.

### 2.2 Signal handlers for Customer ↔ User reconciliation

dj-stripe already handles webhook ingestion and persists Stripe objects (Customer, Subscription, Invoice). You only need small "glue" via signals.

**New file:** `core/stripe_handlers.py`

```python
from djstripe import webhooks

@webhooks.handler("customer.subscription.created")
def handle_subscription_created(event, **kwargs):
    # Reconcile Customer.subscriber ↔ User
    # Sync stripe_customer_id if needed
    pass

@webhooks.handler("customer.subscription.deleted")
def handle_subscription_cancelled(event, **kwargs):
    # dj-stripe handles status update automatically
    # Optional: send notification email
    pass

@webhooks.handler("invoice.payment_failed")
def handle_payment_failed(event, **kwargs):
    # Optional: send payment failed email
    # Optional: set a flag for UI banner
    pass
```

**Register in `core/apps.py` → `ready()`:**
```python
def ready(self):
    import core.stripe_handlers  # noqa: F401
```

### 2.3 Handle payment failure UX

- Update pricing/settings UI to show a banner like "Payment issue — update billing details" when a subscription exists but is not `active`/`trialing`
- The "Manage billing" button (Phase 3) handles resolution

---

## Phase 3 — Customer Portal (~1 hr)

### 3.1 Add portal endpoint

**Files:** `core/views.py`, `core/urls.py`

```python
@login_required
@require_POST
def create_customer_portal_session(request):
    import stripe
    stripe.api_key = settings.STRIPE_TEST_SECRET_KEY if settings.DEBUG else settings.STRIPE_LIVE_SECRET_KEY

    customer_id = request.user.stripe_customer_id
    if not customer_id:
        return redirect(reverse("core:pricing"))

    portal_session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=request.build_absolute_uri(reverse("core:user_settings") + "#account"),
    )
    return redirect(portal_session.url, code=303)
```

Add URL:
```python
path("stripe/portal/", views.create_customer_portal_session, name="stripe_portal"),
```

### 3.2 Add subscription card to settings page

**File:** `templates/settings.html` (Account tab, above Sign Out)

Add a "Subscription" card:
- If `request.user.has_active_subscription`: show "Pro (Active)" + "Manage billing" button (POST form to `core:stripe_portal`)
- Else: show "Free" + link to `/pricing/`

---

## Phase 4 — Pricing Page Polish (~1 hr)

### 4.1 Make pricing page context-aware

**Files:** `core/views.py` → `pricing`, `templates/pricing.html`

- Authenticated + active Pro → Pro card shows "Manage" button (links to portal)
- Authenticated + no Pro → Pro card shows "Upgrade to Pro" button
- Anonymous → Pro card shows "Sign up to upgrade" CTA (since checkout requires login)
- Remove hardcoded `price_id` fallback from views

### 4.2 Clean up price_id handling

Remove `os.environ.get("STRIPE_PRO_PRICE_ID", "price_placeholder")` from the pricing view context — the template doesn't need it since checkout is handled server-side via POST.

---

## Phase 6 — Testing & Admin (~1 hr)

### 6.1 Stripe test mode verification

- Create test user
- Purchase Pro via Checkout
- Confirm:
  - `user.stripe_customer_id` saved
  - dj-stripe `Customer` exists with `subscriber=user`
  - `Subscription` exists with status `active`/`trialing`
  - `user.has_active_subscription` returns `True`
  - Rate limit becomes unlimited

### 6.2 Webhook verification

```bash
stripe listen --forward-to localhost:8000/stripe/webhook/
```

Trigger test events (checkout completed, invoice paid, subscription deleted) and confirm DB updates via dj-stripe.

### 6.3 Admin visibility

- Ensure dj-stripe models visible in Django admin (helpful for debugging)
- Add `pro_courtesy`, `stripe_customer_id` to User admin list display

---

## Risks & Guardrails

- **Webhook delivery delays:** Don't promise immediate Pro access on the success page; show "may take a minute" and provide a "refresh status" link
- **Customer duplication:** Using `customer_email` alone causes duplicates in Stripe; always use `customer=` once you have an id
- **Environment mismatch:** Ensure `STRIPE_LIVE_MODE` / keys / webhook secret match the mode you're testing

## When to Consider the Advanced Path

Switch to a more elaborate design (local `Subscription` model, explicit entitlements table, background reconciliation jobs) only if:
- You add multiple plans/add-ons/seat-based pricing
- You need per-feature entitlements beyond "Pro vs Free"
- Webhook reliability becomes a real operational issue
- You see performance issues from per-request subscription queries
