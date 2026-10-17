# Plan: Product Reviews

> Source PRD: `prd/product-reviews.md` (builds on `prd/core-platform.md`).
> The PRD owns the requirements; this plan owns the sequence. Where a
> phase says "per the PRD", the PRD's wording is authoritative.

## Architectural decisions

Durable decisions that apply across all phases:

- **Owning app**: a new app, `reviews`, with the `reviews` namespace. It
  imports `products` and `orders`; neither imports it back. The product
  page reaches it through a template tag, as the wishlist does with
  `{% wishlist_button %}`. `dashboard` may import `reviews`.
- **No new deep module.** Eligibility, permission, visibility and the
  counted set live on `Review` and its queryset; views stay thin and
  class-based, and every HTMX endpoint returns a partial.
- **URLs** (all `reviews:`; the PRD fixes the names, this plan fixes the
  paths). Public actions use the product pk or the review pk; nothing in
  a URL names a reviewer.

  | Purpose | Path | Name |
  |---|---|---|
  | Create (POST) | `/reviews/product/<pk>/create/` | `create` |
  | List page / sort (GET) | `/reviews/product/<pk>/` | `list` |
  | Review partial, for Cancel (GET) | `/reviews/<pk>/` | `detail` |
  | Author edit form (GET) / save (POST) | `/reviews/<pk>/edit/` | `edit` |
  | Author delete confirm (GET) / delete (POST) | `/reviews/<pk>/delete/` | `delete` |
  | Staff edit form (GET) / save (POST) | `/reviews/<pk>/moderate/` | `moderate` |
  | Staff remove confirm (GET) / remove (POST) | `/reviews/<pk>/remove/` | `remove` |
  | Restore (POST) | `/reviews/<pk>/restore/` | `restore` |
  | Allow a new review (POST) | `/reviews/<pk>/allow-new/` | `allow_new` |
  | Back-office Reviews tab | `/backoffice/reviews/` | `manage` |

- **Querystring parameters**:
  - catalog and category pages: `sort=highest|lowest` and `rating`
    (1–5, repeated once per ticked star box), composing with `q`, `tag`
    and `category`
  - the product page's review list: `sort=newest|highest|lowest` and
    `page`
  - the product page itself: `review` (a review pk), from the Reviews
    tab's "View on product page" link
  - the Reviews tab: `q`, `sort=reviewer|product|newest`, `product` (pk),
    `rating` (stored half-star value), `author=customer|staff`,
    `status=live|removed` and `page`
  - the shared review endpoints (`detail`, `edit`, `delete`, `moderate`,
    `remove`): `from=manage` when used from the Reviews tab, so they
    answer with the tab's partials (added in Phase 10)
- **Models**:
  - `Review`: `user` (FK, cascade), `product` (FK, cascade,
    `related_name="reviews"`), `rating`, `headline`, `comment`, created
    and updated timestamps, `by_staff`, `edited_at`, `moderated_at`,
    `moderated_by` (FK user, `SET_NULL`), `removed_at`, `removed_by` (FK
    user, `SET_NULL`).
  - `rating` is a whole number of half stars, 2–10, through
    `IntegerChoices` with readable labels ("3½ stars"). A
    `CheckConstraint` enforces the range, and a property halves it for
    display.
  - `headline` up to 100 characters, optional. `comment` required, 10 to
    2,000 characters after trimming, enforced by the form and by model
    validation for live reviews only.
  - `UniqueConstraint` on (user, product).
  - `by_staff` is a snapshot of the author's `is_staff` when the review is
    first written and is never recomputed.
  - No other app's models change. `products` gains only a queryset method.
- **Eligibility to create**: an order item for the product on an order
  that is not cancelled, the same "counts as sold" rule as discount limits
  and the dashboard. It guards creation only. Staff are eligible on the
  same terms; unavailable products are reviewable.
- **The counted set**: reviews that are neither removed nor `by_staff`.
  Every average, count, sort and filter uses it. One `reviews` queryset
  method expresses it, and `ProductQuerySet.with_ratings()` repeats it by
  string lookup without importing `reviews`. That soft dependency is
  documented and guarded by a test.
- **Authorization**: one rule for every change: the author, or any user
  with `is_staff`. Anyone else gets a 404. Whether the user is the author
  decides which action applies (author edit versus staff edit, delete
  versus remove). The Reviews tab is gated by `StaffRequiredMixin`.
  Reviews are never registered in the Django admin.
- **HTMX**: partials follow `docs/TEMPLATES.md` (underscore-prefixed,
  never extending `base.html`) and are shared by the product page and the
  Reviews tab. Every state-changing endpoint is POST only; confirmation
  and edit-form GETs change nothing. Confirmation is an inline swap, never
  `hx-confirm`. The slot, each review, the section summary and the
  details-card average have stable `id`s, and the two averages update
  out of band (`hx-swap-oob`) whenever the counted set changes. Invalid
  submissions re-render the form in place with its errors.
- **Seed**: wipes reviews first, deterministic and idempotent. Seeded
  reviews come from a hand-written list kept like `CATALOG`, each by a
  customer holding a non-cancelled order for the product, with varied
  creation dates. The seed grows phase by phase.
- **Testing**: pytest with plain fixtures, per `docs/TESTING.md`.
  `uv run pytest` and `uv run ruff check .` are green at the end of every
  phase.

---

## Phase 1: Write a review

**User stories**: 4, 15, 16, 17, 18, 19, 20, 22, 23, 43, 50

### What to build

The tracer. The `reviews` app and the `Review` model with its
constraints, its rating choices and the eligibility rule. A template tag
puts a Reviews section below the product page's two-column grid, holding
the "Your review" slot. Its state comes from the database on every
render: a sign-in link with `?next=` back to the product for visitors,
"Only customers who've bought <name> can review it." for signed-in users
with no qualifying purchase, the form for eligible users, and the
author's own review once written. The form uses the DaisyUI
`rating rating-half` picker with no 0.5 option and a screen-reader label
on each radio. Submitting creates the review over HTMX and re-renders the
slot. A double-submit or a stale tab gets the existing review back in the
slot, not an error. A test fails if `Review` is registered in the admin.

### Acceptance criteria

- [x] A customer with a placed, shipped or delivered order for the product
      sees the form, and one with only a cancelled order sees the
      not-bought note.
- [x] A visitor sees "Bought this? Sign in to leave a review." linking to
      sign-in with `?next=` set to the product page.
- [x] Staff with a qualifying order see the form; an unavailable product's
      buyer can still review it.
- [x] Ratings below 2 or above 10 half stars are refused by the database;
      the picker offers 1.0 to 5.0 in half steps.
- [x] A headline over 100 characters, or a comment under 10 or over 2,000
      characters after trimming, re-renders the form in place with errors.
- [x] A valid POST creates the review, sets `by_staff` from the author's
      current `is_staff`, and returns the slot showing it.
- [x] A second create POST for the same user and product returns the
      existing review in the slot and creates nothing.
- [x] A create POST from an ineligible user creates nothing.
- [x] `Review` is not registered in the Django admin, and a test proves
      it.

---

## Phase 2: Reviews section and summary

**User stories**: 1, 2, 3, 5, 12, 14, 21, 45, 47, 48, 49 (staff review)

### What to build

The Reviews section gains its summary ("4.0 from 8 customer reviews", or
"No customer reviews yet") and, below the slot, everyone else's reviews:
stars, headline, comment, date, "Dana R." (or "A ThoughtTronix customer")
and a "Verified purchase" or "ThoughtTronix staff" badge. The viewer's
own review is shown only in the slot. The details card gains a small star
average and count linking to the section's anchor. The counted set is
introduced here, so staff reviews are shown but never counted. Creating a
review now updates the summary and the details-card average out of band
in the same response. The seed gains its hand-written reviews, more than
ten on at least one product, Casey's review of DreamWeaver, and a
delivered order for Emory with a staff review on it, so seeded orders go
from 52 to 53.

### Acceptance criteria

- [x] A visitor sees the summary and the list without signing in.
- [x] A product with only staff reviews reads "No customer reviews yet"
      and still lists the staff reviews, badged.
- [x] The reviewer name is first name and last initial, or "A
      ThoughtTronix customer" without a first name; neither the username
      nor the full name appears.
- [x] The viewer's own review appears in the slot and not in the list.
- [x] A create response carries the slot plus out-of-band summary and
      details-card average.
- [x] `by_staff` doesn't change when the author later gains or loses
      `is_staff`.
- [x] `seed` runs twice cleanly. Every seeded review's author holds a
      non-cancelled order for its product, Casey has reviewed DreamWeaver
      and nothing else, Emory has one staff review, and there are 53
      orders.

---

## Phase 3: Author edit

**User stories**: 13 (Edited), 24, 27, 28, 44

### What to build

Edit on the author's own review swaps the author form (rating, headline,
comment) into its place; Cancel fetches the review partial back
unchanged. Saving sets `edited_at`, re-renders the slot with an "Edited"
label and updates both averages out of band. The one permission rule is
introduced here: the author or staff, anyone else a 404. A staff member
editing their own review is an ordinary author edit. A later
cancellation of the author's order doesn't take away their right to
edit.

### Acceptance criteria

- [x] The edit-form GET changes nothing; Cancel returns the review as it
      was.
- [x] Saving changes rating, headline and comment, sets `edited_at`, and
      the review shows "Edited".
- [x] Another customer gets a 404 on the edit GET and POST.
- [x] A staff member editing their own review may change the rating and
      gets "Edited", not the staff label.
- [x] An author whose order was cancelled after reviewing can still edit.
- [x] Invalid input re-renders the form in place with errors and saves
      nothing.

---

## Phase 4: Author delete

**User stories**: 25, 26, 27

### What to build

Delete on the author's own review swaps in "Delete your review? This
can't be undone. [Delete] [Keep it]". Keep it puts the review back.
Delete really deletes the row and re-renders the slot, which shows the
form again if the author is still eligible, with both averages updated
out of band.

### Acceptance criteria

- [x] The confirm GET changes nothing; "Keep it" returns the review
      unchanged.
- [x] The delete POST removes the row and returns the slot in its new
      state, with out-of-band averages.
- [x] A still-eligible author can then write a new review.
- [x] An author whose order was cancelled after reviewing can still
      delete, and then sees the not-bought note.
- [x] Another customer gets a 404.

---

## Phase 5: Show more and sort

**User stories**: 10, 11

### What to build

The list shows ten reviews at a time. "Show more reviews" fetches the
next ten in the current sort and replaces its own button with them, plus
a new button if any remain. A sort menu (Newest, Highest rated, Lowest
rated) replaces the list from the first page. Ties are shown newest
first. Both go through `reviews:list`, which never includes removed
reviews or the viewer's own.

### Acceptance criteria

- [x] A product with more than ten other reviews shows ten and a "Show
      more reviews" button; the last page has no button.
- [x] Each sort orders correctly, with equal ratings newest first.
- [x] Show more keeps the current sort.
- [x] The list endpoint excludes the viewer's own review.
- [x] The seeded product with more than ten reviews exercises Show more.

---

## Phase 6: Catalog ratings

**User stories**: 6, 7, 8, 9, 14 (catalog)

### What to build

`ProductQuerySet.with_ratings()` annotates each product's customer
average and count from the counted set, by string lookup through
`reviews`, never importing the app. Its docstring records the soft
dependency, and a test in `reviews` checks that it agrees with the
`reviews`-side counted set. Catalog cards show the stars and count, or
"No reviews yet", from the annotation with no per-card query. The
catalog and category pages gain sort by rating, Highest rated or Lowest
rated (average, then more reviews, then name, unreviewed last either
way), and a rating filter of five star checkboxes. Each box is a
whole-star band of averages (4 is 4.0 up to, not including, 5.0; 5 is
exactly 5.0), any mix may be ticked, and unreviewed products are in no
band. Both compose with `q`, `tag` and `category`, survive pagination,
and show when they are active.

*Changed 2026-10-15 at the user's request, after the phase was first
built with the PRD's single "4 stars & up" filter and one rating sort.*

### Acceptance criteria

- [x] `with_ratings()` matches the `reviews` counted set, excluding
      removed and staff reviews.
- [x] A product with several tags and several reviews keeps the right
      average and count under the tag filter.
- [x] Highest and Lowest rated order by average, then count, then name,
      with unreviewed products last.
- [x] Ticked star boxes keep products whose average falls in any ticked
      band and drop unreviewed ones; ticking 4 and 5 is "4 stars & up".
- [x] Both combine with search, tag and category, and pagination links
      keep them.
- [x] Rendering the catalog adds no query per card.

---

## Phase 7: Staff edit on the product page

**User stories**: 13 (staff label), 31, 32, 33, 49 (staff-edited)

### What to build

Staff viewing a product page see Edit on every other review in the list.
It swaps in the staff form, headline and comment only, with no rating
field; Cancel puts the review back. Saving sets `moderated_at` and
`moderated_by`, and the review shows "Edited by ThoughtTronix staff",
which wins over "Edited" when both apply. The public page never names
the staff member. The seed gains one review edited by staff.

### Acceptance criteria

- [x] Staff see Edit on other people's reviews; customers don't.
- [x] The staff form has no rating field, and a POSTed rating is ignored.
- [x] Saving sets `moderated_at` and `moderated_by`, and the review shows
      the staff label without the staff member's name.
- [x] A review with both labels shows only the staff one.
- [x] A non-staff, non-author user gets a 404 on the moderate endpoints.
- [x] After `seed`, one review carries the staff label.

---

## Phase 8: Staff remove and the removed states

**User stories**: 29, 30, 34, 35, 49 (removed)

### What to build

Staff see Remove on every other review in the list. It swaps in "Remove
this review? [Remove] [Cancel]". Removing sets `removed_at` and
`removed_by`, swaps the review out of the list, and updates both
averages out of band. A removed review is hidden from every public list
and leaves every number. Its author's slot shows "Your review was removed
by ThoughtTronix staff" and no form, because the row still holds the
unique constraint. While its text remains, the author can delete it,
which blanks headline and comment, keeps the row and adds "You've
deleted its text." Blanking bypasses the comment-length rule. The seed
gains one removed review.

### Acceptance criteria

- [x] The confirm GET changes nothing; Cancel returns the review.
- [x] Removing hides the review from the product page, the list endpoint
      and every average, count, sort and filter, the catalog's included.
- [x] The author sees the removal notice and cannot create a new review,
      even with a direct POST.
- [x] The author's delete of a removed review blanks its text, keeps the
      row and shows the extra line; Delete is then gone.
- [x] A customer who isn't the author gets a 404 on the remove endpoints.
- [x] After `seed`, one review is removed and its author sees the notice.

---

## Phase 9: Back-office Reviews tab: list and filters

**User stories**: 36, 37, 39

### What to build

A "Reviews" tab in the back-office rail (`section="reviews"`) opens
`reviews:manage`, visible to all staff. It lists every review, removed
and staff ones included, 20 per page. Each row leads with the author's
profile picture, full name and username, then the product (linked to its
page), the rating, headline and comment, live or removed status,
"Edited", "Edited by <staff username>", and who removed it and when. A
sort menu offers Reviewer A–Z (the default: first name, then last name,
accounts without a first name last), Product A–Z and Newest, each ending
newest first. A search box matches every word against the author's
username and names, the product name, the headline and the comment.
Search and the filters for product, rating, author type and status
compose and survive pagination. Each live row links to "View on product
page", which opens the product page listed down to that review and
briefly highlights it (a CSS `:target` rule, no JavaScript).

*Changed 2026-10-16 at the user's request, after the phase was first
built with newest-first order and product-led rows: the reviewer sort,
the search, profile pictures and the jump link were added. The
querystring gains `q` and `sort=reviewer|product|newest`, and the
product page gains `review` (a review pk to list down to).*

### Acceptance criteria

- [x] Customers and visitors can't reach the tab; all staff can.
- [x] The list includes removed and staff reviews, 20 per page, sorted
      by reviewer name by default, or by product or newest on request.
- [x] Each filter narrows the list, filters combine, and pagination keeps
      them.
- [x] The search finds a review by any word of the author's username or
      name, the product, the headline or the comment, and composes with
      the filters and pagination.
- [x] Rows lead with the author's profile picture and name.
- [x] Rows name the staff member who last edited or removed the review.
- [x] A live row's "View on product page" opens the product page with
      that review listed and highlighted, however far down it sits;
      removed rows have no link.
- [x] The tab shows as active in the rail.

---

## Phase 10: Back-office Reviews tab: actions

**User stories**: 38, 40, 41, 42

### What to build

Each row offers its actions in place, using the same partials as the
product page and rendering the version that fits the Reviews tab. Live
reviews get Edit (the staff form) and Remove. Removed reviews get
Restore, offered only while the comment isn't blank, which clears
`removed_at` and `removed_by`, and Allow a new review, which really
deletes the row so its author can write again if still eligible. A staff
member's own reviews offer the author actions instead.

### Acceptance criteria

- [x] Edit and Remove on the tab swap the row in place, with the same
      results as on the product page.
- [x] Restore puts a removed review back on the product page and into the
      numbers.
- [x] Restore is absent, and refused on a direct POST, once the author has
      blanked the text.
- [x] Allow a new review deletes the row, and the still-eligible author
      then sees the form.
- [x] A staff member's own review offers Edit and Delete as the author,
      not the staff actions.
- [x] Every action's response is the tab's partial, not the product
      page's.

---

## Phase 11: Dashboard card

**User stories**: 46

### What to build

A new function in `dashboard/queries.py` returns the number of counted
reviews and their average rating in stars since the period start,
following the module's `since` convention, with a docstring, type hints
and tests. The dashboard gains a card showing "Reviews in this period"
and "Average customer rating in this period", following the existing
date range. An empty period shows zero and a dash.

### Acceptance criteria

- [ ] The function counts only counted reviews created at or after
      `since`, and all of them when `since` is `None`.
- [ ] The average is in stars (1.0 to 5.0), not half stars.
- [ ] An empty period returns zero and no average, and the card shows a
      dash.
- [ ] Changing the dashboard's period changes the card.
- [ ] The function has a docstring and type hints.

---

## Phase 12: Documentation and wrap-up

**User stories**: none of its own (the PRD's Further Notes)

### What to build

`docs/REVIEWS.md` covers the model, the eligibility and permission rules,
the counted set, the soft dependency in `with_ratings()`, the HTMX
endpoints and partials, and the seed. CLAUDE.md gains a "Read before…"
line pointing to it and a `reviews/` entry in its project layout. The
core PRD gets a dated amendment pointing to `prd/product-reviews.md`,
not a rewrite. Finally, `seed` is run before `db.sqlite3` is committed.

### Acceptance criteria

- [ ] `docs/REVIEWS.md` exists and CLAUDE.md points to it.
- [ ] CLAUDE.md's project layout lists `reviews/`.
- [ ] The core PRD carries a dated amendment rather than a rewrite.
- [ ] The seed's docstrings and count comments say 53 orders.
- [ ] `uv run pytest` is green and `uv run ruff check .` is clean.
