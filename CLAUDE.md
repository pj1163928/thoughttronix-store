# CLAUDE.md — The ThoughtTronix Store

A server-rendered Django 6 storefront and back office. The PRD (`prd/core-platform.md`) and the plan (`plans/core-platform.md`) record how the core platform was designed and built.

## Commands

- `uv sync` — install dependencies (Python 3.13, managed by uv)
- `uv run python manage.py migrate` — apply migrations
- `uv run python manage.py seed` — reset the database to the demo world
  (destructive, idempotent)
- `uv run python manage.py tailwind runserver` — dev server + Tailwind watch
- `uv run python manage.py tailwind build` — compile production CSS
- `uv run pytest` — run the test suite
- `uv run ruff check .` and `uv run ruff format .` — lint and format

## Project layout

- `config/` — the project package (settings, root urls)
- `accounts/` — custom user model (`accounts.User`, `AbstractUser` + nullable
  `job_title`). Roles are Django's own vocabulary: customers are plain users,
  employees are `is_staff`, the admin is `is_superuser`. No role field, no Groups.
  Also owns `Address` — a customer's saved address book and its CRUD — along
  with the address vocabulary (`US_STATES`, `ADDRESS_FIELDS`, `zip_validator`)
  that `orders` imports for checkout.
- `products/` — catalog (`Category`, `Product`, `Tag`), its back-office CRUD,
  and the `seed` command
- `orders/` — cart, checkout, orders, discount codes, and the back-office
  order and discount management
- `dashboard/` — the staff analytics dashboard
- `PROMPTS.md` — the AI-usage log; append entries, never rewrite history
- `templates/` — project-level templates (`base.html`); app templates live in
  `templates/<app>/`
- `assets/` — static sources; `assets/css/source.css` is the Tailwind input,
  `assets/css/tailwind.css` is compiled output (gitignored, never edit)

## Architecture convention

Logic lives in models and managers; cross-model workflows get a service
module; views stay thin.

Exactly two deliberate deep modules, docstrings and type hints on every
public function: `orders/services.py` (`place_order`) and
`dashboard/queries.py` (the dashboard's aggregations).

Discount codes live in `orders`: `DiscountCode` owns the rules
(`unusable_reason`, `discount_for`), `Cart.discount_code` holds the
applied one, and an `Order` freezes the code's name and the dollars it
took off. `place_order` re-checks eligibility before charging — the cart
box, the cart's own total, the checkout guard and the till all call
`unusable_reason`, never their own copies.

A code covers the whole order or a chosen set of products; `applies_to`
is stored rather than inferred from an empty `products` set, so deleting
a product can only narrow a code, never widen it to the whole store.
`per_user_limit` (default 1) and `total_limit` (default unlimited) cap
redemptions, counted live from the orders — cancelled orders give the
use back, and `counting_since` is how reinstating a code starts its
count over without touching a single order.

The back office lists codes by `?show=active|inactive|all`, where active
means live or scheduled. Typing a code that already exists is answered
with the existing code and a way to reinstate it, not a unique-constraint
error — `DiscountCodeForm.validate_unique` records the clash instead of
rejecting it, and only the create view turns that on.

Saved addresses live in `accounts`: `Address` rows are role-free, and a
role is assigned at checkout, never stored on the address. No order
points at one — `Order` keeps its own flat copy — so deleting an address
can never damage history. Two invariants hold by construction: a
customer with at least one address has exactly one default per role, and
`make_default` is the only thing that moves one (the box that would
clear a default is rendered disabled rather than offered). Checkout
pre-fills from the defaults and swaps a chosen address into the fields
over HTMX, so `CheckoutForm` keeps its twelve required fields and
`place_order` is untouched. `Address.objects.remember` writes back after
the order is placed, outside its transaction, and declines to duplicate
an address the customer already has.

Idiomatic Django throughout: class-based views, model methods, custom
managers/querysets, forms own their validation. Settings read from `.env`
via environs with working defaults — the app must run with no `.env` present.

## Template conventions

- Every page extends the project-level `templates/base.html` (DaisyUI navbar,
  footer motto). DaisyUI theme: `night`, set in `assets/css/source.css` and
  `data-theme` on `<html>`.
- Back-office pages extend `templates/backoffice/base.html` — the staff shell
  with the tab rail; the active tab comes from the view's `section` context
  entry.
- HTMX endpoints render partials from `templates/<app>/partials/_<name>.html` —
  prefixed with an underscore, never extending `base.html`.
- Every list view gets a designed empty state, not a blank page.
- Styling is Tailwind + DaisyUI classes only; no crispy-forms, no JavaScript
  beyond HTMX.

## URL conventions

- Every URL is named; every app has a namespace (`products:catalog`,
  `orders:checkout`).
- Public catalog URLs use slugs (`/products/seraphine-home-hub/`);
  back-office URLs use pks.
- `Product` defines `get_absolute_url`.

## Testing

pytest + pytest-django. Shared fixtures live in the project-level
`conftest.py` — plain fixtures, no factory-boy. Tests never invoke the seed
command. The suite must be green at every phase boundary.