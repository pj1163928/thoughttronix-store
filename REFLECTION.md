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

# Product Images

## One Decision From Grill Me

One of the biggest decisions I overruled based on Claude's questioning was implementing the ability to add multiple pictures. Claude argued that this would make the project and codebase more complicated and that, to simply satisfy the given requirements, a single image should be used.

I did decide to overrule this mainly because it would make the product listing more advanced and diverse. I also gave it criteria to select an image as a primary.

Claude was right about it making things more complicated, as I had much more back-and-forth conversations with the agent about how to better style the images it provided me with and how to improve the gallery.

## Uploading Images

### 1. Referencing the `ImageField`

To upload an image, it first references the `ImageField` on `Product`, located in `products/models.py` lines 106–108:

```python
image = models.ImageField(
    "main image", upload_to=PRODUCT_FOLDER, blank=True, editable=False
)
```

Essentially, it is referencing that an image is associated with that product.

The `upload_to` parameter places the uploaded image inside the `products` folder.

### 2. Upload Form

The upload form is used to upload product images and is located in:

`templates/products/manage_product_images.html`, lines 58–60.

```html
<form method="post" enctype="multipart/form-data"
      action="{% url 'products:manage_product_image_upload' product.pk %}"
      class="mt-2 space-y-4">
```

I also have one for any additional images, but they both accomplish essentially the same purpose: posting an image to the server and allowing the user to view the image.

The `enctype` is essentially used to send the actual file, not just the file name. Without `enctype`, it would only send the file name rather than the full image file.

## Following an Image Request

### 1. Where the Image Is Stored

```text
\thoughttronix-store\media\products\80d48821e30a452799c45e82c8e44604-thumb.webp
```

This is stored in the root `media` folder under the `products` subfolder.

It is also re-uploaded as a `.webp` file, so the original file name is not saved.

It is stored as two images: one for the full image and the other for a thumbnail.

### 2. Value Stored in the Database

```text
products/80d48821e30a452799c45e82c8e44604.webp
```

This is stored in the `products_product` row for `MindReader`, the product that I created. The `image` column holds the path to the image.

### 3. Value the Web Browser Requests to View the Image

```text
/media/products/80d48821e30a452799c45e82c8e44604.webp
```

The browser requests the image on the detail page.

Product cards in the catalog use `card_image` rather than `display_image`.

### Disclaimer
ChatGPT was used to format the MD text readability, wording and choice of thought is entirely humanly generated.
