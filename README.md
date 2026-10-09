# The ThoughtTronix Store

*Your Thoughts, Our Business.*

A server-rendered Django 6 storefront and back office for the world's most
beloved consumer neural technology: browse the catalog, fill a cart, check
out through a fully validated form, and — if you're staff — run the store
from the back office, analytics dashboard included.

## Getting started

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). No Node.js —
Tailwind runs as a standalone binary.

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py seed
uv run python manage.py tailwind runserver
```

Then open <http://127.0.0.1:8000/>. From clone to browsing the store, this
takes about two minutes.

## Demo logins

The `seed` command creates a fixed demo world — the same one every run:

| Username   | Password      | Who they are                                                  |
| ---------- | ------------- | ------------------------------------------------------------- |
| `admin`    | `admin123`    | Superuser: everything below, plus the Django admin at `/admin/` |
| `employee` | `employee123` | Staff: the back office (products, orders, dashboard)           |
| `customer` | `customer123` | A customer with order history and a live cart                  |

Sign in with the username or the email (`admin@example.com` and so on).
Two-factor authentication is mandatory for superusers, and `seed` enrols
nobody, so **after every `seed`, signing in as `admin` lands on two-factor
setup**. Scan the QR code with any authenticator app (Google
Authenticator, 1Password, Authy…) and keep the recovery codes it shows.
`employee` and `customer` can turn two-factor on from their Account page
if they want to. If the admin's phone and recovery codes are both lost,
`uv run python manage.py reset_2fa admin` turns it off from the server.

Email goes to the console, so verification and password-reset links are
printed in the `runserver` window. `customer`'s email starts unverified,
so the "resend link" prompt can be demoed.

## Commands

| Command                                     | What it does                             |
| ------------------------------------------- | ---------------------------------------- |
| `uv sync`                                    | Install dependencies                     |
| `uv run python manage.py migrate`            | Apply database migrations                |
| `uv run python manage.py seed`               | Reset the database to the demo world (destructive, idempotent) |
| `uv run python manage.py reset_2fa <username>` | Turn two-factor off for one account, superusers included |
| `uv run python manage.py tailwind runserver` | Dev server + Tailwind watch              |
| `uv run python manage.py tailwind build`     | Compile production CSS                   |
| `uv run pytest`                              | Run the test suite                       |
| `uv run ruff check .`                        | Lint                                     |
| `uv run ruff format .`                       | Format                                   |

## Repo layout

`config/` is the project package (settings, root URLs); the apps are
`accounts` (custom user model, the Account area, two-factor and the
security audit log, with the security rules in `accounts/security.py` —
see `docs/ACCOUNTS.md`), `products` (the public catalog and its
back-office CRUD), `orders` (cart, checkout, orders — with the
`place_order` service in `orders/services.py`), `wishlist` (each
customer's private wishlist), and `dashboard` (staff analytics, with the
aggregations in `dashboard/queries.py`). Project-level
templates live in `templates/`, static sources in `assets/`. The product
requirements are in `prd/`, the phase-by-phase build plan in `plans/`, and
`PROMPTS.md` is where AI usage on this codebase gets logged.
