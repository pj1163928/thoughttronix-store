# Discount codes

Discount codes live in `orders`: `DiscountCode` owns the rules
(`unusable_reason`, `discount_for`), `Cart.discount_code` holds the
applied one, and an `Order` freezes the code's name and the dollars it
took off. `place_order` re-checks eligibility before charging — the cart
box, the cart's own total, the checkout guard and the till all call
`unusable_reason`, never their own copies.

## Scope and limits

A code covers the whole order or a chosen set of products; `applies_to`
is stored rather than inferred from an empty `products` set, so deleting
a product can only narrow a code, never widen it to the whole store.
`per_user_limit` (default 1) and `total_limit` (default unlimited) cap
redemptions, counted live from the orders — cancelled orders give the
use back, and `counting_since` is how reinstating a code starts its
count over without touching a single order.

## Back office

The back office lists codes by `?show=active|inactive|all`, where active
means live or scheduled. Typing a code that already exists is answered
with the existing code and a way to reinstate it, not a unique-constraint
error — `DiscountCodeForm.validate_unique` records the clash instead of
rejecting it, and only the create view turns that on.
