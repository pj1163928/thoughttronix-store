# The wishlist

A customer's saved products. Lives in its own app, `wishlist/`, which
imports `products` and nothing imports back: the product page reaches it
through the `{% wishlist_button product %}` tag (`wishlist_extras`), never
through `products` Python code.

## Model

- `Wishlist` — one per user (`OneToOneField`), created lazily by
  `Wishlist.for_user`, the same way as `Cart`.
- `WishlistItem` — one saved product, unique per wishlist, no quantity.
  Newest first (`-added_at`). Deleting a product removes it from every
  wishlist.
- Any product with a page can be saved, unavailable ones included. The
  wishlist page shows the ordinary add-to-cart button, which greys itself
  out for those.
- Adding to the cart leaves the product on the wishlist; only the
  customer removes it. Checkout and `place_order` know nothing about
  wishlists.

## Privacy

Only the owner ever sees a wishlist — not staff, not the superuser.

- No admin registration, no back-office page, no dashboard figure. A test
  fails if either model is registered in the admin.
- No URL names a wishlist or its owner. Every lookup starts from
  `request.user` via `WishlistItem.objects.of(user)` (empty for anonymous
  visitors); a line belonging to someone else 404s.
- Aggregate "most wished-for" figures were deliberately left out. If they
  are ever added, they must never single out one customer.

## HTMX

- Product page: `wishlist:add` and `wishlist:remove` (POST, product pk)
  are separate and idempotent — deliberately not a toggle, so a double
  click or a stale tab can't flip the state back. Each re-renders
  `wishlist/partials/_wishlist_button.html` from the database. The button
  keeps `id="wishlist-button"` so htmx restores keyboard focus after the
  swap.
- Wishlist page (`wishlist:list`): each row's Remove posts to
  `wishlist:remove_item` (wishlist-item pk) and re-renders
  `_wishlist_contents.html` into `#wishlist-contents`, like the cart.
- Anonymous visitors get a plain sign-in link with `?next=`, as with
  add-to-cart.

## Seed

`customer` gets three saved products (DreamWeaver, MindSync Duo, and the
unavailable EchoPatch), a day apart. The seed wipes all wishlists first.
