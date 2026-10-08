# Product images

Images live in `products/images.py`, the third deep module. Nothing else
writes, deletes or validates an image file. A product has one main image
on `Product.image` and up to eight ordered extras in `ProductImage`.
The product page shows one gallery: the main image first, then the
extras, each shown whole in a fixed 4:3 frame. A blurred, cropped copy
of the photo fills the sides it leaves empty, and clicking the photo
opens it full size (`_zoom_frame.html`). An extra never stands in for the
main image by itself: remove the main image and the store shows the
placeholder. It becomes main only when an employee chooses it
(`make_main`, a swap of stored names, not of files). Each stored image is
two WebPs, a *display* file (longest side 1200 px) and a *thumbnail*
(600 px wide). The upload itself is not kept.

## Never load a missing file

Templates never read an image field. They render a `Picture` (url,
width, height, alt, `is_placeholder`) through
`products/partials/_picture.html`, taken from `Product.card_image`
(thumbnail), `Product.display_image` (display file),
`Product.extra_pictures` or `OrderItem.thumbnail`. Each returns the media URL only if the field
is set **and** the file is in storage right now. Otherwise it returns
the category placeholder. Media is served under `SERVE_MEDIA`, which is
deliberately independent of `DEBUG`, so the check and the server agree.

## One set of rules, one pipeline

`validate_image` is the only gate for product photos, and
`validate_avatar` for profile pictures; both run the same checks
(`_checked`). Forms call it in `clean_image`, and the
seed calls it on the baseline photos. It checks the file size, the type
(by content, not by name), the megapixel count (before decoding), the
minimum side, the aspect ratio, animation and a clean decode. Each
refusal is one sentence that names the file and the values it found.
EXIF rotation, CMYK and transparency are fixed, not refused.

`set_main_image` and `add_extra_image` then write the new files under
fresh random names, save the row in a transaction, and delete the old
files in `transaction.on_commit`. On failure they remove the new files
and leave the old image untouched. `post_delete` receivers delete the
files of products, extras and order lines. In tests, pass
`django_capture_on_commit_callbacks(execute=True)` to see a deletion.

## Back office and admin

The product form (create and edit) has an **Upload images** button. The
chosen files go straight to `StageProductImagesView` over HTMX. It checks
each file and *holds* the ones that pass (`stage_uploads` and
`hold_image`, under `media/pending/`, swept after a day). The view
returns `_image_picker.html`: a preview of every image with a "main
image" radio button and a ✕ to discard an upload. When editing, the
product's saved images are offered as choices too. The choice travels
as `main_image`: `main`, `extra-<pk>` or `held-<token>`. On save,
`attach_uploads` adds the held images, and `make_main` then promotes the
chosen one.

Holding also protects against browsers that empty a file input when a
form comes back with errors. A typo in the price never costs the
employee their photos. The form's `upload` field catches any files still
in the input when Save is pressed. Held tokens come from the POST and
are untrusted: `held_images` accepts only well-formed tokens for files
that exist.

Each product's Images page (`products:manage_product_images`) is where
saved images are managed: replace, remove, reorder, make main, alt text. The
image fields are `editable=False`, so the Django admin shows read-only
previews and links to that page. The admin is not a way to upload.

## Order snapshots

`place_order` registers `snapshot_for_order` with `on_commit(robust=True)`.
After the order commits, each line gets its own copy of the product's
thumbnail. A failed copy leaves that line on its placeholder and can
never fail or roll back the purchase. Use a lambda, not
`functools.partial`, for a robust callback: Django logs a failure by
`__qualname__`, and a partial doesn't have one. The seed builds orders
directly, so it calls `snapshot_for_order` itself.

## Profile pictures

`User.avatar` holds one square WebP, `AVATAR_SIZE` (180) pixels a side.
`validate_avatar` applies every product rule except the minimum side
(180, not 600), then crops the centre square and scales it.
`ProfileForm.clean_photo` calls it, and `ProfileForm.save` hands the
result to `set_avatar` (or calls `remove_avatar`). Both delete the old
file on commit, and a `post_delete` receiver on `User` deletes it with the
account. Templates render `User.avatar_picture`, a `Picture` that falls
back to the silhouette at `assets/images/placeholders/avatar.svg` when
there is no picture or its file is missing. The navbar's profile menu and
the Account page show it at 36, 48 and 64 pixels, and Edit profile at
full size.
