"""The address book: defaults, the invariants, and the CRUD views.

The two invariants under test are the ones the design leans on
everywhere else: a customer with any addresses has exactly one default
per role, and ``make_default`` is the only thing that moves one.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import Address


@pytest.fixture
def other_customer(db):
    """A second account, for the tests that prove addresses are private."""
    return get_user_model().objects.create_user(
        username="someone-else", password="someone123"
    )


def make_address(user, **overrides):
    return Address.objects.create(
        user=user,
        **{
            "name": "Casey Monroe",
            "street": "9 Axon Avenue",
            "city": "Norman",
            "state": "OK",
            "zip": "73019",
            **overrides,
        },
    )


# --- The model ---------------------------------------------------------------


def test_display_name_prefers_the_label(address):
    assert address.display_name == "Home"


def test_display_name_falls_back_to_the_street(customer):
    unlabelled = make_address(customer)
    assert unlabelled.display_name == "9 Axon Avenue, Norman, OK 73019"


def test_summary_includes_line2_when_there_is_one(second_address):
    assert second_address.summary == "77 Cortex Lane, Suite 300, Amarillo, TX 79101"


def test_making_a_new_default_steps_the_previous_one_aside(address, second_address):
    second_address.make_default(shipping=True)

    address.refresh_from_db()
    assert not address.is_default_shipping
    assert second_address.is_default_shipping
    # Billing did not move: the two roles are independent.
    assert address.is_default_billing


def test_a_role_is_held_by_exactly_one_address(address, second_address):
    second_address.make_default(shipping=True, billing=True)

    assert Address.objects.filter(is_default_shipping=True).count() == 1
    assert Address.objects.filter(is_default_billing=True).count() == 1


def test_defaults_are_per_customer(address, other_customer):
    theirs = make_address(other_customer)
    theirs.make_default(shipping=True)

    address.refresh_from_db()
    # Two customers holding the role at once is the point of the
    # constraint being scoped to the user.
    assert address.is_default_shipping
    assert theirs.is_default_shipping


# --- Deletion ----------------------------------------------------------------


def test_deleting_a_default_promotes_the_newest_survivor(address, second_address):
    address.delete()

    second_address.refresh_from_db()
    assert second_address.is_default_shipping
    assert second_address.is_default_billing


def test_deleting_the_last_address_leaves_nothing_to_promote(address):
    address.delete()

    assert not Address.objects.exists()


def test_deleting_a_non_default_moves_nothing(address, second_address):
    second_address.delete()

    address.refresh_from_db()
    assert address.is_default_shipping
    assert address.is_default_billing


def test_deleting_through_the_view_promotes_too(
    client, customer, address, second_address
):
    """``DeleteView`` must route through the model, not around it."""
    client.force_login(customer)

    client.post(reverse("accounts:address_delete", args=[address.pk]))

    second_address.refresh_from_db()
    assert not Address.objects.filter(pk=address.pk).exists()
    assert second_address.is_default_shipping
    assert second_address.is_default_billing


def test_the_delete_page_warns_that_a_default_will_move(
    client, customer, address, second_address
):
    client.force_login(customer)

    response = client.get(reverse("accounts:address_delete", args=[address.pk]))

    assert response.status_code == 200
    assert b"will become your default" in response.content


def test_you_cannot_delete_someone_elses_address(client, customer, other_customer):
    theirs = make_address(other_customer)
    client.force_login(customer)

    response = client.post(reverse("accounts:address_delete", args=[theirs.pk]))

    assert response.status_code == 404
    assert Address.objects.filter(pk=theirs.pk).exists()


# --- The form ----------------------------------------------------------------


def test_the_first_address_becomes_the_default_for_both_roles(client, customer):
    client.force_login(customer)
    client.post(
        reverse("accounts:address_create"),
        {
            "label": "Home",
            "name": "Casey Monroe",
            "street": "214 Synapse Street",
            "line2": "",
            "city": "Canyon",
            "state": "TX",
            "zip": "79015",
        },
    )

    saved = Address.objects.get()
    assert saved.is_default_shipping
    assert saved.is_default_billing


def test_the_default_checkbox_is_disabled_on_the_address_that_holds_it(
    client, customer, address
):
    client.force_login(customer)
    response = client.get(reverse("accounts:address_update", args=[address.pk]))

    form = response.context["form"]
    assert form.fields["is_default_shipping"].disabled
    assert form.fields["is_default_billing"].disabled


def test_a_disabled_checkbox_keeps_its_role_through_a_save(client, customer, address):
    client.force_login(customer)
    # The unticked POST is what a customer trying to clear the default
    # would send; the disabled field ignores it in favour of its initial.
    client.post(
        reverse("accounts:address_update", args=[address.pk]),
        {
            "label": "Home",
            "name": "Casey Monroe",
            "street": "214 Synapse Street",
            "line2": "",
            "city": "Canyon",
            "state": "TX",
            "zip": "79015",
        },
    )

    address.refresh_from_db()
    assert address.is_default_shipping
    assert address.is_default_billing


def test_ticking_a_default_on_another_address_moves_it(
    client, customer, address, second_address
):
    client.force_login(customer)
    client.post(
        reverse("accounts:address_update", args=[second_address.pk]),
        {
            "label": "Work",
            "name": "Casey Monroe",
            "street": "77 Cortex Lane",
            "line2": "Suite 300",
            "city": "Amarillo",
            "state": "TX",
            "zip": "79101",
            "is_default_shipping": "on",
        },
    )

    address.refresh_from_db()
    second_address.refresh_from_db()
    assert second_address.is_default_shipping
    assert not address.is_default_shipping
    assert address.is_default_billing


def test_a_bad_zip_is_rejected(client, customer):
    client.force_login(customer)
    response = client.post(
        reverse("accounts:address_create"),
        {
            "label": "",
            "name": "Casey Monroe",
            "street": "214 Synapse Street",
            "line2": "",
            "city": "Canyon",
            "state": "TX",
            "zip": "7901",
        },
    )

    assert not Address.objects.exists()
    assert "zip" in response.context["form"].errors


# --- The views ---------------------------------------------------------------


def test_the_list_shows_only_your_own_addresses(
    client, customer, address, other_customer
):
    make_address(other_customer, label="Not yours")
    client.force_login(customer)

    response = client.get(reverse("accounts:addresses"))

    assert list(response.context["addresses"]) == [address]


def test_you_cannot_edit_someone_elses_address(client, customer, other_customer):
    theirs = make_address(other_customer)
    client.force_login(customer)

    response = client.get(reverse("accounts:address_update", args=[theirs.pk]))

    assert response.status_code == 404


def test_the_address_book_requires_signing_in(client):
    response = client.get(reverse("accounts:addresses"))

    assert response.status_code == 302


def test_the_empty_state_invites_a_first_address(client, customer):
    client.force_login(customer)

    response = client.get(reverse("accounts:addresses"))

    assert b"No saved addresses yet" in response.content


@pytest.mark.parametrize(
    "name",
    ["accounts:addresses", "accounts:address_create"],
)
def test_the_address_pages_render(client, customer, address, name):
    client.force_login(customer)

    assert client.get(reverse(name)).status_code == 200
