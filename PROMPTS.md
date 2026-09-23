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

## 2026-09-22 — Discount codes: the design interview, the build, and the review

*Session ran 21–22 September and is logged on the 22nd. This is the session
that created the discount feature; the other 2026-09-22 entry further down is
the separate follow-up session that added usage limits, multi-product scope
and reinstatement on top of it.*

### Prompts

1. The `/grill-me` skill, given the feature in the user's own words: "I would
   like you to lead me to develop a discount code feature. This feature allows
   a customer to type a code at the checkout, with that discount code the order
   total would subsequently drop. Here are some requirements of this feature:
   codes must expire when the promotion ends, customers who type expired codes
   should see a message saying that the code is expired without breaking the
   page or the underlying code. Codes must be able to be created and retired.
   If a code is retired that code must not change any order that has already
   used it. The code written should be free from errors redirects to blank
   pages or the customers wrongfully contacting legal. The extent of the
   discount codes must apply to both wide orders(multiple items) or singular
   items. An example of this would be making a discount code for 50% off
   Seraphine for a given date."
2. "Implement this feature"
3. "Ok now that the changes have been made how cn I manually review and test
   the changes to make sure there are no bugs or issus with the code"
4. "can you explain this deviation that I made in more depth", quoting the
   **Where the user overrode the recommendation** bullet from the interim log
   entry (the IDE selection of PROMPTS.md lines 114–121).
5. The session-log prompt from the top of this file.

### Summary

- **Outcome:** Sixteen questions, one at a time, each naming the part of the
  design it settled and recommending an option; then the build. Everything the
  codebase could answer was read rather than asked — the dormant `coupon_code`
  seam, `OrderItem`'s denormalisation precedent, `Product.is_available` as the
  retire pattern, the six call sites of `cart.total()`, and the existing
  `UpdateOrderStatusView` shape.

  `DiscountCode` landed in `orders` with `code`, `kind`, `value`, a nullable
  `product` FK, `starts_at`/`ends_at` and `is_active`; rules on the model
  (`is_live`, `status`, `label`, `discount_for`) and its queryset (`live`,
  `find`). `Cart` gained the FK, and its old `total()` became `subtotal()` so
  that `total()` could mean the amount due — which made `place_order` and all
  three templates discount-aware without editing them. `Order` froze the code's
  name, the dollars taken off, and a `SET_NULL` link. Apply and remove run over
  HTMX on the cart page; `CheckoutView.dispatch` re-checks before card entry
  and `place_order` re-checks inside the transaction. The back office gained a
  fifth tab with list/create/edit and retirement as its own POST action, and
  the dashboard gained `discounts_given()` plus a fourth tile, with Top
  products relabelled "by gross sales". 221 tests passing, ruff clean, five
  demo codes in the seed covering live, scheduled and expired. The
  `coupon_code` parameter was removed and the PRD and plan amended to record
  how the seam actually landed.

  Prompts 3 and 4 changed no code. Prompt 3 produced a manual review script
  with exact expected figures against the seeded world ($616.00 subtotal;
  `THOUGHTS10` → $554.40, `MINDFUL20` → $596.00, `SERAPHINE50` → $367.00) and
  named three things verified in tests but not in a browser: the
  `datetime-local` prefill when editing an existing code, the apply form after
  an HTMX swap, and that `TIME_ZONE = "UTC"` makes entered dates read as UTC
  rather than Central. Prompt 4 was an explanation of the two overridden
  recommendations, grounded in the code as it stood after the follow-up
  session had already grown it.

  *Note for future readers:* this entry describes the feature as built in this
  session. `is_live`/`status` and the single `product` FK have since been
  replaced by `unusable_reason` and `applies_to` + `products` — see the
  2026-09-22 part-two entry below.

- **Deviations:** two of the sixteen recommendations were overridden, and both
  changed the design.

  `kind` + `value` instead of percent-only forced a question percent alone
  never raises — what "$20 off Seraphine" means when three are in the cart. It
  was settled as $20, once, capped at the line total, so the worst case stays
  bounded by the number the merchant typed. The asymmetry with percent (which
  does scale with quantity) is deliberate and is asserted directly by
  `test_a_fixed_amount_comes_off_once_however_many_are_bought`.

  Applying on the **cart page** rather than at checkout opened a real
  time-of-check/time-of-use gap: a code can stop being valid between applying
  and paying. Validation became four call sites over one implementation — the
  apply form, the cart's own total, the checkout guard, and `place_order`. The
  user was told the second check was non-negotiable before agreeing.

  Two follow-up questions were asked after the build: how to manually review
  and test the changes, and a request to explain those two deviations in more
  depth.

- **Sideways:** four tests failed on the first full run. Two were arithmetic
  errors of mine (half of 2 × $349.99 is $349.99, not $350.00) and one assumed
  Django escapes literal template text — in all three the implementation was
  right and the test was wrong. The fourth was a real defect: the back office's
  success message printed the code as typed rather than as stored, and behind
  it sat a worse problem — `ModelForm` checked uniqueness against the
  un-normalised string, so `spring50` would have passed validation beside an
  existing `SPRING50` and then failed at the database. Normalising in
  `clean_code` fixed both, with a regression test for the duplicate case.

  Ruff caught two further things: an import-order violation (auto-fixed) and
  DJ012, the Django style guide's method ordering, which wanted `save` above
  the `normalize` staticmethod.

  Found while reading rather than while building: `CheckoutView.form_valid`
  called `place_order` with no `try`/`except`, so its `ValueError` would have
  rendered a Django 500 — the blank page the brief asked to design against,
  already latent in the code before this feature existed. Fixed here.

  Two process notes. Manually exercising the flow through `manage.py shell`
  hit `DisallowedHost: testserver`, since `ALLOWED_HOSTS` is only relaxed under
  pytest; worked around at runtime, not a defect. And the interim log entry
  written mid-session was appended at the bottom of this file in a freeform
  shape, following CLAUDE.md's "append entries" without reading this file's own
  header, which asks for newest-first and a fixed shape. It has been folded
  into this entry rather than left as a malformed duplicate; no fact it
  recorded was dropped.

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

## 2026-09-22 — Discount codes, part two: limits, scope, organisation, reinstatement

### Prompts

1. The `/grill-me` skill, given four changes in the user's own words:
   usage limits (once per account by default, or a set number, or
   unlimited); an active/inactive split on the discounts page with only
   active codes shown by default; box-selection of several products per
   code instead of one-or-all; and reinstatement of codes, with duplicate
   entry prompting the creator rather than erroring.
2. "Implement the changes."

### Summary

- **Outcome:** Sixteen questions, then the build. `DiscountCode` gained
  `applies_to` + `products` (M2M, replacing the `product` FK),
  `per_user_limit` (default 1), `total_limit` (default unlimited) and
  `counting_since`. Migration `0004` adds the columns, copies the old FK
  into the new set, and only then drops it — `SERAPHINE50` survived
  intact. Uses are counted live from `Order.discount_code_used` via
  `counted_orders`, with `with_usage()` as its SQL twin for the list
  page. `unusable_reason(user)` is the single eligibility answer, called
  from the cart box, `Cart.discount_amount`, `CheckoutView.dispatch` and
  `place_order`. The back office gained `?show=active|inactive|all`, a
  used/limit column, a scrollable product checkbox list, and a
  reinstatement screen that adapts to the existing code's status. 275
  tests pass (54 new), ruff clean.

- **Where the grilling changed the design:** two places, both found by
  reading rather than asking. First, "active" cannot mean `is_active` —
  an expired code still has that flag set, so the obvious reading would
  have left every dead promotion in the default view, which was the exact
  complaint. Active became live-or-scheduled. Second, and more seriously,
  question 7 settled on "an empty product set means the whole order", and
  question 9 had to reopen it: the existing `on_delete=CASCADE` carried a
  comment explaining that *"a code for a deleted product must not quietly
  become a code for everything"*, an M2M has no `on_delete`, and staff can
  delete products from the back office. The implicit spelling would have
  turned 50%-off-Seraphine into 50% off the store. `applies_to` exists
  because of that comment.

- **Already built, contrary to the request:** reinstatement. The brief
  asked to add it, but `ToggleDiscountActiveView` and a "Reactivate"
  button were already there. The real gap was the duplicate path, which
  dead-ended in Django's stock "already exists". That became the work.

- **Deviations:** one recommendation overridden, deliberately. Cancelled
  orders now *release* their use, against my advice — the user was told it
  allows order-and-cancel farming of a one-per-account code and chose it
  anyway. The exclusion sits in `counted_orders` alone, so reversing it is
  one line. Also noted and accepted: "reinstate as-is" cannot revive an
  expired code (flipping `is_active` can't outrun a past date), so that
  button is withheld for expired codes rather than offered as a no-op.

- **Sideways:** five tests failed on the first full run, all of them
  pinned to the old shape — three constructing codes with `product=`, one
  expecting the generic "no longer valid" where the guard now reports the
  code's own reason, and one expecting the duplicate dead-end that was the
  point of the change. All five were updated rather than worked around.
  One template block was written badly first (the typed-terms summary
  computed a label in markup, including a nonsense `yesno` filter) and was
  replaced by a `typed_label` helper on the view, because `target_label`
  reads the products relation and an unsaved instance has no primary key
  to read it with.
