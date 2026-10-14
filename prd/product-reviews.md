# PRD: Product Reviews

*Builds on `prd/core-platform.md`. The design interview behind it (Q1–Q25,
2026-10-14) is logged at the top of `PROMPTS.md`, and `HANDOFF.md` is its
decision record. Decisions taken while writing this PRD, which the
interview left open, are marked **(PRD-stage)**.*

---

## Problem Statement

A ThoughtTronix customer deciding whether to buy a product has only the
store's own words to go on: the tagline, the description and the photos.
They can't see what anyone who owns it thinks, and the catalog gives them
no way to find the products other customers like best. A customer who has
bought something, loved it or regretted it, has nowhere to say so.

Staff have no view of how customers feel about the catalog. If customer
opinion were published, staff would also need a way to deal with a review
that is abusive, off-topic or wrong, without silencing honest criticism or
leaving the author confused about what happened to their words.

## Solution

Customers who have bought a product can leave **one review of it**: a
**star rating from 1 to 5 in half stars**, an optional headline and a
written comment. A review appears on the product page as soon as it is
posted. Its author can edit or delete it at any time, and every one of
those actions happens **in place, without a page reload**.

Every product page gains a **Reviews section** with the customer average,
the visitor's own review (or a form, or a short note saying why they
can't write one), and everyone else's reviews, ten at a time, sortable by
newest, highest or lowest rating. Each review shows a "Verified purchase"
badge and a privacy-safe name such as "Dana R.". The catalog shows each
product's average on its card and gains **Sort by rating** and **4 stars
& up**.

**Staff moderate after publication.** On the product page, and from a new
**Reviews tab** in the back office, staff can correct a review's headline
and comment (labelled "Edited by ThoughtTronix staff") or remove it. A
removed review disappears everywhere, its author is told it was removed,
and they can't simply post it again. Staff can restore it or let the
customer write a new one. Staff may also review products they have bought
themselves. Their reviews are badged as staff and never counted in a
product's numbers.

The staff dashboard gains a card showing how many customer reviews arrived
in the selected period and their average rating.

## User Stories

**Visitor (not signed in)**

1. As a visitor, I want to read a product's reviews without signing in, so that I can judge it before I create an account.
2. As a visitor, I want to see a product's average customer rating and how many customer reviews it has, written as "4.0 from 8 customer reviews", so that I know how much weight to give the average.
3. As a visitor, I want a product with no customer reviews to say "No customer reviews yet", so that an empty section isn't mistaken for a broken one.
4. As a visitor, I want a "Bought this? Sign in to leave a review." link that brings me back to the product after signing in, so that I can review something I bought without hunting for it again.

**Shopping with reviews**

5. As a shopper, I want a small star average and review count in the product's details card that links down to the Reviews section, so that I see the rating next to the price and can jump to the detail.
6. As a shopper, I want every catalog card to show its star average and review count, or "No reviews yet", so that I can compare products at a glance.
7. As a shopper, I want to sort the catalog by rating, highest average first, more reviews breaking ties, then name, with unreviewed products last, so that I can find the best-liked products.
8. As a shopper, I want a "4 stars & up" filter that shows only products averaging at least 4.0, so that I can skip products customers didn't like.
9. As a shopper, I want the rating sort and filter to combine with search, tag and category, so that I can find the best-rated product of the kind I'm looking for.
10. As a shopper, I want reviews to be listed ten at a time with a "Show more reviews" button that adds the next ten below, without reloading the page, so that a long list doesn't swamp the page.
11. As a shopper, I want to sort reviews by Newest, Highest rated or Lowest rated without reloading the page, with ties shown newest first, so that I can read the praise or the complaints first.
12. As a shopper, I want each review to show its star rating, headline, comment, date, the reviewer's first name and last initial, and a "Verified purchase" badge, so that I know a real buyer wrote it.
13. As a shopper, I want a review a customer has changed to say "Edited", and one staff have changed to say "Edited by ThoughtTronix staff", so that I know the text isn't exactly what was first posted.
14. As a shopper, I want staff reviews badged "ThoughtTronix staff" and left out of every average, count, sort and filter, so that the store's own people can't inflate a product's rating.

**Customer writing a review**

15. As a signed-in customer who hasn't bought a product, I want to be told "Only customers who've bought <product> can review it", so that I understand why there is no form.
16. As a customer who has bought a product, I want a review form on its page, so that I can share my opinion where other shoppers will see it.
17. As a customer, I want an order I placed, had shipped or had delivered to count as a purchase, but not a cancelled one, so that only real buyers can review.
18. As a customer, I want to be able to review a product that is no longer available, so that I can still share my opinion of something I bought.
19. As a customer, I want to pick a rating from 1 to 5 stars in half-star steps by clicking the stars, so that I can say exactly how much I liked it.
20. As a customer, I want an optional headline of up to 100 characters and a required comment of 10 to 2,000 characters, so that my review says something useful without becoming an essay.
21. As a customer, I want my review to appear on the product page as soon as I submit it, with the average and count updating in the same moment and no page reload, so that I can see it worked.
22. As a customer, I want to be able to write only one review per product, and a double-click or a second tab to show me my existing review rather than an error, so that I can't post twice by accident.
23. As a customer, I want my own review shown in a "Your review" slot above everyone else's and not repeated in the list below, so that I can find it straight away.

**Customer managing their review**

24. As a customer, I want to edit my review's rating, headline and comment in place, with Cancel putting it back unchanged, so that I can update my opinion without leaving the page.
25. As a customer, I want to delete my review after an inline "Delete your review? This can't be undone. [Delete] [Keep it]" confirmation, so that I can't delete it by accident.
26. As a customer who has deleted my review, I want to be able to write a new one if I'm still eligible, so that deleting isn't permanent.
27. As a customer whose order was cancelled after I reviewed, I want to keep my review and still be able to edit or delete it, so that a later refund doesn't make my words disappear.
28. As a customer, I want nobody but me and the store's staff to be able to edit or delete my review, so that my words can't be changed by other customers.
29. As a customer whose review staff removed, I want to see "Your review was removed by ThoughtTronix staff" where my review was, so that I know what happened rather than thinking it failed.
30. As a customer whose review was removed, I want to be able to delete its text, after which the notice adds "You've deleted its text", so that I can take my words out of the store's records.

**Staff moderating**

31. As a staff member, I want Edit and Remove controls on every review on the product page, so that I can deal with a problem review where I see it.
32. As a staff member, I want to correct a review's headline and comment but not its rating, so that I can remove abuse without changing what the customer thought of the product.
33. As a staff member, I want my edit to be labelled "Edited by ThoughtTronix staff" without my name on the public page, so that shoppers know the store changed it and I stay anonymous.
34. As a staff member, I want to remove a review after an inline "Remove this review? [Remove] [Cancel]" confirmation, hiding it everywhere and taking it out of every number, so that a problem review stops affecting shoppers.
35. As a staff member, I want a removed review to stop its author from simply posting it again, so that removal means something.
36. As a staff member, I want a "Reviews" tab in the back office listing every review, newest first, so that I can moderate without visiting each product.
37. As a staff member, I want to filter that list by product, rating, author type (customer or staff) and status (live or removed), so that I can find the reviews that need attention.
38. As a staff member, I want to edit, remove, restore and allow a new review from the Reviews tab in place, without reloading the page, so that moderating many reviews is quick.
39. As a staff member, I want to see which staff member last edited or removed each review, so that moderation is accountable inside the team.
40. As a staff member, I want to restore a removed review whose text is still there, so that a mistaken removal can be undone.
41. As a staff member, I want "Allow a new review" to delete a removed review for good, so that its author can write a fresh one.
42. As a staff member, I want Restore to be unavailable once the author has deleted the text, so that an empty review can never go back on the page.

**Staff reviewing**

43. As a staff member who has bought a product, I want to review it like any customer, so that I can share my own experience.
44. As a staff member, I want editing my own review to be an ordinary author edit, rating included, labelled just "Edited", so that my own review isn't treated as moderation.
45. As a staff member, I want my review to keep its staff badge and stay out of the numbers even if I later leave the staff, and a customer's review not to become a staff review if they join, so that a review's status reflects who wrote it at the time.

**Store owner and staff analytics**

46. As a staff member, I want a dashboard card showing "Reviews in this period" and "Average customer rating in this period", following the dashboard's existing date range and excluding staff and removed reviews, so that I can see how customer opinion is trending.

**Developer**

47. As a developer, I want `seed` to create hand-written, product-specific reviews only from customers who really hold a non-cancelled order for that product, spread across ratings including half stars, with enough on some products to need "Show more", so that the demo looks real and obeys the feature's own rules.
48. As a developer, I want the seeded `customer` to have reviewed DreamWeaver and left their other purchases unreviewed, so that both the "Your review" and the form states can be demoed.
49. As a developer, I want the seed to include one review edited by staff, one removed by staff, and a staff review by `employee`, so that every label and moderation state can be demoed after every reset.
50. As a developer, I want reviews kept out of the Django admin, with a test that fails if they are registered, so that there is exactly one place to moderate them.

## Implementation Decisions

### Shape

- A new app, **`reviews`**. It imports `products` and `orders`; neither
  imports it back. The product page reaches it through a template tag, as
  the wishlist does with `{% wishlist_button %}`. `dashboard` may import
  `reviews`, as it already imports `orders` and `products`.
- No new deep module. Eligibility, permission and visibility rules live on
  the `Review` model and its manager/queryset; views stay thin. Class-based
  views throughout, each HTMX endpoint returning a partial.
- **One permission rule** governs every change: the review's author, or
  any user with `is_staff`. Anything else is a 404, as for another
  customer's wishlist line. What the user may do (author edit versus staff
  edit, delete versus remove) depends on whether they are the author.
- Reviews are **not registered in the Django admin**. The back-office
  Reviews tab is the only moderation surface.

### Data model

- **`Review`**: user (FK, cascade), product (FK, cascade, reverse name
  `reviews`), rating, headline, comment, created and updated timestamps,
  `by_staff`, `edited_at`, `moderated_at`, `moderated_by` (FK to user,
  `SET_NULL`), `removed_at`, `removed_by` (FK to user, `SET_NULL`).
- **Rating** is stored as a whole number of **half stars, 2–10**, through
  `IntegerChoices` with readable labels ("3½ stars"). A `CheckConstraint`
  enforces the range. A property halves it for display, so templates and
  averages speak in stars (1.0–5.0).
- **Headline**: up to 100 characters, optional. **Comment**: required,
  10–2,000 characters after trimming, enforced both by the form and by
  model validation.
- A **`UniqueConstraint` on (user, product)**. Creating when a review
  already exists, from a double-submit or a stale tab, returns the
  existing review in the "Your review" slot rather than an error.
- **`by_staff`** is a snapshot of the author's `is_staff` taken when the
  review is first written and never recomputed.
- **Eligibility to create**: the user has an order item for the product on
  an order whose status is not cancelled. This is the same "counts as
  sold" rule that discount limits and the dashboard use. It guards
  **creation only**. A later cancellation leaves an existing review and
  its author's rights untouched. Staff are eligible on the same terms.
- **The "counted" set**: every average, count, sort and filter, in the
  catalog, on the product page and on the dashboard, uses only reviews
  that are **neither removed nor `by_staff`**. One queryset method on the
  `reviews` side expresses it, and the catalog annotation repeats the same
  rule (see below).
- **Visibility**: removed reviews are hidden from every public list,
  including the product page and the catalog. Staff reviews are shown,
  badged, but never counted.

### Edits, deletes and removal

- **Author edit** may change rating, headline and comment, and sets
  `edited_at` ("Edited"). A staff member editing their own review is an
  author edit.
- **Staff edit** of someone else's review uses a separate form with
  **headline and comment only**, no rating field. It sets `moderated_at`
  and `moderated_by` ("Edited by ThoughtTronix staff"). The public page
  never names the staff member; the back office does.
- When a review carries both labels, the public page shows the staff one.
  **(PRD-stage)**
- **Author delete** of a live review is a real deletion. The author may
  review again if still eligible.
- **Staff remove** sets `removed_at` and `removed_by`. The review is
  hidden everywhere and leaves every number. Its author sees "Your review
  was removed by ThoughtTronix staff" in the "Your review" slot and cannot
  post a new one, because the row still holds the unique constraint.
- **Author delete of a removed review** blanks headline and comment and
  keeps the row, so reposting stays blocked. The notice adds "You've
  deleted its text." Blanking bypasses the comment-length rule, which
  applies to form and model validation for live reviews only.
- **Restore** (staff, back office only) clears `removed_at` and
  `removed_by`. It is offered only while the comment is not blank.
- **Allow a new review** (staff, back office only) really deletes a
  removed review, freeing the author to write again if still eligible.
- No removal-reason field. Removal sends no email and records no
  `SecurityEvent`.

### Product page

- A **full-width Reviews section** below the existing two-column grid, in
  order: the summary (average stars and count), the "Your review" slot,
  then everyone else's reviews.
- A **small star average and count in the details card**, linking to the
  section's anchor.
- **"Your review" slot states**, decided from the database on every
  render:
  - anonymous: "Bought this? Sign in to leave a review." with `?next=`
    back to the product
  - signed in, no qualifying purchase and no review: "Only customers
    who've bought <name> can review it."
  - eligible, no review: the form
  - has a live review: the review, with Edit and Delete
  - review removed by staff: the removal notice, with Delete while its
    text remains
- **Reviewer name**: first name and last initial ("Dana R."), or "A
  ThoughtTronix customer" when the account has no first name. Never the
  username, which is a sign-in identifier, and never the full name.
- **Badges**: "Verified purchase", or "ThoughtTronix staff" when
  `by_staff`. A review whose order was later cancelled keeps "Verified
  purchase": the badge records that the purchase qualified when the
  review was written. **(PRD-stage)**
- **The list** excludes the viewer's own review (it is in the slot) and
  removed reviews. It shows ten at a time. "Show more reviews" appends the
  next ten in the current sort. The sort menu (Newest, Highest rated,
  Lowest rated; ties newest first) replaces the list from the first page.
- **Staff viewing the page** see Edit and Remove on every other review in
  the list, alongside the Edit and Delete on their own.

### Rating picker

- DaisyUI `rating rating-half`: radio inputs with half masks. The first
  half star (0.5) is absent, so the minimum is 1.0. No JavaScript.
- Labels on each radio for screen readers, taken from the `IntegerChoices`
  labels.

### HTMX

- **Create, author edit and delete** re-render the "Your review" slot. The
  section summary and the details-card average update in the same
  response through `hx-swap-oob`.
- **Edit** swaps the form into the review's place; **Cancel** swaps the
  review back, unchanged. The same applies to a staff edit in the list or
  in the back office.
- **Confirmation** of delete and remove is an inline swap (the review is
  replaced by "Delete your review? This can't be undone. [Delete] [Keep
  it]" or "Remove this review? [Remove] [Cancel]"), not a separate page
  and not `hx-confirm`.
- **Staff remove** on the product page swaps the review out of the list
  and updates the summary and details-card average out of band.
- **Show more** and **sort** return list partials; Show more replaces its
  own button with the next ten and, if any remain, a new button.
- **Stable `id`s** on the slot, each review, the summary and the
  details-card average, so focus survives the swap as it does for
  `#wishlist-button`.
- The product page and the Reviews tab **share the review and form
  partials**. Each action renders the partial that fits the page it was
  posted from. **(PRD-stage)**
- Every state-changing endpoint is POST only. Confirmation and edit-form
  GETs change nothing.
- Invalid form submissions re-render the form in place with its errors.

### Catalog

- **`ProductQuerySet.with_ratings()`**, in `products`, annotates each
  product's **customer average and customer count** through the reverse
  relation by string lookup (an `Avg`/`Count` over `reviews__…` with a
  filter excluding removed and staff reviews). It **never imports
  `reviews`**. This follows `DiscountCodeQuerySet.with_usage()`: computed
  from rows, never a running total.
- This is a deliberate **soft dependency** of `products` on `reviews`'
  field names. It is documented in the queryset's docstring and in
  `docs/REVIEWS.md`, and a test in `reviews` checks that `with_ratings()`
  agrees with the `reviews`-side counted set, so a renamed field fails a
  test instead of silently returning nothing.
- Catalog cards read the annotation, so showing ratings adds **no
  per-card query**.
- Two new querystring parameters on the catalog (and the category pages
  that inherit from it), composing with `q`, `tag` and `category`:
  - **sort by rating**: highest average, then more reviews, then name;
    unreviewed products last
  - **4 stars & up**: average ≥ 4.0; unreviewed products excluded
- Pagination links and the existing filter controls preserve both new
  parameters, and the controls show which are active. **(PRD-stage)**
- The annotation must stay correct when combined with the tag filter's
  join; a test covers a product with several tags and several reviews.

### Back office: the Reviews tab

- A new tab in the back-office rail, `section="reviews"`, visible to all
  staff, gated by `StaffRequiredMixin`.
- Lists **every review, removed and staff ones included, newest first**,
  20 per page like the order list. **(PRD-stage)**
- Each row shows the product (linked to its page), the author's username
  and full name (this is the back office, not the public page), the
  rating, headline and comment, status, the "Edited" and "Edited by
  <staff username>" markers, and who removed it and when.
- **Filters**, as querystring parameters that compose and survive
  pagination: product, rating, author type (customer or staff), status
  (live or removed).
- **Actions in place**: Edit (staff form) and Remove on live reviews;
  Restore (while text remains) and Allow a new review on removed ones.
  A staff member's own reviews offer the author actions instead.

### URLs (PRD-stage)

Everything lives in a `reviews` namespace. Public actions use the product
pk or the review pk; nothing in a URL names a reviewer.

| Purpose | Name |
|---|---|
| Create (POST, product pk) | `reviews:create` |
| Author edit form / save (review pk) | `reviews:edit` |
| Author delete confirm / delete (review pk) | `reviews:delete` |
| Review partial, for Cancel (review pk) | `reviews:detail` |
| List page / sort (GET, product pk) | `reviews:list` |
| Staff edit form / save (review pk) | `reviews:moderate` |
| Staff remove confirm / remove (review pk) | `reviews:remove` |
| Restore (POST, review pk) | `reviews:restore` |
| Allow a new review (POST, review pk) | `reviews:allow_new` |
| Back-office Reviews tab | `reviews:manage` |

### Dashboard

- One new function in `dashboard/queries.py` returning the **number of
  counted reviews** and their **average rating in stars** since the
  dashboard's selected period start, following the module's existing
  `since` convention. Docstring, type hints and tests, as for every
  function in that deep module.
- One new card on the dashboard with both figures. An empty period shows
  zero reviews and a dash for the average. **(PRD-stage)**

### Seed

- The seed **wipes reviews first** and is deterministic and idempotent.
- A hand-written list of product-specific reviews, kept like `CATALOG`,
  each attributed to a background customer who holds a non-cancelled
  order for that product. The list covers every rating including half
  stars, some headlines left blank, and more than ten on at least one
  product.
- `customer` (Casey) has reviewed DreamWeaver; their other purchases are
  left unreviewed.
- One review edited by staff, one removed by staff.
- `employee` (Emory) gains **one delivered order** and **one staff
  review** of a product on it. Seeded orders go from **52 to 53**; the
  seed's docstrings and count comments are updated to match.
- Seeded reviews have varied creation dates so that "Newest" and the
  dashboard period are meaningful. **(PRD-stage)**

## Out of Scope

- An approval queue. Reviews publish immediately.
- A "report this review" button.
- Helpfulness votes ("Was this helpful?").
- Emails of any kind: to the author on removal, to staff on new reviews.
- `SecurityEvent` entries for any review action.
- A removal reason, whether shown to the author or recorded for staff.
- Public display names or reviewer profiles.
- A lowest-rated-products table on the dashboard.
- Photos on reviews.
- Replies to reviews, from staff or customers.
- Showing a removed review's text to its author.
- Registering reviews in the Django admin.

## Further Notes

- **Documents to write with the feature:** `docs/REVIEWS.md` covering the
  model, the eligibility and permission rules, the counted set, the soft
  dependency in `with_ratings()`, the HTMX endpoints and partials, and the
  seed. `CLAUDE.md` gains a "Read before…" line pointing to it and a
  `reviews/` entry in its project layout.
- **HTMX:** the feature follows `docs/TEMPLATES.md`'s partials
  convention (underscore-prefixed partials that never extend
  `base.html`). Its endpoints are listed in `docs/REVIEWS.md`, as the
  wishlist's are in `docs/WISHLIST.md`.
- **The core PRD** gets a dated amendment pointing here, as was done for
  discount codes and account security, rather than a rewrite.
- **Rating storage.** Half stars as integers 2–10 keep averages, sorting
  and the check constraint exact, and avoid floating-point comparisons.
  Halving happens only at display time and in the averages.
- **Testing priorities** (pytest, plain fixtures, per `docs/TESTING.md`):
  1. Eligibility: placed, shipped and delivered count; cancelled doesn't;
     creation only; staff eligible; unavailable products reviewable.
  2. Permissions: author or staff only; other customers 404; staff edit
     can't change the rating.
  3. The removal states: remove, author blank, restore refused after
     blanking, allow a new review, reposting blocked while removed.
  4. The counted set: removed and staff reviews excluded everywhere;
     `by_staff` as a snapshot.
  5. `with_ratings()`: agreement with the `reviews` side, the tag join,
     sort order with ties and unreviewed products, the 4-stars filter.
  6. The dashboard query, including an empty period.
  7. The HTMX responses: right partial, out-of-band summary updates,
     double-submit returning the existing review.
  8. The admin registration guard and the seed's own rules (every seeded
     review's author holds a qualifying order).
- `uv run pytest` and `uv run ruff check .` must be green before any
  phase is finished. Tailwind may be blocked by Windows Smart App Control
  (WinError 4551); that is an OS policy, not a code fault.
