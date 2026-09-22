# Implementation Plan: The ThoughtTronix Store — Core Platform

*Companion to `prd/core-platform.md`. The PRD owns the requirements; this plan owns the sequence. Where a task says "per the PRD," the PRD's wording is authoritative — do not improvise alternatives.*

---

## Phase 1 — Tracer Bullet: One Product, Every Layer

**Goal:** A styled catalog page displays one product, served by a fully wired toolchain — proof that every layer works before any real feature is built.

**Tasks:**
1. Initialize the project with `uv`: Django 6.0, pytest-django, environs, django-tailwind-cli (version-pinned), Ruff and pre-commit as dev dependencies.
2. `startproject config .` — settings read from `.env` via environs with working defaults (the app must run with no `.env` file). `.gitignore` covers the SQLite file, compiled CSS, `.env`, and caches.
3. Create the `accounts` app with the custom user model per the PRD (`AbstractUser` + nullable `job_title`), set `AUTH_USER_MODEL`, **before the first migration is generated**. This ordering is non-negotiable — a custom user cannot be retrofitted.
4. Create the `products` app with `Category` and a minimal `Product` (name, slug, price, FK Category). Register both in the Django admin.
5. One view, one template: the catalog page lists products, extends a project-level `base.html` carrying the DaisyUI navbar and the footer motto ("Your Thoughts, Our Business").
6. Wire Tailwind + DaisyUI via django-tailwind-cli; confirm watch mode and build both work.
7. Configure Ruff per the PRD's code-quality block; install pre-commit hooks; add the GitHub Actions workflow (`ruff check`, `ruff format --check`, `pytest`).
8. Author the initial `CLAUDE.md`: project layout, the architecture convention line (*logic lives in models and managers; cross-model workflows get a service module; views stay thin*), template and URL conventions from the PRD, and the phase discipline from this plan's header.
9. One test: the catalog page returns 200 and displays a product created in test setup. Begin the project-level `conftest.py` with its first fixture.

**Verification.** *Automated:* pytest green (one test), Ruff clean, CI passes on push. *Manual:* create a superuser, add "Seraphine Home Hub" in the admin, see it styled on the catalog page.

**Out of bounds:** tags, search, pagination, seed command, auth pages, cart, HTMX. One product on one page is the whole ambition.

---

## Phase 2 — The Catalog, Complete

**Goal:** The full public catalog: browse, search, filter, paginate — with the demo world seeded.

**Tasks:**
1. Complete the `Product` model per the PRD's data model: description, tagline, `is_available`, M2M `Tag`, `get_absolute_url`.
2. Custom manager: `Product.objects.available()`.
3. Product detail page at slug URLs; category browse pages; app-namespaced named URLs throughout (`products:detail`).
4. Search (`icontains` over name and description), tag filtering, category filtering — composing via querystring per the PRD. Pagination at 12.
5. Designed empty states: no search results, empty category.
6. The `seed` management command, v1: destructive and idempotent per the PRD; 6 categories, tags, 30–35 products with brand-voice copy, the three demo logins (`admin`, `employee`, `customer`) and 8–10 background customers. No carts or orders yet — those arrive with their phases.
7. Admin list displays and search fields for catalog models.

**Verification.** *Automated:* model behavior tests (manager, `__str__`, slug uniqueness), view smoke tests, search/filter/pagination tests, seed-runs-twice idempotence test. *Manual:* seed, browse all categories, search "Seraphine," filter by a tag, walk pages 1→2→3, view the Defense page and confirm the SoulSear Mark I is appropriately recalled.

**Out of bounds:** anything requiring login. The catalog is a public reading room.

---

## Phase 3 — Accounts and Access

**Goal:** Visitors become customers: signup, login, logout, and an auth-aware layout.

**Tasks:**
1. Signup (username and password with confirmation — Django's stock `UserCreationForm` fields, no email), login, logout — Django auth views plus a signup view in `accounts`, templates styled to match. Signup redirects to the login page.
2. Navbar reflects auth state (greeting + logout vs. login/signup links).
3. Messages framework wired into `base.html`; "You have signed out" as the first message per the PRD's messages convention.
4. `conftest.py` grows: a customer fixture and a staff fixture.

**Verification.** *Automated:* signup creates a non-staff user; login/logout round-trip; auth pages return 200. *Manual:* sign up a fresh account, sign out, sign in as `customer`.

**Out of bounds:** cart (next phase), any staff-only screens, password reset email flows.

---

## Phase 4 — The Cart, with HTMX

**Goal:** Signed-in customers manage a cart without page reloads — the core's three HTMX interactions, and only those three.

**Tasks:**
1. Vendor HTMX as a version-pinned static file; include it from `base.html`.
2. `Cart` (one per user) and `CartItem` (unique per cart–product pair) per the PRD; cart total and line-total logic as model methods.
3. Add-to-cart from catalog and detail pages: HTMX button swap plus navbar badge update. Anonymous users are redirected to login (PRD story 7). Duplicate adds increment quantity. Unavailable products are rejected.
4. Cart page: line items, quantities, totals, designed empty state. Quantity change and line removal as HTMX partial swaps.
5. Template partials under `templates/orders/partials/_*.html` per the PRD's template rules (cart lives in the `orders` app).
6. Extend seed: the `customer` demo login gets a live cart.

**Verification.** *Automated:* cart arithmetic, uniqueness/increment behavior, unavailable rejection, HTMX endpoints return partials not full pages, anonymous add redirects. *Manual:* as `customer`, add a Home Hub from the catalog — badge ticks without reload; change a quantity; remove a line; empty the cart and admire the empty state.

**Out of bounds:** checkout. The cart page's checkout button may exist but leads nowhere yet.

---

## Phase 5 — Checkout and Orders

**Goal:** The validated checkout and the order lifecycle — the phase that builds both the declarative-validation showcase and the codebase's deepest module.

**Tasks:**
1. **Validators first:** `orders/validators.py` (`validate_card_number` via Luhn, `validate_expiry`) with their unit tests, before any form or view exists. Pure functions, tested against the PRD's standard test numbers.
2. `CheckoutForm` exactly per the PRD's declarative-validation section — field types, field arguments, `validators=[...]`; no `clean_*` methods, no `clean()`.
3. `Order` and `OrderItem` per the PRD's data model: status `TextChoices`, denormalized addresses and line prices, `card_last4` only, order-number property.
4. `orders/services.py` — `place_order(cart, user, checkout_data, *, coupon_code=None)`: transactional, all-or-nothing, empties the cart, coupon seam accepted and ignored with a marked comment. Docstrings and type hints on every public function.
5. Checkout view (thin: validate → `place_order`), confirmation page with order number, order history (most recent first, empty state) and order detail — both filtered to `request.user` in the queryset.
6. Extend seed: 40–60 orders across the trailing six months, spread across background customers; the `customer` demo login gets visible history.

**Verification.** *Automated:* the PRD's coverage priorities 1–3 in full — validators, form rules, service atomicity and denormalization — plus owner-only access to orders. *Manual:* check out with `4242 4242 4242 4242` and succeed; retry with a corrupted digit and watch the field error appear with data preserved; try a past expiry; confirm history shows the order and the detail page shows purchase-time prices.

**Out of bounds:** coupon model or checkout coupon field (the seam stays dormant), address book, back-office order screens.

---

## Phase 6 — The Back Office

**Goal:** Employees run the store from dedicated staff screens.

**Tasks:**
1. Staff-only area with its own layout region; every view gated by an `is_staff` mixin.
2. Product CRUD (create, update, delete) with full form validation per PRD story 22; category and tag management.
3. Order list, filterable by status; order detail; status advancement per the `TextChoices` workflow.
4. Success messages on saves per the messages convention.
5. Navbar exposes the back office to staff only.

**Verification.** *Automated:* every staff URL returns 302/403 for anonymous and plain customers; CRUD round-trips; status transitions persist. *Manual:* as `employee`, create a new MindSync accessory, edit its price, mark a product unavailable and confirm it vanishes from the public catalog; advance an order placed → shipped.

**Out of bounds:** the analytics dashboard — the back office navigation may link to it, dead, for one phase.

---

## Phase 7 — Dashboard and Final Polish

**Goal:** The analytics dashboard, and the finishing pass for the core platform.

**Tasks:**
1. `dashboard/queries.py`: the aggregation functions (revenue, order count, average order value, revenue over time, top products by revenue), docstrings and type hints, tested against small hand-computed datasets including the empty case — queries and tests before the view.
2. Dashboard view with period selector (30 / 90 / all time, default 30). Revenue-over-time renders as a styled table or CSS-bar visualization — no JavaScript chart library (the PRD's JS boundary is HTMX only).
3. Designed empty state for a store with no orders.
4. Final seed pass: verify the dashboard reads well at all three periods; confirm idempotence.
5. `README.md`: setup (`uv sync` → `migrate` → `seed` → `tailwind runserver`), the demo-login table, the command inventory, one paragraph on repo layout.
6. `CLAUDE.md` refinement pass: reconcile with everything actually built; add the empty `PROMPTS.md` with its instructions.
7. Sweep: every list view has its empty state; Ruff clean repo-wide; CI green; every public function in the two deep modules documented.

**Verification.** *Automated:* full suite green; dashboard query tests including empty case; CI passes. *Manual:* sign in as `employee`, read the dashboard at all three periods and confirm the numbers are plausible against the seeded orders; then the full journey — fresh clone, README steps only, from nothing to browsing the store in under five minutes.

**Out of bounds:** nothing new. This phase adds no features — it finishes the ones that exist.

---
## Phase 7 — Discount codes (2026-09-21)

Added after the core platform, against the seam the PRD reserved for it.
See the PRD amendment for the design and for why the seam's signature
changed.

1. `orders.DiscountCode` + `DiscountCodeQuerySet` — `is_live`, `status`,
   `label`, `discount_for(cart)`, `live()`, `find(raw)`; codes normalise
   to capitals on save and on lookup.
2. `Cart` — a nullable `discount_code` FK; `total()` becomes the amount
   due and the old sum-of-lines behaviour becomes `subtotal()`, so
   `place_order` and all three templates are discount-aware unchanged.
3. `Order` — `discount_code_used` (SET_NULL), the frozen `discount_code`
   string, `discount_amount`, and a `subtotal` property.
4. `ApplyDiscountForm` — the deliberate exception to `CheckoutForm`'s
   no-`clean_*` rule; a specific sentence for every way a code can fail.
5. Cart page HTMX apply/remove; checkout re-checks in `dispatch` before
   card entry; `form_valid` turns `place_order`'s `ValueError` backstop
   into a message instead of a 500.
6. Back office: a fifth tab, list/create/edit, and retire as its own POST
   action — `is_active` is not on the edit form.
7. Dashboard: `discounts_given()` and a fourth stat tile; `top_products`
   relabelled "by gross sales", since it sums lines before order-level
   discounts.

**Verification.** 40 new tests, including the window's exact boundaries,
the percent/amount quantity asymmetry, over-clamping, rounding, and the
headline guarantee — retire and re-price a used code, then assert the
order is untouched. Manually exercised against seeded data end to end.

**Out of bounds:** stacking multiple codes, per-customer usage limits,
category-scoped codes (a nullable `category` FK is the additive next
step), and allocating order-level discounts across order lines.
