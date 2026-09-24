"""Saved addresses at checkout: the pre-fill, the picker, and the write-back.

The property worth defending here is that none of this changes what
reaches the till. A saved address feeds the *form*; ``place_order`` sees
the same POST whether the customer typed it or picked it.
"""

from django.urls import reverse

from accounts.models import Address

from .models import Order
from .test_checkout_form import VALID_DATA


def post_checkout(client, **overrides):
    return client.post(reverse("orders:checkout"), {**VALID_DATA, **overrides})


# --- Pre-filling -------------------------------------------------------------


def test_checkout_prefills_both_sections_from_the_defaults(
    client, customer, cart_item, address
):
    client.force_login(customer)

    initial = client.get(reverse("orders:checkout")).context["form"].initial

    assert initial["shipping_street"] == "214 Synapse Street"
    assert initial["billing_street"] == "214 Synapse Street"
    assert initial["shipping_zip"] == "79015"


def test_an_empty_address_book_pre_ticks_the_save_boxes(client, customer, cart_item):
    client.force_login(customer)

    initial = client.get(reverse("orders:checkout")).context["form"].initial

    assert initial["save_shipping_address"]
    assert initial["save_billing_address"]
    assert "shipping_street" not in initial


def test_a_populated_address_book_leaves_the_save_boxes_clear(
    client, customer, cart_item, address
):
    client.force_login(customer)

    initial = client.get(reverse("orders:checkout")).context["form"].initial

    assert not initial.get("save_shipping_address")
    assert not initial.get("save_billing_address")


def test_the_picker_is_absent_until_there_is_something_to_pick(
    client, customer, cart_item
):
    client.force_login(customer)

    response = client.get(reverse("orders:checkout"))

    assert b"Use a saved address" not in response.content


def test_the_picker_lists_saved_addresses(
    client, customer, cart_item, address, second_address
):
    client.force_login(customer)

    response = client.get(reverse("orders:checkout"))

    assert b"Use a saved address" in response.content
    assert b"Home" in response.content
    assert b"Work" in response.content


# --- The HTMX picker endpoint ------------------------------------------------


def test_choosing_an_address_re_renders_that_fieldset(client, customer, second_address):
    client.force_login(customer)

    response = client.get(
        reverse("orders:checkout_address", args=["shipping"]),
        {"address": second_address.pk},
    )

    assert response.status_code == 200
    assert b"77 Cortex Lane" in response.content
    assert b"shipping_street" in response.content
    # The swap is scoped to one section; billing is never touched.
    assert b"billing_street" not in response.content


def test_the_empty_choice_clears_the_fieldset(client, customer, address):
    client.force_login(customer)

    response = client.get(
        reverse("orders:checkout_address", args=["billing"]), {"address": ""}
    )

    assert response.status_code == 200
    assert b"214 Synapse Street" not in response.content
    assert b"billing_street" in response.content


def test_you_cannot_pull_someone_elses_address_into_your_checkout(
    client, customer, staff_user
):
    theirs = Address.objects.create(
        user=staff_user,
        name="Someone Else",
        street="1 Private Road",
        city="Denver",
        state="CO",
        zip="80202",
    )
    client.force_login(customer)

    response = client.get(
        reverse("orders:checkout_address", args=["shipping"]), {"address": theirs.pk}
    )

    assert response.status_code == 404


def test_an_unknown_section_is_a_404(client, customer, address):
    client.force_login(customer)

    response = client.get(
        reverse("orders:checkout_address", args=["postal"]), {"address": address.pk}
    )

    assert response.status_code == 404


def test_the_picker_requires_signing_in(client, address):
    response = client.get(
        reverse("orders:checkout_address", args=["shipping"]), {"address": address.pk}
    )

    assert response.status_code == 302


# --- The write-back ----------------------------------------------------------


def test_ticking_the_box_saves_the_address(client, customer, cart_item):
    client.force_login(customer)

    post_checkout(client, save_shipping_address="on")

    saved = Address.objects.get(user=customer)
    assert saved.street == "12 Cortex Lane"
    # First address in the book, so it takes both roles.
    assert saved.is_default_shipping
    assert saved.is_default_billing


def test_leaving_the_box_clear_saves_nothing(client, customer, cart_item):
    client.force_login(customer)

    post_checkout(client)

    assert not Address.objects.filter(user=customer).exists()
    assert Order.objects.filter(user=customer).exists()


def test_both_boxes_on_one_address_save_a_single_row(client, customer, cart_item):
    client.force_login(customer)

    post_checkout(
        client,
        billing_street="12 Cortex Lane",
        billing_line2="Unit 7",
        billing_zip="79015",
        save_shipping_address="on",
        save_billing_address="on",
    )

    assert Address.objects.filter(user=customer).count() == 1


def test_saving_an_address_you_already_have_adds_nothing(
    client, customer, cart_item, address
):
    client.force_login(customer)

    post_checkout(
        client,
        shipping_street="214 SYNAPSE STREET",
        shipping_line2="",
        shipping_city="Canyon",
        shipping_zip="79015",
        save_shipping_address="on",
    )

    assert Address.objects.filter(user=customer).count() == 1


def test_a_re_saved_address_keeps_its_label(client, customer, cart_item, address):
    client.force_login(customer)

    post_checkout(
        client,
        shipping_street="214 Synapse Street",
        shipping_line2="",
        shipping_city="Canyon",
        shipping_zip="79015",
        save_shipping_address="on",
    )

    address.refresh_from_db()
    assert address.label == "Home"


def test_a_second_saved_address_does_not_steal_the_defaults(
    client, customer, cart_item, address
):
    client.force_login(customer)

    post_checkout(client, save_shipping_address="on")

    address.refresh_from_db()
    assert Address.objects.filter(user=customer).count() == 2
    assert address.is_default_shipping
    assert address.is_default_billing


def test_the_order_is_unaffected_by_the_address_book(
    client, customer, cart_item, address
):
    """The picker feeds the form; the order is still built from the POST."""
    client.force_login(customer)

    post_checkout(client, save_shipping_address="on")

    order = Order.objects.get(user=customer)
    assert order.shipping_street == "12 Cortex Lane"
    assert order.shipping_line2 == "Unit 7"
