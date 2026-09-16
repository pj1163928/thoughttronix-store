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
