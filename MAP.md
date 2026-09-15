# Current Mappings

## What is each app and what does it own?

### Accounts

Contains all account actions including:

* Account sign up
* Sign out
* Sign in

Acts as a layer of validation in determining which forms a user may have access to.

### Dashboard

Contains a general overview of current financial/ordering statistics.

The view can be seen from:

* The last 30 days
* The last 90 days
* All time in which data exists

Also uses calculations to determine current date and time.

### Orders

Contains all orders from users on the admin side as well as their processing status.

The customer side will display all orders they have made and their related details of the order.

### Products

Contains all information pertaining to the products on the storefront, as well as the ability to manage the current products such as their price, name, and other related information.

Will also give admins access to inventory statistics of any given product.

---

## The path of a request

**URL:**

```text
http://127.0.0.1:8000/backoffice/products/
```

**Request:**

```text
[14/Sep/2026 22:35:07] "GET /backoffice/products/ HTTP/1.1" 200 32770
[14/Sep/2026 22:35:07] "GET /static/js/htmx.min.js HTTP/1.1" 304 0
```

---

## Model Explanation (Cart)

The Cart Model uses the User field, where each user gets at most 1 cart.

One aspect of the Cart Model is the `get_or_create`, this either:

* Creates a cart for the user and appends a row, or
* Reuses an already pre-existing row to get the users cart information.

---

## Deleting a Category Explanation

In `models.py` there is a category variable.

Line 70 dictates whether removal of a category is possible, and will essentially stop the category from being deleted if there is a products that still exists in the category.

---

## Test Structure

Currently there are quite a few tests within our app.

There are tests for:

* Every category and app
* The entire project as a whole
* Individualized tests within some apps to make sure each is working properly with eachother

### `conftest.py`

`Conftest.py` allows for the configuration of pytest.

Pytest uses specific fixtures and pull certain tests that it may need.

---

## Still Unclear

Besides the Tailwind CSS and some of the advanced features, it all seems to make sense broadly.

What is a little difficult for me is how all of these views are combined together into a page that looks usable rather than just one that has all of the functionality but not the actually positioning and constraints.
