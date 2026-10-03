# Templates, partials and assets

## Page structure

- Every page extends the project-level `templates/base.html` (DaisyUI navbar,
  footer motto). DaisyUI theme: `night`, set in `assets/css/source.css` and
  `data-theme` on `<html>`.
- Back-office pages extend `templates/backoffice/base.html` — the staff shell
  with the tab rail; the active tab comes from the view's `section` context
  entry.
- Every list view gets a designed empty state, not a blank page.

## Partials

- Partials live in `templates/<app>/partials/_<name>.html` — prefixed with an
  underscore, never extending `base.html`. HTMX endpoints render them
  (`_cart_contents`, `_add_button`, `_address_fields`), and so do plain
  `{% include %}`s (`_status_badge`, `_featured_badge`, `_address`).
- Form fields render through a `_field.html` partial. Checkout and the
  address form use `orders/partials/_field.html`; forms built on
  `StyledModelForm` (products, catalog, discount codes) use
  `products/partials/_field.html`.

## Forms and template helpers

- `StyledModelForm` (`products/forms.py`) is the DaisyUI-styled `ModelForm`
  base; `orders.DiscountCodeForm` builds on it too. `accounts.AddressForm`
  deliberately does not, so the apps don't import each other.
- `orders/context_processors.py` (`cart`) supplies `cart_item_count` (the
  navbar badge) and `cart_quantities` (per-product counts on the catalog's
  add buttons) to every page. The `cart_extras` template tags provide
  `quantity_of` to read the latter.

## Styling and assets

- Styling is Tailwind + DaisyUI classes only; no crispy-forms, no JavaScript
  beyond HTMX. The one exception is the product page's CSS-only gallery
  (`_gallery_slide.html`, `_gallery_thumb.html`): a hidden radio per image,
  with thumbnails and the wrap-around arrows as `<label for>`. Pairing radio
  N with slide N and thumbnail N can't be written as classes, so those state
  rules live in `assets/css/source.css` (nine positions, `MAX_IMAGES`).
  Each product-page photo goes through `_zoom_frame.html`: a blurred copy
  (`_picture.html` with `decorative=True`) fills the letterbox, and the
  full-size view is a `:target` overlay (`#zoom-<n>`, closed by `#close`,
  a fragment no element has, so the page doesn't jump).
- Image frames are 4:3 everywhere, matching the placeholder SVGs.
- `assets/css/source.css` is the Tailwind input; `assets/css/tailwind.css` is
  compiled output (gitignored, never edit).
- `assets/js/htmx.min.js` is vendored htmx 2.0.6 — no CDN.
- `assets/images/placeholders/` holds the per-category placeholder images
  (4:3 SVGs). Product and order images render only through
  `products/partials/_picture.html` from a `Picture`, never from a field;
  see [IMAGES.md](IMAGES.md).
- Line-item thumbnails (cart, checkout, order history, order detail,
  confirmation, back-office order detail) all use
  `products/partials/_thumbnail.html`: one fixed 64×48 frame. The `<img>` is
  sized itself (attributes plus `w-16 h-12`), never `w-full`/`h-full` of its
  frame, so a browser-cached stylesheet that lacks the frame's classes still
  can't render the photo at full size. Include it with `only`.
