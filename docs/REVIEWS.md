# Product reviews

Customer reviews of products, moderated by staff after publication. Lives
in its own app, `reviews/`, which imports `products` and `orders`; neither
imports it back. The product page reaches it through template tags
(`reviews_extras`), as the wishlist does with `{% wishlist_button %}`.
`dashboard` may import `reviews`. The requirements are in
`prd/product-reviews.md`; there is no deep module, so the rules below live
on `Review` and `ReviewQuerySet`.

## Model

- `Review` — one per user per product (`UniqueConstraint`). `rating` is a
  whole number of **half stars, 2–10** (`Review.Rating`, labels like "3½
  stars"), held in range by a `CheckConstraint`; `stars` halves it for
  display, and averages are halved after aggregating. Integers keep
  sorting, averages and the constraint exact.
- `headline` is optional, up to 100 characters. `comment` is 10–2,000
  characters once trimmed, enforced by `ReviewForm` and by `Review.clean`
  — for live reviews only, because an author's delete of a removed review
  blanks it.
- `by_staff` is a snapshot of the author's `is_staff`, taken in `save` on
  the first write and never recomputed. A staff member who leaves keeps
  the staff badge; a customer who joins doesn't gain one.
- `edited_at` marks an author edit ("Edited"); `moderated_at` and
  `moderated_by` a staff edit ("Edited by ThoughtTronix staff", which
  wins when both apply); `removed_at` and `removed_by` a removal. Both
  staff FKs are `SET_NULL`. `created_at` is a `default`, not
  `auto_now_add`, so the seed can backdate.
- The public page names an author by `author_name` ("Dana C.", or "A
  ThoughtTronix customer" without a first name) and `author_picture`,
  never by username or full name. The back office shows both.

## Who may do what

- **Write**: `Review.can_write` — an order line for the product on an
  order that isn't cancelled, the same "counts as sold" rule as discount
  limits and the dashboard. Staff qualify on the same terms; unavailable
  products are reviewable. It guards **creation only**: a later
  cancellation leaves the review and its author's rights alone.
- **Change**: `ReviewQuerySet.changeable_by` — the author, or anyone with
  `is_staff`. Anything else is a 404. `ReviewActionMixin` then decides
  which change applies: the author edits (rating included) and deletes
  their own review, staff included; staff moderate (headline and comment,
  never the rating) and remove **someone else's**. A removed review is
  reachable only by its author, except through Restore and Allow a new
  review, which reach removed reviews alone.
- **Delete** of a live review really deletes it, and an eligible author
  may write again. **Remove** keeps the row, so it still holds the unique
  constraint and the author can't repost; their slot shows the removal
  notice. The author's delete of a removed review (`delete_text`) blanks
  its words and keeps the row. **Restore** works only while the comment
  isn't blank (`can_restore`); **Allow a new review** deletes the removed
  row for good.
- Reviews are **not in the Django admin**; the back office's Reviews tab
  is the one moderation surface. A test fails if `Review` is registered.
  No review action sends email or writes a `SecurityEvent`.

## The counted set

`ReviewQuerySet.counted()` — live reviews not `by_staff`. Every average,
count, sort and filter uses it: the product page summary and details card
(`rating_summary`), the catalog, and the dashboard card
(`dashboard.queries.review_summary`). Staff reviews are shown, badged
"ThoughtTronix staff", but never counted. Removed reviews are hidden from
every public list (`live()`, `listed_for`).

## The soft dependency in `with_ratings()`

`ProductQuerySet.with_ratings()` annotates `rating_count` and
`rating_average` (in stars) for the catalog's cards, its rating sort
(`by_rating`) and its star-band filter (`rated_in`). `products` never
imports `reviews`, so it repeats the counted set by string lookup through
the `reviews` reverse relation (`reviews__removed_at`, `reviews__by_staff`,
`reviews__rating`). Rename any of those fields and the annotation would go
quietly wrong, so `test_with_ratings_agrees_with_the_counted_set` in
`reviews/tests.py` checks the two sides agree. Keep them in step.

## HTMX

Every state-changing endpoint is POST only; the edit-form and
confirmation GETs change nothing. Confirmation is an inline swap, never
`hx-confirm`. Invalid submissions re-render the form in place.

| Name | Path | What it answers with |
|---|---|---|
| `reviews:create` | `/reviews/product/<pk>/create/` | the slot, plus both averages out of band; an existing review comes back instead of an error |
| `reviews:list` | `/reviews/product/<pk>/` | `_review_page`: ten reviews in `?sort=` from `?page=`, then Show more if any remain |
| `reviews:detail` | `/reviews/<pk>/` | the review as it is — what Cancel and "Keep it" fetch |
| `reviews:edit` | `/reviews/<pk>/edit/` | GET the author form; POST the slot plus averages |
| `reviews:delete` | `/reviews/<pk>/delete/` | GET the confirmation; POST the slot plus averages |
| `reviews:moderate` | `/reviews/<pk>/moderate/` | GET the staff form; POST the review |
| `reviews:remove` | `/reviews/<pk>/remove/` | GET the confirmation; POST nothing in its place, plus averages |
| `reviews:restore` | `/reviews/<pk>/restore/` | the Reviews tab's row |
| `reviews:allow_new` | `/reviews/<pk>/allow-new/` | a note in the row's place |
| `reviews:manage` | `/backoffice/reviews/` | the Reviews tab (a full page) |

- **Stable ids**: `#reviews` (the section, the details card's anchor),
  `#reviews-summary`, `#details-rating`, `#your-review` (the slot),
  `#review-list`, `#show-more-reviews`, `#review-<pk>` on each review and
  `#review-row-<pk>` on each tab row. The two averages update with
  `hx-swap-oob` whenever the counted set changes (`_slot_update`,
  `_review_removed`); a staff edit can't change the rating, so it swaps
  nothing out of band.
- **Shared partials**: the product page and the Reviews tab share the
  form and confirmation partials. On the tab, `back_office` is in the
  context and the `{% review_url %}` tag adds `?from=manage` to every
  action URL, so the view answers with the tab's row (`_manage_review`,
  or `_manage_review_deleted`) instead of the product page's partials.
- **The slot** (`_your_review`) is rebuilt from the database by
  `views.slot_context` on every render: sign-in link with `?next=`,
  not-bought note, form, the review, or the removal notice.
- **The list** never includes the viewer's own review (it's in the slot)
  or a removed one. Sorts are `SORTS` in `reviews/models.py`, each ending
  newest first. `?review=<pk>` on the product page — the tab's "View on
  product page" link — lists down to that review, and the `:target` rule
  in `assets/css/source.css` highlights it briefly.
- The rating picker is DaisyUI `rating rating-half` radios with no 0.5
  option, each labelled from `Review.Rating` for screen readers.

## Back office

The Reviews tab (`section="reviews"`, `StaffRequiredMixin`) lists every
review, removed and staff ones included, 20 a page. `ReviewFilterForm`
reads `q`, `sort=reviewer|product|newest` (`MANAGE_SORTS`, Reviewer A–Z
by default), `product`, `rating` (stored half stars),
`author=customer|staff` and `status=live|removed`; they compose through
`ReviewQuerySet.filtered` and survive pagination. Rows name the author and
the staff member who edited or removed the review.

## Seed

The seed wipes reviews and rebuilds them from `REVIEWS` in
`products/management/commands/seed.py`, a hand-written list kept like
`CATALOG`, each review run through `full_clean`. Every author holds a
non-cancelled order for what they review: each background reviewer gets
one delivered order of it, `REVIEWED_AFTER_DAYS` before their first
review. Seraphine has twelve reviews averaging exactly 4.0, enough for
Show more. `customer` (Casey) has reviewed DreamWeaver and nothing else.
`employee` (Emory) has one delivered order and a staff review of the
FocusBand Workplace Edition. `STAFF_EDIT` gives one review the staff
label and `REMOVAL` removes one. Seeded orders total **53**.
