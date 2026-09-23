## Featured Products

### Trace the Feature

The `is_featured` works similarly to an already existing feature, `is_available`. Essentially another model was added to products right below `is_available`.

Then similar to `is_available` again, the `forms.py` inside products has a new option which allows the featured status to appear.

Then in `admin.py` it added the `is_featured` to the list which registers the necessary database model.

Now that feature is added we can go to both the catalog and details HTML files and include them there.

As a side note, Claude included another page which to me was fine as it allowed the admin to see whether the featured tag had been applied to a product.

---

### How it was verified

I verified it a few ways.

First I wanted to make sure that the checkbox was working correctly and that it showed up on both pages. I did this before the badge was added and after.

It also likely helped the AI because it had a point of reference.

Then I had the AI generate and run tests, that I also verified worked independently and made sure that no other anomalies were present.

---

### Judgement

I actually had a fairly smooth experience the second time I tried this with Claude.

The first time went good, however I mistakenly had the AI auto-complete everything which did not allow me to verify any of its changes. It essentially made a best-guess that I was not able to safeguard.

To fix this I simply just synced my git repo with the one on GitHub.

I made sure to be very specific with my directions, fortunately the AI was able to judge and determine what to do.

An unexpected result that actually was kind of nice was the addition of the badge on the staff page. This was likely done because I mentioned to have it included on all relevant locations.

As far as my troubleshooting steps, I applied the same methodology as above.


# Discount Codes

## One Decision From Grill Me

I deviated a total of 4 times throughout Claude's questioning; many of my changes likely could have been argued, but I felt that given what existed, it would make sense to go with these decisions over Claude's.

Claude argued against my "kind + value" decision. I stated that it would make more sense if a percentage was applied to a given set of items or all of the items. Claude wanted to take an easier approach, which, in my opinion, would make it less flexible and potentially allow an exploit in how a person was to use a discount code.

**My Decision:** Make a discount code apply to specific items and those items only, not the entire cart.

**Claude's Decision:** Make a discount apply to all items that matched the item of the discount code. (Claude actually reversed this decision because it could essentially turn a $20 order of Seraphine into a $200 Seraphine order if they were to order 10 Seraphine.)

---

## Changes I Suggested

I sort of went all out with changes, as I wanted to see what Claude was fully capable of, especially considering it wrote over 1,500 lines of new code.

I suggested a variety of additions, such as usage limitations (making it so a user can use a code a certain amount of times or infinitely); before this, there was no usage limitation, meaning a user could use it as many times as they wanted.

I also made it able to sort between active and inactive codes. Before, codes were all over the place; I figured there was no point in displaying inactive codes right away.

I wanted discount codes to be highly customizable and suggested making it possible to select multiple items and apply the discount to those items if they were in a user's cart; before this, it was a single item or all items.

Lastly, I wanted to limit the number of codes that were being made and prevent codes from being duplicated. If a duplicated code is created, it would flag it and allow the user to reinstate the code.

Along with that, admins can choose to simply reinstate any discount code of their choosing and see how many times that code is used.

Before this, any code could be created, which would be somewhat disorganized and harder to keep track of items that may be doing better because of sales and discounts.

Claude made a few mistakes that were automatically caught in its testing; most of these were arithmetic errors or overwriting previous tests.

Claude was able to use the changes to alter the code and the tests to work properly, making all tests succeed.
