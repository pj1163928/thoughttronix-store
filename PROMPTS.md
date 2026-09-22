# PROMPTS.md — AI Usage Log

This file is the record of AI use on this codebase. At the end of every
agent session, direct the agent to write the session log with this prompt:

> Append a session log to PROMPTS.md at the repo root, under today's date,
> newest entry at the top. Record every prompt I gave you this session, in
> order, including any corrections. End the entry with a short summary:
> the outcome, any places where I deviated from a recommended answer or
> asked follow-up questions, and anything that went sideways.

Two rules:

- Entries are added only by that prompt, never unprompted.
- New entries go at the top. Never rewrite or delete an old entry — the
  log is part of your work, and an honest log of a session that went
  sideways is worth more than a tidy one.

Each entry has this shape:

    ## YYYY-MM-DD — <one-line summary>

    ### Prompts
    1. ...

    ### Summary
    - **Outcome:** what was built and what was kept
    - **Deviations:** recommendations overridden, follow-up questions asked
    - **Sideways:** failures, wrong turns, and how they were caught

---

## 2026-09-15 — `Product.is_featured` and the Featured badge

### Prompts

1. "Can you add an is_featured field stored as a boolean object, do not
   include the tag/badge on the product such as the accessories defense or
   home assistants tags as that will come later. Simply add it as another
   option like Is available. Also make sure that is_featured is defaulted to
   not featured or false."
2. "Ok now that I do have the is_featured field and I have verified that it
   works well and does not break anything, I would like to implement the
   badge that I talked about earlier. It is important that the badge appears
   in all relevant views this includes the catalog list and the product
   detail page, (make sure it shows up in all relevant locations). Also add
   any tests that you may see fit regarding these two implementations and
   make sure they are working properly."
3. The session-log prompt from the top of this file.

### Summary

- **Outcome:** Two deliberately separated phases, both kept.

  Phase one added `Product.is_featured = BooleanField(default=False)` in
  `products/models.py`, migration `0003_product_is_featured`, the field in
  `ProductForm.Meta.fields` (it renders as another DaisyUI toggle beside
  "Is available" — the back-office form template loops over the form, so no
  template change was needed), and `is_featured` in the admin's
  `list_display` and `list_filter`. 164 tests green.

  Phase two added the badge as one shared partial,
  `templates/products/partials/_featured_badge.html` — a solid
  `badge badge-primary` reading "Featured", rendered only when
  `product.is_featured`. It is included in three places: the catalog card's
  badge row (`catalog.html`, which also covers the category pages, since
  `CategoryView` subclasses `CatalogView` and reuses the template), the
  detail page's status row (`detail.html`, whose wrapper became a
  `flex flex-wrap gap-2` so two badges sit side by side), and the
  back-office product table next to the product name
  (`manage_products.html`). Ten new tests and a `featured_product` fixture
  in `conftest.py`; 174 passing, ruff clean.

- **Deviations:** No recommendation was overridden and no blocking question
  was asked. The split itself was the user's call: prompt 1 explicitly
  deferred the badge ("that will come later"), and prompt 2 opened by
  confirming the field had been verified in the running app before the badge
  work started. One judgment call was made and flagged rather than asked
  about — the badge was deliberately left off the order-side templates
  (cart, checkout, order history, order detail, staff order detail), on the
  grounds that those show what someone bought and "featured" is a browsing
  signal; the user was told and invited to override.

- **Sideways:** Nothing broke; no wrong turns, no failing intermediate
  states. Worth recording as method rather than mishap: four of the ten new
  tests only assert that a string appears on a page, which would pass
  vacuously if the include were wired up wrong. They were checked by
  blanking the partial and confirming those four fail
  (`test_manage_list_badges_featured_products`,
  `test_catalog_badges_only_featured_products`,
  `test_detail_shows_featured_badge`,
  `test_category_page_shows_featured_badge`), then restoring it and
  re-running the full suite. The two catalog/back-office badge tests count
  `">Featured<"` occurrences rather than testing mere presence, so they
  catch both a missing badge and one leaking onto every card.

## Discount codes — `/grill-me`, then implementation (2026-09-21)

- **Prompt:** the `/grill-me` skill, given the feature in the user's own
  words: a code typed at checkout that drops the order total; codes that
  expire when the promotion ends; an expired code showing a message
  without breaking the page; codes that can be created and retired, where
  retiring changes nothing about orders that already used them; and codes
  that work for a whole order or for a single item ("50% off Seraphine for
  a given date").

- **Method:** sixteen questions, one at a time, each naming the part of
  the design it settled and recommending an option. Everything the
  codebase could answer was read rather than asked — the dormant
  `coupon_code` seam, `OrderItem`'s denormalisation precedent,
  `Product.is_available` as the retire pattern, the six call sites of
  `cart.total()`, and the existing `UpdateOrderStatusView` shape.

- **Where the user overrode the recommendation:** twice, and both changed
  the design. `kind` + `value` instead of percent-only forced a decision
  about what "$20 off Seraphine" means when three are in the cart (it
  means $20, once). Applying on the **cart page** instead of at checkout
  opened a real gap — a code can expire between applying and paying — so
  validation became two call sites over one implementation, plus a
  `dispatch` check and a transactional backstop.

- **Found while reading, not while building:** `CheckoutView.form_valid`
  called `place_order` with no `try`/`except`, so its `ValueError` would
  have rendered a Django 500 — the "blank page" the user asked to design
  against, already latent in the code. Fixed here.

- **Found by a failing test:** the back office's success message printed
  the code as typed, not as stored. The real defect behind it was that
  `ModelForm` checked uniqueness against the un-normalised string, so
  `spring50` would pass validation beside an existing `SPRING50` and then
  fail at the database. Normalising in `clean_code` fixed both; there is a
  regression test for the duplicate case.

- **Corrected:** two of my own test expectations were arithmetic errors
  (half of 2 × $349.99 is $349.99, not $350.00), and one assumed Django
  escapes literal template text. The implementation was right; the tests
  were wrong.
