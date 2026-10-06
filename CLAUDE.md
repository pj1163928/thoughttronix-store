# CLAUDE.md — The ThoughtTronix Store

A server-rendered Django 6 storefront and back office. The PRD (`prd/core-platform.md`) and the plan (`plans/core-platform.md`) record how the core platform was designed and built.

## Read before…

- writing or running tests → [docs/TESTING.md](docs/TESTING.md)
- touching templates, partials, HTMX, form rendering or static assets →
  [docs/TEMPLATES.md](docs/TEMPLATES.md)
- changing `DiscountCode`, the cart's discount box, or discount management →
  [docs/DISCOUNTS.md](docs/DISCOUNTS.md)
- changing `Address`, the address book, or checkout's address fields →
  [docs/ADDRESSES.md](docs/ADDRESSES.md)
- touching product or order images, `products/images.py`, the Images
  page, or media settings → [docs/IMAGES.md](docs/IMAGES.md)
- changing the wishlist, its product-page button, or anything that could
  expose one customer's wishlist to anyone else →
  [docs/WISHLIST.md](docs/WISHLIST.md)

## Commands

- `uv sync` — install dependencies (Python 3.13, managed by uv)
- `uv run python manage.py migrate` — apply migrations
- `uv run python manage.py seed` — reset the database to the demo world
  (destructive, idempotent)
- `uv run python manage.py tailwind runserver` — dev server + Tailwind watch
- `uv run python manage.py tailwind build` — compile production CSS
- `uv run pytest` — run the test suite; it must be green before you finish
- `uv run ruff check .` and `uv run ruff format .` — lint and format

## Project layout

- `config/` — the project package (settings, root urls)
- `accounts/` — custom user model (`accounts.User`, `AbstractUser` + nullable
  `job_title`), `StaffRequiredMixin` (gates every back-office view), and the
  saved address book. Roles are Django's own vocabulary: customers are plain
  users, employees are `is_staff`, the admin is `is_superuser`. No role field,
  no Groups.
- `products/` — catalog (`Category`, `Product`, `Tag`, `ProductImage`), its
  back-office CRUD and Images page, and the `seed` command (baseline photos
  in `products/seed_images/`)
- `orders/` — cart, checkout, orders, discount codes, and the back-office
  order and discount management
- `wishlist/` — the customer wishlist: one per user, private to its owner,
  HTMX add/remove on the product page
- `dashboard/` — the staff analytics dashboard
- `templates/` — `base.html` and `templates/<app>/`
- `assets/` — static sources; `assets/css/tailwind.css` is compiled output
  (gitignored, never edit)
- `media/` — uploaded and seeded images (`MEDIA_ROOT`, gitignored)
- `PROMPTS.md` — the AI-usage log; append entries, never rewrite history
- `README.md`, `MAP.md`, `REFLECTION.md` — course write-ups; not a source of
  truth for the code

## Architecture convention

Logic lives in models and managers; cross-model workflows get a service
module; views stay thin.

Exactly three deliberate deep modules, docstrings and type hints on every
public function: `orders/services.py` (`place_order`),
`dashboard/queries.py` (the dashboard's aggregations) and
`products/images.py` (image validation, storage and snapshots).

Idiomatic Django throughout: class-based views, model methods, custom
managers/querysets, forms own their validation. Settings read from `.env`
via environs with working defaults — the app must run with no `.env` present
(`.env.example` lists what it may override).

## URL conventions

- Every URL is named; every app has a namespace (`products:catalog`,
  `orders:checkout`).
- Public catalog URLs use slugs (`/products/seraphine-home-hub/`);
  back-office URLs use pks.
- `Product` defines `get_absolute_url`.
