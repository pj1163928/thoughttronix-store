# Handoff: image sizing, product gallery and product-page polish

## Status

The design is finished and approved through a `/grill-me` interview. **No code has been
changed yet**, and the working tree was clean at `862eb6b`. Next step: implement the
design below, then run `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`
and `uv run python manage.py tailwind build`.

Read first: [CLAUDE.md](CLAUDE.md), [docs/TEMPLATES.md](docs/TEMPLATES.md),
[docs/IMAGES.md](docs/IMAGES.md), [docs/TESTING.md](docs/TESTING.md).

## What the user asked for

Make the product images and the product-page menu look better: consistent tile sizes,
a styled top navigation, space between the text and the image, a gallery that scrolls
sideways instead of a growing list, and placeholders instead of "No image" in the
back office.

## Decisions (all confirmed by the user)

1. **4:3 frames everywhere**, to match the placeholder SVGs (`PLACEHOLDER_SIZE = (400, 300)`
   in [products/images.py](products/images.py)).
   - Catalog cards: change `aspect-[4/5]` to 4:3 in [templates/products/catalog.html](templates/products/catalog.html).
     Photos crop with `object-cover`, the default in `_picture.html`.
   - Back office: change the 4:5 frames to 4:3 in
     [manage_products.html](templates/products/manage_products.html),
     [manage_product_images.html](templates/products/manage_product_images.html),
     [manage_product_image_confirm_remove.html](templates/products/manage_product_image_confirm_remove.html)
     and [partials/_image_picker.html](templates/products/partials/_image_picker.html).
   - Line-item thumbnails: change [partials/_thumbnail.html](templates/products/partials/_thumbnail.html)
     from 48×60 to **64×48** (`w-16 h-12`). Keep its rule that the `<img>` is sized itself
     and never `w-full`/`h-full`, and update the width/height attributes to match.
2. **Product page main frame:** a fixed 4:3 frame using `object-contain`, so the whole photo
   is shown with letterboxing on `bg-base-200`. It replaces today's unbounded `h-auto w-full`.
3. **One gallery, main image first:** the thumbnails are `product.display_image` followed by
   `product.extra_pictures`, and the first one is selected on load. Remove the separate
   "More images" carousel. With only one image, hide the strip.
4. **No JavaScript.** The project rule is "no JS beyond HTMX", so build a **CSS-only radio
   gallery**:
   - Hidden radios, one per image, with thumbnails as `<label for>`.
   - Each large image is shown when its radio is checked. Tailwind v4 `has-[]`/`peer`
     variants or a `:has()` rule work for this.
   - The selected thumbnail gets a `ring`/border.
5. **Navigating the images:**
   - The strip shows about 3 thumbnails, scrolls sideways, and uses scroll-snap.
   - Wrap-around ❮ ❯ arrows on the main image are labels for the previous/next radio, plus an
     "n / total" badge.
   - Known and accepted limitation: arrow clicks don't scroll the strip to follow.
6. **Breadcrumb bar** on [detail.html](templates/products/detail.html):
   - A rounded, shaded bar (`bg-base-200 rounded-box px-4 py-3`) with more space below it.
   - Inline-SVG icons: a grid for Catalog, a tag for the category.
   - Links hover in `text-primary`, and the current product name is bold.
   - Same three links as today.
7. **Text spacing:**
   - Widen the column gap to about 4rem on md+ (`md:gap-16`).
   - Put the name, price, badges, add button, description and tags in a padded card
     (`card bg-base-200` or similar, `p-6`/`p-8`).
8. **Back-office list:**
   - Replace the `{% if product.has_image %}…No image` branch with the category
     placeholder in the same 4:3 frame.
   - Fade it (`opacity-50` or similar) and give it the tooltip "No photo yet — manage images".

## Follow-on edits

- **Tests in [products/test_image_views.py](products/test_image_views.py)** check the old markup,
  so rewrite them for the new behaviour:
  - "No image" (around line 593)
  - "More images", the `carousel` class (around lines 622–643)
  - `href="#more-1"` (around line 657)
  - New assertions: the main image is first in the gallery, there's one radio per image,
    the arrows wrap around, the strip is hidden for a single image, and the placeholder
    appears in the back-office list.
- **[docs/IMAGES.md](docs/IMAGES.md):** rewrite the sentence about the main image being alone
  with extras in a "More images" carousel.
- **[docs/TEMPLATES.md](docs/TEMPLATES.md):** change the 48×60 thumbnail note to 64×48, and
  mention the CSS-only gallery.
- **[products/models.py](products/models.py):** reword the `extra_pictures` docstring (around
  line 184). Its behaviour stays the same: extras only, missing files skipped. The template
  combines it with `display_image`.
- **[PROMPTS.md](PROMPTS.md):** append an entry for this work. Append only, never rewrite.

## Gotchas

- `assets/css/tailwind.css` is compiled output and should never be edited. Rebuild it so new
  classes such as arbitrary aspect ratios and `has-[]` variants exist. A recent commit
  (`f5a2bf9`) fixed oversized images partly caused by stale CSS, so hard-refresh when checking
  in a browser.
- Templates must render images only through `products/partials/_picture.html` from a
  `Picture`, never from a field. Placeholders always get `object-contain`.
- Tests may need `django_capture_on_commit_callbacks(execute=True)` for file deletions
  (see IMAGES.md).

## Suggested skills

- `run`: start the dev server (`uv run python manage.py tailwind runserver`) and look at the
  catalog, a product with several images, one with no image, the cart and the back-office
  product list.
- `code-review`: review the diff before finishing.
- `simplify`: tidy the gallery template markup once it works.
