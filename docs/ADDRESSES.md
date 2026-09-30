# Saved addresses

Saved addresses live in `accounts`: `Address` rows are role-free, and a
role is assigned at checkout, never stored on the address. No order
points at one — `Order` keeps its own flat copy — so deleting an address
can never damage history.

## Invariants

A customer with at least one address has exactly one default per role, and
`make_default` is the only thing that moves one (the box that would clear a
default is rendered disabled rather than offered). Both hold by
construction.

## Checkout

Checkout pre-fills from the defaults and swaps a chosen address into the
fields over HTMX, so `CheckoutForm` keeps its twelve address fields (all
required except the two `line2`s) and `place_order` is untouched.
`Address.objects.remember` writes back after the order is placed, outside
its transaction, and declines to duplicate an address the customer already
has.

## Address vocabulary

`orders` imports the address vocabulary from `accounts`: `US_STATES` and
`ADDRESS_FIELDS` from `accounts/models.py`, `zip_validator` from
`accounts/validators.py`. Card validators are separate, in
`orders/validators.py`.

Two different constants are both named `ADDRESS_FIELDS`, so import the
right one: `accounts.models.ADDRESS_FIELDS` is the six unprefixed address
fields (`name` … `zip`) shared by `Address` and checkout, while
`orders.services.ADDRESS_FIELDS` is the thirteen checkout keys (`email`
plus the `shipping_`/`billing_`-prefixed fields) that `place_order` copies
onto an `Order`.
