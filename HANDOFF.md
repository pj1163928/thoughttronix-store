# HANDOFF — Product images

**Next session's job:** implement the product-image design below. It was
settled in a `/grill-me` interview (Q1–Q16); every decision here is agreed —
don't re-litigate, implement. The design is **not yet written anywhere else**
(no PRD/plan file), so this document is its only record.

## Where things stand

- No code written yet. Uncommitted: `pillow>=12.3.0` added to
  `pyproject.toml` / `uv.lock` (needed for `ImageField`) — keep it.
- `product-images/` (untracked, temporary) holds the 13 baseline PNGs
  (~1.7–2.5 MB each, ~1122×1402; `MindSync Duo.png` is 1536×1024).
- Open question left unanswered: whether to first write the design up as
  `prd/product-images.md` + `plans/product-images.md` in the style of
  `prd/core-platform.md` / `plans/core-platform.md`. **Ask the user before
  coding.**

## Read first

- `CLAUDE.md`, `docs/TESTING.md`, `docs/TEMPLATES.md` (no JS beyond HTMX;
  partials conventions; `StyledModelForm`)
- `products/models.py` — `Category.placeholder_image` (per-category static
  SVGs in `assets/images/placeholders/`, 4:3)
- `templates/products/catalog.html:64`, `templates/products/detail.html:17`
  — the only current `<img>` tags
- `orders/services.py` (`place_order`), `orders/models.py` `OrderItem`
  (~line 516; `product` FK is `SET_NULL`, already snapshots `product_name`)
- `products/management/commands/seed.py` — `CATALOG` dict; demo orders are
  built directly (~line 790), **not** via `place_order`
- `products/admin.py` — `ProductAdmin` has no field restriction
- `PROMPTS.md` — append an entry for this work; never rewrite history

## Agreed design

**Model**
- `Product.image` = the main image. New `ProductImage` model (FK Product,
  image, optional alt text, sort order) = extras, max 8 per product.
  Extras never affect the main image; no "promote extra to main".
- Each stored image = two WebP files: **display** (longest side ~1200 px)
  and **thumbnail** (~600 px wide). Original upload is **not** kept.
- Unique random filenames (cache-busting; old/new never collide).
- Optional alt text per image; fallback = product name (main) or
  "Name — image N of M" (extras).

**Validation** — one shared validator, plain-language messages that state
the actual values found:
1. Real JPEG/PNG/WebP, detected by content not extension
2. Must decode cleanly
3. ≤ 10 MB
4. ≥ 600 px on each side
5. ≤ 40 megapixels (decompression-bomb guard)
6. Aspect no more extreme than 3:1 either way
7. Not animated

Silently fix, don't reject: EXIF rotation, CMYK → RGB, keep transparency.

**Never load a missing/broken file**
- Templates only use model properties (e.g. card/display URL) that return
  the media URL only if the field is set **and** the file exists in
  storage; otherwise the category placeholder. Cards check the thumbnail,
  detail checks the display file. No `onerror` tricks.
- Also keep disk/DB in sync: order is validate+resize in memory → write new
  files → save row in a transaction → delete old files in
  `transaction.on_commit`. On failure, remove the new files, leave the old
  image untouched. Product deletion cleans up its files too.

**Back office** — a per-product **Images page** (pk URL, staff-only via
`StaffRequiredMixin`), separate from the product form, so a failing
unrelated field can never discard an upload:
- Upload/replace main; remove main (confirm → placeholder); add extra;
  remove extra (confirm); move extra up/down (plain buttons); 8-extra
  limit with its own message; 4:5 cropped card preview.
- "Create product" redirects to the new product's Images page.
- Back-office product list shows each thumbnail or a "No image" badge.
- Concurrent uploads: last write wins.

**Django admin** — image fields read-only with a small preview and a link
"Manage images in the back office →"; same for `OrderItem` snapshots.
No second upload path.

**Storefront**
- Catalog cards: fixed 4:5 frame, `object-cover` crop (visual only);
  placeholders shown whole (`object-contain`) in the same frame.
- Detail page: full uncropped image. If extras exist, a DaisyUI CSS
  carousel (main first) + thumbnail row of anchor links. No extras →
  looks as today.
- `<img>` tags get `loading="lazy"` (not on the above-the-fold detail
  image), `decoding="async"`, and `width`/`height`.
- Thumbnails also in cart (`_cart_contents` partial), checkout summary,
  order confirmation, order history, order detail. Avoid N+1
  (`select_related`).

**Order snapshots** — `OrderItem` gets its own image field; `place_order`
copies the product's current thumbnail. **A failed copy must never fail
the order** (item just shows the placeholder). Order pages use the same
exists-or-placeholder property. Pre-existing orders show placeholders.

**Settings / media**
- `MEDIA_ROOT = BASE_DIR / "media"` (env-overridable), `MEDIA_URL`,
  `media/` gitignored.
- `SERVE_MEDIA` setting (env, default `True`, independent of `DEBUG`) —
  Django serves `/media/` when true. Add it and `MEDIA_ROOT` to
  `.env.example` with one-line explanations.
- Tests use a temporary `MEDIA_ROOT`.

**Seed data**
- Move baseline files to committed `products/seed_images/`, renamed to
  slugs; then delete `product-images/`. Seed maps files via an explicit
  table (slug → main + extras + alt text) and runs them through the same
  pipeline as employee uploads. Write real alt-text descriptions.
- Mapping: Calm Collar GPT Man → calm-collar; CrowdCalm Array No Text →
  crowdcalm-array; DreamWeaver Matrix GPT 3 → dreamweaver; Hush GPT No
  Text → hush; MindSync Duo → mindsync-duo; MindSync GPT 2 → mindsync;
  MoodSet GPT No Text → moodset; RecallPro → recallpro; Seraphine GPT Text
  → seraphine (flagship only); Veil GPT Text → veil; SoulSear No Text →
  soulsear-mark-i **only**; SyncRest GPT No Text → syncrest **main**,
  SyncRest GPT Text (poster) → syncrest **extra**. Verify slugs against
  `slugify()` output. All others keep placeholders.
- Seed also snapshots images onto its demo orders.

**Architecture**
- Pipeline lives in a **third deep module, `products/images.py`**
  (docstrings + type hints on every public function): e.g.
  `validate_image`, `set_main_image`, `remove_main_image`,
  `add_extra_image`, `remove_extra_image`, `move_extra`,
  `snapshot_for_order`. Forms call the validator; views stay thin;
  `place_order` and `seed` call into it.
- Update `CLAUDE.md` ("exactly two" → three deep modules; add the
  "Read before…" line) and add `docs/IMAGES.md` in the style of
  `docs/DISCOUNTS.md` / `docs/ADDRESSES.md`.

## Done means

`uv run pytest` green (validator rules and messages, pipeline order and
failure cleanup, missing-file → placeholder, extras limit/reorder,
snapshot-failure-doesn't-fail-order, admin read-only),
`uv run ruff check .` / `ruff format .` clean, `seed` runs, and the
catalog visibly shows images in the running app.

## Suggested skills

- `/run` — launch the app and confirm images, carousel and the Images page
  work for real, not just in tests
- `/security-review` — file uploads are an attack surface; run before
  finishing
- `/code-review` — correctness pass on the diff (transaction/on_commit
  ordering, file cleanup)
- `/simplify` — tidy after the feature works
- `/grill-me` — only if a genuinely new design question comes up that
  this doc doesn't settle
