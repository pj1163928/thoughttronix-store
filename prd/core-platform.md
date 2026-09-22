# PRD: The ThoughtTronix Store — Core Platform

*Commissioned by ThoughtTronix Product Management. "Your Thoughts, Our Business."*

---

## Problem Statement

ThoughtTronix manufactures the world's most beloved consumer neural technology — the Seraphine assistant line, the MindSync implant series, and an accessories catalog our legal team describes as "extensive." Yet we have no way to sell any of it online. Customers who wish to purchase a MindSync Duo currently cannot; they can only want one, which our analytics team notes is not a revenue event.

Internally the situation is worse. Employees managing the catalog have no tool for adding or editing products. Nobody can see which orders exist, because orders do not exist. Leadership has requested a revenue dashboard and has been shown, in response, a whiteboard.

We need a web storefront where customers can browse the catalog, maintain a cart, and place orders through a real checkout — shipping address, billing address, payment card, every field validated — and review their purchase history. And we need a staff back office where employees manage products, oversee orders, and see how the business is performing.

## Solution

A server-rendered Django web application with two faces:

**The storefront (customers and visitors).** A browsable product catalog organized by category, with search, tag filtering, and pagination. Visitors browse freely; creating an account unlocks the cart and checkout. Checkout is a single form — shipping address, billing address, and card details.

**The back office (staff).** Employees manage the product catalog through dedicated CRUD screens (not the Django admin), view and update customer orders, and see an analytics dashboard summarizing revenue, order volume, and top products.

Pages are enhanced with HTMX where a full-page reload would feel clumsy — most visibly the cart. The visual language is Tailwind + DaisyUI throughout.

## User Stories

**Visitor (not signed in)**

1. As a visitor, I can view a paginated product catalog (12 per page) showing each product's name, image, category, price, and tagline.
2. As a visitor, I can view a single product's detail page — at a readable URL like `/products/seraphine-home-hub/` — with full description, tags, price, and availability.
3. As a visitor, I can browse products by category.
4. As a visitor, I can search products by name and description text.
5. As a visitor, I can filter the catalog by tag, and combine filtering with search.
6. As a visitor, I can sign up for a customer account with a username and password (no email — Django's stock signup fields).
7. As a visitor, I am prompted to sign in when I attempt to add a product to a cart.

**Customer (signed in)**

8. As a customer, I can sign in and sign out.
9. As a customer, I can add a product to my cart from the catalog or the product detail page, without a full page reload, and see my navbar cart badge update.
10. As a customer, adding a product already in my cart increments its quantity rather than creating a duplicate line.
11. As a customer, I can view my cart with line items, quantities, per-line totals, and a cart total — and when my cart is empty, I see a designed empty state, not a blank page.
12. As a customer, I can change a line item's quantity or remove it, without a full page reload.
13. As a customer, I cannot add an unavailable product to my cart.
14. As a customer, I can check out on a single checkout page where I enter a shipping address, a billing address, and payment card details.
15. As a customer, every checkout field is validated. Errors appear beside their fields and everything I typed is preserved.
16. As a customer, submitting a valid checkout always succeeds: the order is created, my cart is emptied, and I see a confirmation with an order number like `TT-2026-00042`.
17. As a customer, my order records show my card only by its last four digits ("card ending 4242"); the full number and CVV are never stored.
18. As a customer, I can view my order history, most recent first.
19. As a customer, I can view a past order in detail: line items with prices *as of purchase time*, the shipping address I used, and the order's status.
20. As a customer, I cannot view another customer's orders or cart.

**Employee (staff)**

21. As an employee, I can access a back-office area that customers and visitors cannot reach.
22. As an employee, I can create, edit, and delete products — including assigning a category and tags and marking a product unavailable — with validation on all fields (price must be positive, name required, slug unique).
23. As an employee, I can create and edit categories and tags.
24. As an employee, I can view a list of all orders, filterable by status, and view any order's detail.
25. As an employee, I can advance an order's status (placed → shipped → delivered, or cancelled).
26. As an employee, I can view an analytics dashboard showing total revenue, order count, and average order value for a selected period (30 days, 90 days, or all time; default 30), revenue over time, and top products by revenue — with a designed empty state before any orders exist.

**Admin**

27. As an admin, I have everything an employee has, plus access to the Django admin for direct data management, including user accounts.

**Any developer (including future ones)**

28. As a developer, I can reset the database to a known demo state with a single command, at any time, in under a minute.

## Implementation Decisions

**Stack.** Django 6.0, server-rendered. SQLite (file gitignored). Package management with `uv` (`pyproject.toml` + `uv.lock` committed). Tailwind CSS + DaisyUI via `django-tailwind-cli` (standalone binary — no Node.js; compiled CSS gitignored). HTMX vendored as a version-pinned static file. Plain Django forms styled with DaisyUI classes — no crispy-forms. Settings read from `.env` via `environs`, with defaults such that the app runs with no `.env` present.

**Project layout.** Project package `config`. Apps: `accounts`, `products`, `orders`, `dashboard`.

**User model.** Custom user (`accounts.User`, subclassing `AbstractUser`) from the first migration, with one extra field: nullable `job_title`. Authentication is **username-based** — Django's default, unchanged. Roles use Django's own vocabulary and nothing else: customers are plain users; employees are `is_staff=True`; the admin is `is_superuser`. No role field, no Groups.

**Data model (8 domain models).** `User`; `Category`; `Product` (FK Category, M2M Tag, `SlugField`, `is_available`, price as `DecimalField`); `Tag`; `Cart` (one per user) and `CartItem` (unique per cart–product pair); `Order` and `OrderItem`. The Order carries: FK user, status, immutable total, the order's shipping and billing address as **flat denormalized fields** (an order is a snapshot; it must not change if a customer later edits a saved address), and `card_last4` — never the card number, never the CVV. `OrderItem` denormalizes product name and unit price at purchase time — order history must not change when the catalog does. Order status is a `TextChoices` enum: `PLACED`, `SHIPPED`, `DELIVERED`, `CANCELLED`. Order number is a model property formatted `TT-<year>-<zero-padded pk>`, not a stored field.

**Checkout: a showcase of declarative validation.** Checkout is one page, one POST, and the `CheckoutForm` is the codebase's reference example of Django's declarative validation — every rule visible at the field declaration, in the style of data annotations:

- Field types validate: `EmailField` for email.
- Field arguments validate: `required` (the default), `max_length`, `ChoiceField` restricting state to the 50 US states + DC.
- The `validators=[...]` list carries the rest: `RegexValidator` for ZIP (`^\d{5}(-\d{4})?$`) and CVV (`^\d{3,4}$`), and two custom validators defined in `orders/validators.py` — `validate_card_number` (a Luhn checksum; standard test numbers such as `4242424242424242` and `4111111111111111` pass) and `validate_expiry` (MM/YY, must be the current month or later).

Custom validators are plain functions that raise `ValidationError` — small, pure, and unit-testable. No `clean_*` methods and no cross-field `clean()` on this form. A valid form always results in a successful order — no payment gateway, no processor, no network, ever. The checkout view is thin: validate form → `place_order`.

**Architecture.** Idiomatic Django: class-based views, model methods, custom managers/querysets (e.g., `Product.objects.available()`), forms own their validation. Exactly two deliberate deep modules: (1) `orders/services.py` exposing `place_order(cart, user, checkout_data, *, coupon_code=None)` — creates the order and order items with denormalized prices and addresses, empties the cart, all-or-nothing in a transaction; the `coupon_code` parameter is a marked extension seam that the core accepts and ignores; (2) `dashboard/queries.py` holding the aggregation queries (`annotate`, `Count`, `Sum`) behind the analytics dashboard. Both deep modules carry docstrings and type hints on every public function — their interfaces are the product. Views stay thin everywhere.

**Access control.** Back-office views gate on `is_staff` via mixins. Customer-owned resources (cart, orders) are always filtered to `request.user` in the queryset, never fetched by bare primary key.

**URLs.** Every URL is named; every app has a namespace (`products:detail`, `orders:checkout`). `Product` defines `get_absolute_url`. Public catalog URLs use slugs (`/products/seraphine-home-hub/`); back-office URLs use pks.

**Templates.** Project-level `templates/` holds `base.html` (navbar with cart badge, messages block, footer carrying the corporate motto). Each app keeps its templates in `templates/<app>/`. Every HTMX endpoint renders a partial from `templates/<app>/partials/_<name>.html` — partials are prefixed with an underscore and never extend `base.html`. Every list view has a designed empty state (empty cart, no search results, no orders yet, dashboard before first sale).

**HTMX inventory (core).** Exactly three interactions, all in the cart flow: add-to-cart (button swap + navbar badge update), cart line-item quantity change, cart line-item removal. Everything else is conventional full-page navigation. Additional HTMX belongs to future features, not this build.

**Messages convention.** `django.contrib.messages` for full-page POST outcomes (order placed, product saved, signed out); inline HTMX swaps carry their own feedback for cart actions. Never both for the same action.

**Pagination and search.** `paginate_by = 12` on the catalog. Search is simple `icontains` over name and description; tag and category filters compose with search via querystring parameters.

**Product images.** No file uploads and no media handling in the core platform (this arrives later). Each product displays a static placeholder image chosen by category; the `Product` model carries no image field.

**Seed data.** A destructive, idempotent management command: `manage.py seed`. Wipes domain data and rebuilds the identical demo world: 30–35 products across 6 categories (Home Assistants — the Seraphine line, Neural Implants — the MindSync line, Neural Wearables, Accessories, Defense — home of the SoulSear directed-energy line, and Legacy Products), 40–60 orders spread across the trailing six months so the dashboard has a real time axis, and fixed demo logins documented in the README: `admin`/`admin123` (superuser), `employee`/`employee123` (staff, job title "Junior Thought Curator"), `customer`/`customer123` (with order history and a live cart), plus 8–10 background customers with orders. Product copy carries the brand voice ("She's always listening. In a good way."). Written as readable ORM Python — the seed file doubles as documentation.

**Code quality.** Ruff for linting and formatting (`extend-select = ["I", "DJ", "UP", "B"]`, migrations excluded, line length 88), enforced by pre-commit hooks and CI (GitHub Actions: `ruff check`, `ruff format --check`, `pytest`).

## Testing Decisions

pytest + pytest-django throughout

Test data comes from shared pytest fixtures in a project-level `conftest.py` (a user, a staff user, a category with products, a cart with items). No factory-boy — plain fixtures keep the dependency surface small and the test setup readable. Tests never invoke the seed command.

Coverage priorities, in order:

1. **`orders/validators.py`** — the pure functions first: `validate_card_number` accepts known test numbers (`4242424242424242`, `4111111111111111`) and rejects corrupted ones; `validate_expiry` rejects past dates and accepts the current month.
2. **`CheckoutForm`** — each declarative rule rejects bad input with a field-specific error; a fully valid form passes.
3. **`orders/services.py`** — order created with correct denormalized prices and addresses; cart emptied; transaction atomicity (a failure mid-way leaves no partial order); unavailable products rejected; only `card_last4` persisted.
4. **Access control** — staff-only views return 302/403 to non-staff; customers cannot reach other customers' orders or carts.
5. **Model behavior** — managers (`available()`), `__str__` methods, cart total arithmetic, order-number formatting, cart-item uniqueness/increment.
6. **`dashboard/queries.py`** — aggregations verified against small hand-computed datasets, including the empty case.
7. **View smoke tests** — every URL returns 200 for the right class of user; HTMX endpoints return partials.
8. **The seed command** — runs twice without error, produces the same counts both times (the idempotence contract).

No browser automation, no JavaScript testing: HTMX endpoints are tested as Django views returning partial HTML.
---

## Amendment — discount codes (2026-09-21)

The `coupon_code` seam described above was activated, and reshaped in the
process. The code does not arrive as a string argument to `place_order`:
customers apply it on the cart page, so it is held on `Cart.discount_code`
and `place_order` reads it from the cart it was already given. The
parameter was removed rather than kept beside the real path, so there is
one source of truth for which code an order is using.

`DiscountCode` lives in `orders`. It discounts either the whole order or
one product's line (`product` is null for the former), by a percentage or
a fixed amount. A percentage is proportional and scales with the quantity
bought; a fixed amount means what it says and comes off once, capped at
what it is discounting. Codes are retired, never deleted, and an `Order`
freezes the code's name and the dollars it took off — so retiring or
re-pricing a code cannot rewrite an order that already used it.

Liveness is checked in two places and implemented in one: the cart page,
for a message the customer can act on, and inside `place_order`, because
a code can expire between the two.
