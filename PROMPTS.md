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

## 2026-09-30 — One fixed size for cart, checkout and order thumbnails

### Prompts

1. "@HANDOFF.md everything seems to be working correctly but there are some
   additional stlying implementation changes I would like to make. When I
   tems are added to cart the image is huge and overlaps the price of the
   item, the same can be said on the checkout and orders section, can we
   make the thumbnail images on all of these one specific size and make sure
   it does not overlap any text"
2. "These images are still not sized correctly and are overlapping text, can
   you please make sure these images are one specific size and that they do
   not overlap or make the text look weird", with three screenshots: the
   cart, checkout's "Your order" box and the order confirmation, each showing
   a roughly 600 px photo over the text.
3. "Ok can you append this conversation to PROMPTS.md with the styling
   specified there"

### Summary

- **Outcome:** Every line-item thumbnail now renders through one partial,
  `products/partials/_thumbnail.html`, as a fixed 48×60 (4:5) frame. It is
  used on the cart, checkout, order history, order detail, confirmation and
  back-office order detail. Before, each page set its own width (32–56 px).
  The partial takes `pic`, an optional `href` (the cart links to the
  product) and `tooltip` (history and confirmation), and is included with
  `only`, so page context such as a `title` cannot leak in.
  `products/partials/_picture.html` gained optional `width`/`height`
  overrides for the `<img>` attributes; the catalog and product page are
  unchanged. In the cart and checkout the text beside the thumbnail got
  `min-w-0` so long names wrap next to the image instead of under or over
  it. `docs/TEMPLATES.md` records the partial and why it is built this way.
  Result: 431 tests passing, ruff clean, CSS rebuilt. Nothing committed.

- **Deviations:** None from a recommendation. The user chose no size; 48×60
  was picked to fit four thumbnails in an order-history row, and 64×80 was
  offered as a one-line change. A dev-mode cache-busting fix for the
  stylesheet was offered and is unanswered.

- **Sideways:** The first fix did not fix the user's browser, and the cause
  was misread at first.
  - **Prompt 1.** A render through the test client, screenshotted with
    headless Edge, showed thumbnails already the right size before any
    change. The session guessed a stale cached `tailwind.css`, told the user
    to press Ctrl+F5, and added the shared partial with `width="48"
    height="60"` on the `<img>` as a fallback. It checked that fallback only
    with *no* stylesheet at all, which is not the failure the user had.
  - **Prompt 2.** The user's screenshots showed the photos still at full
    size. Logging in to the live dev server with curl proved it was serving
    the new markup and a current stylesheet, so the browser's cached CSS was
    confirmed as the cause: the tag links a plain `/static/css/tailwind.css`
    with no version in `DEBUG`. That old copy had `w-full`/`h-full` but not
    the frame's `w-12`/`h-15`, so `w-full` of an unsized frame resolved to
    the photo's natural 600 px and overrode the width attribute. The fix
    sizes the `<img>` itself (`h-15 w-12 max-w-none`) instead of as a
    percentage of its frame. It was verified against a copy of the
    stylesheet with those rules deleted, which reproduces the user's state.
  - **Side effects.** The render script added products to the demo
    `customer` account's cart on every run, leaving 13 items in the dev
    database; the user was told `seed` resets it. Several stale `runserver`
    and `tailwind watch` processes from earlier sessions were found running,
    only one of them serving port 8000.

---

## 2026-09-30 — Product images: the build, then two rounds of back-office and gallery changes

### Prompts

1. "@HANDOFF.md Implement this feature"
2. "Code only (Recommended)" — the answer to the question `HANDOFF.md` said
   to ask first: whether to write `prd/product-images.md` and
   `plans/product-images.md` before coding.
3. "Ok now that you have implemented the features how can I manually review
   and test the code that you generated?"
4. "Ok I have some problems when I try to adda product, firstly I dont know
   what "slug" is, I would simply like to have the image uploaded using a
   simple upload button and if more than one image is added show it as a
   gallery as discussed before. Next the tags section looks off with all of
   the text being scrunched togehter can be make this a simle list view where
   I can select by using checkboxes for which tags I would like to add"
5. "Ok there are a few things I would like to change first of all cn we make
   the upload images instead of having it say Choose make it an upload button
   and specify that to set a main image first add all images, then on the
   product options have the option for the user to actually select the main
   image after they have all loaded and are able to be previewed. The next
   thing I notice that needed to be changed is the way the images are listed
   on the given product pages. Right now it has the images loaded twice, it
   merges the main and secondary images into the primary image rather than
   just using the main image only. Also there does not seem to be any
   scrollable carousel for viewing the secondary images just a line of
   images"
6. "Ok can you append this conversation to PROMPTS.md using the styling
   provided on PROMPTS.md"

### Summary

- **Outcome:** The design in `HANDOFF.md` was built as agreed, then reshaped
  twice by the user's own testing.

  *The build (prompts 1–2).* `products/images.py` became the third deep
  module. It holds one validator with the seven rules, each refusal naming
  the file and the values it found. It also holds the pipeline (resize to
  display and thumbnail WebPs in memory, write under random names, save in a
  transaction, delete old files on commit), the extras' ordering, and
  `snapshot_for_order`. `Product` gained the main image fields,
  `ProductImage` holds up to eight extras, and `OrderItem` gained a snapshot.
  Templates only ever render a `Picture` through
  `products/partials/_picture.html`. `card_image`, `display_image` and
  `OrderItem.thumbnail` return the media URL only when the file exists, and
  the category placeholder otherwise. `place_order` copies thumbnails in
  `on_commit(robust=True)`, so a failed copy cannot fail or roll back an
  order. Other pieces:
  - a staff-only Images page;
  - read-only previews in the Django admin;
  - `SERVE_MEDIA` independent of `DEBUG`, and `MEDIA_ROOT`, both in
    `.env.example`;
  - a temporary `MEDIA_ROOT` for every test;
  - thumbnails on the cart, checkout and all order pages, loaded without
    N+1 queries via `Order.objects.with_items()`.

  The 13 baseline photos moved to `products/seed_images/` under slug names,
  with written alt text, and `product-images/` was deleted after a checksum
  comparison. The seeded catalog went from 27 MB of PNGs to about 4 MB of
  WebPs, and reseeding leaves no stray files. `CLAUDE.md` now says "three"
  deep modules, and `docs/IMAGES.md` was added. Result: 401 tests (86 new),
  ruff clean, and the catalog and carousel checked by headless-Edge
  screenshot.

  *Prompt 3* changed no code. It produced a manual review and test script: a
  file-by-file reading order, a browser walkthrough for each login, a Python
  snippet that generates one bad file per validation rule with the expected
  message for each, and steps for the missing-file, product-deletion and
  `DEBUG=False` checks.

  *Prompt 4.* `Product.save` now generates the slug from the name, numbered
  if taken (`seraphine-2`), and never changes it on rename. The field left
  the form and became `blank=True` (migration `0005`). The product form
  gained a multi-file upload: the first file fills the main image and the
  rest become extras. Tags became a checkbox list, one choice per row. To
  keep the brief's "never accept a file and then lose it" once uploads sat on
  a form with other fields, images that pass validation are *held* under
  `media/pending/` and carried as hidden tokens while the employee fixes
  other errors. Stale holds are swept after a day. Result: 412 tests.

  *Prompt 5.* The upload became an **⬆ Upload images** button that sends
  files over HTMX to `StageProductImagesView` the moment they are chosen.
  That view returns `_image_picker.html`: a preview per image, a "main image"
  radio button, and a ✕ to discard. On the edit form the product's saved
  images are choices too. `attach_uploads` applies the choice through a new
  `make_main`, which swaps stored names rather than files, and the Images
  page gained a "Make main image" button. The product page now shows the
  main image once, with the extras in their own "More images" carousel with
  wrapping ❮ ❯ arrows and a counter. The old thumbnail row, which repeated
  the main image, is gone. Result: 431 tests passing, ruff clean. Nothing
  has been committed.

- **Deviations:** Prompt 2 took the recommended option. Prompts 4 and 5
  reversed three settled decisions from the design interview, each at the
  user's request:
  - **Uploads on the product form.** The interview had put uploads on a
    separate Images page, so that an error elsewhere on a form could never
    discard a chosen file. Uploads now sit on the product form, and holding
    accepted images is what preserves that guarantee. The Images page stays
    for managing saved images.
  - **Promoting an extra to main.** "No promote extra to main" became
    allowed, but only by an explicit choice; removing the main image still
    leaves the placeholder, not the first extra.
  - **The gallery.** The Q10 layout (main image first in the carousel, plus
    a thumbnail row) became main-image-only with a separate extras
    carousel.

  "Create product redirects to the Images page" was also dropped once images
  could be added on the form itself. Two things were offered and are still
  unanswered: making the category and tag slugs automatic as well, and
  replacing the anchor-link carousel if its page nudge on arrow clicks
  bothers the user. `HANDOFF.md` asked the build session to write an entry
  here. It was declined, because this file's own rule allows entries only
  when the user asks. This entry is the one that prompt asked for.

- **Sideways:** Several defects were caught during the work, most of them by
  tests:
  - **PNG decoding before the size checks.** A new megapixel test failed
    with "image file is truncated", which exposed a real hole. On a PNG,
    Pillow's `getexif()` decodes every pixel, and it ran *before* the
    decompression-bomb check. Orientation is now read from the header chunks
    only.
  - **A partial as an on-commit callback.** A test of a crashing snapshot
    step showed that Django's `robust=True` error logging reads
    `func.__qualname__`, which `functools.partial` lacks. A failed snapshot
    would have crashed the logger itself. It is now a lambda, and
    `docs/IMAGES.md` records why.
  - **An import ruff removed.** `ruff --fix` dropped `reverse` from
    `products/views.py` when it was briefly unused. It was needed again in
    prompt 5, and 19 tests failed with `NameError` until it was restored.
  - **Tags still inline.** The first tag fix still rendered inline, because
    DaisyUI's `.label` is `inline-flex`. A screenshot caught it, not a test.
  - **Bad tests.** Two tests written in prompt 5 were vacuous: one assertion
    ended in `or True`, and one compared against a field `make_main` had
    already blanked. Two others depended on exact whitespace. All four were
    rewritten before the run, with a regex helper for the checked radio.
  - **Smaller slips.** A test missed that Django escapes apostrophes in
    messages. The media URL pattern first had a leading slash (Django warning
    `urls.W002`). A race in `move_extra` (an extra deleted mid-move raising
    `StopIteration`) was found on self-review and closed.

  Visual checking was limited. Headless Edge could not sign in, so the
  back-office screens were rendered through Django's test client with
  asset URLs pointed at a running dev server. Three blank or half-scrolled
  captures turned out to be lazy loading and smooth-scroll timing, not bugs,
  confirmed by checking every image URL returned 200 and re-shooting the
  public page live. The HTMX upload and the carousel arrows have therefore
  not been clicked in a real browser. `/security-review` and `/code-review`
  were recommended and not run.

## 2026-09-30 — Product images: the design interview and the handoff

### Prompts

1. The `/grill-me` skill, given the feature in the user's own words:
   "Currently there are no images on the catalog, and only a placeholder is
   shown for each item. This has allegedly reduced sales for products, as
   they do not have an idea as to what the product looks like. Some
   additional criteria for this image implementation are that a set of
   baseline images should be used; these images are located in a temporary
   folder called product-images. Pages should remain fast and responsive.
   The following has been mentioned as non-negotiable: Every product must
   display either its intended image or an existing placeholder. Missing
   files or broken images should not be loaded or attempted to be loaded.
   Employees must also be able to upload images through the back office; if
   an image file is unsuitable, reject the image and explain to the employee
   why the image cannot be used in clear/understandable language. Also do
   not accept the file first and then lose it."
2. "A" (Q1: `ImageField` under `MEDIA_ROOT`)
3. "Can we go with B but add some additional prameters, by default a
   product should only get one image but, we should also add the ability to
   potentially add more than one if we so choose. This should not affect
   the main image but still allow you to view the other images if there are
   more than one" (Q2: one image vs. gallery)
4. "A" (Q3: `Product.image` plus a separate `ProductImage` for extras)
5. "B" (Q4: resize at upload to two WebPs, discard the original)
6. "D" (Q5: render-time existence check plus disk/DB sync)
7. "A" (Q6: the seven validation rules and their messages)
8. "A" (Q7: a separate per-product Images page)
9. "lets go with A for both" (Q8a SyncRest clean main + poster extra;
   Q8b SoulSear image on Mark I only)
10. "A" (Q9: fixed 4:5 card frame, cropped to fit)
11. "A" (Q10: CSS carousel with thumbnail row)
12. "A" (Q11: all seven Images-page actions, 8-extra limit)
13. "A" (Q12: optional alt text with fallbacks)
14. "B" (Q13: `SERVE_MEDIA` setting, on by default)
15. "C" (Q14: images on cart, checkout *and* order pages)
16. "B" (Q14b: snapshot the thumbnail onto `OrderItem` at purchase)
17. "A" (Q15: images read-only in Django admin)
18. "A" (Q16: third deep module, `products/images.py`)
19. The `/handoff` skill: "the next session implements the design we just
    agreed"
20. "Ok using the PROMPTS.md write a session log using the standard prompt
    listed there"

### Summary

- **Outcome:** Design only; no application code was written. Seventeen
  questions (Q1–Q16 plus a Q14b sub-question), one at a time, each naming
  what it settled and recommending an option. The agreed design is recorded
  in `HANDOFF.md` and nowhere else yet. In brief: a main image on
  `Product.image` and up to eight ordered extras in `ProductImage`; every
  upload validated by seven plain-language rules and re-encoded to a
  display and thumbnail WebP; templates only ever ask a model property that
  returns the file's URL if it exists on disk, else the category
  placeholder; uploads live on a dedicated Images page so an unrelated
  form error can't discard them; order lines snapshot their thumbnail in
  `place_order`, where a failed copy must never fail the order; and the
  pipeline becomes a third deep module, `products/images.py`, with
  CLAUDE.md to be amended to say so.

  Several decisions came from reading rather than asking: the baseline
  PNGs are ~2 MB each (about 25 MB for a catalog page served raw); the
  placeholders are 4:3 while 12 of 13 photos are ~4:5; `docs/TEMPLATES.md`
  forbids JavaScript beyond HTMX, which ruled out gallery libraries;
  `ProductAdmin` restricts no fields, so the new `ImageField` would have
  appeared in `/admin/` as an unvalidated back door; Django stops serving
  media when `DEBUG=False`, which would have produced exactly the broken
  images the brief forbids, and the render-time file check can't catch it;
  CLAUDE.md's "exactly two deep modules" rule meant Q16 had to be asked
  rather than drifted past; and the seed builds its demo orders directly,
  not through `place_order`, so snapshots there need their own step. The
  two ambiguous baseline images were settled by looking at them and
  checking seed descriptions — Mark I's "took several things off it"
  matched a ruined skyline, and Tactical Core's tagline is literally
  "without the skyline".

- **Deviations:** two recommendations were overridden, and both widened the
  design. Q2: I recommended one image per product; the user chose a gallery
  constrained to one main image plus optional extras that never affect it.
  That reshaped Q3 (hybrid model), and created Q10 (the carousel) and most
  of Q11 (the extras actions and limit). Q14: I recommended stopping images
  at the cart and checkout; the user chose order pages too. That forced
  Q14b, because `OrderItem` only links to the *current* product and would
  have shown today's image on months-old orders; it was settled as a
  snapshot, which touches `place_order`. One answer was read more broadly
  than given — "A" to Q1 was taken to also approve moving the baseline
  images into a committed folder, and the user was told so. One question
  was left unanswered: whether to write `prd/` and `plans/` documents
  before coding. `HANDOFF.md` tells the next session to ask it first.

- **Sideways:** no code, so nothing broke, but the interview contained
  counting errors of mine. Q8 said "eleven of the 13 files match exactly
  one product" above a table of ten; the true split was ten unambiguous,
  one ambiguous (SoulSear) and two for one product (SyncRest). Q12 said the
  seed had 14 images; it has 13 across 12 products. That one was caught and
  corrected at the start of the next reply. The Q8 miscount was not caught
  until this log. Q1's "about 21 products keep the placeholder" became 22
  once the mapping was settled.

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

## 2026-09-22 — Saved shipping and billing addresses

### Prompts

1. The `/grill-me` skill, given one sentence: "Customers should be able
   to save shipping and billing addresses to their account and reuse
   them at checkout."
2. "Implement the feature."

### Summary

- **Outcome:** Seventeen questions, then the build. `accounts.Address`
  holds role-free rows — a role is something an *order* has, assigned at
  checkout — with an optional `label`, two default flags, and a
  conditional `UniqueConstraint` per role. `make_default` is the only
  thing that moves a default; `AddressQuerySet.remember` is the
  write-back. Checkout pre-fills from the defaults and swaps a chosen
  address into its existing fields over HTMX via
  `CheckoutAddressFieldsView`. `US_STATES` and `zip_validator` moved from
  `orders/forms.py` into `accounts`, since the app that owns addresses
  should own the address vocabulary. 315 tests pass (43 new), ruff clean,
  seed idempotent.

- **What the interview bought:** the feature adds nothing to the order
  pipeline. `Order`, `OrderItem`, `place_order` and `ADDRESS_FIELDS` are
  untouched, and `CheckoutForm` keeps its twelve required fields and its
  zero `clean()` methods. Three options were rejected specifically to
  preserve that: replacing the checkout fields with `ModelChoiceField`s,
  giving `Order` an address FK, and adding "billing same as shipping"
  (which would have needed conditionally-required fields). The form
  docstring calling itself "the codebase's showcase of declarative
  validation" did more design work than any answer I gave.

- **Where reading the code beat asking:** the discount feature's
  `discount_code_used` FK looked like the obvious precedent for linking
  orders to addresses. It isn't — that FK is load-bearing for usage
  limits, `dashboard/queries.py` has no address query at all, and codes
  are never deleted while addresses will be. A mostly-null FK with no
  reader would have invited queries that quietly under-count. Choosing
  `accounts` for the model also surfaced two import problems that only a
  grep found: `zip_validator` living in `orders`, and `StyledModelForm`
  living in `products`, which already imports `accounts.mixins` —
  inheriting it would have made two apps import each other. `AddressForm`
  styles its own widgets instead.

- **A gap the plan had:** the defaults invariant ("a customer with
  addresses always has a default") was settled for creation and deletion
  but not for *unticking* a checkbox, which would have left a customer
  with two addresses and nothing pre-selected. The box is rendered
  disabled on the address that holds the role, so `make_default` needs no
  clearing branch and the invariant holds by construction rather than by
  repair.

- **Scope held three times:** a navbar user-menu dropdown, a project-wide
  address partial, and "billing same as shipping" were all declined as
  separate commits with their own justifications. The dual-default design
  already pre-fills both sections identically for the one-address
  customer, which is who "same as shipping" would have served.
