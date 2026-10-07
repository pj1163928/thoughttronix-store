"""Identity rules: sign-up asks for an email, and neither emails nor
usernames may differ from another account's only by case."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse

User = get_user_model()

BEFORE = ("accounts", "0003_securityevent")
CONSTRAINTS = ("accounts", "0004_case_insensitive_identities")


def sign_up(client, **overrides):
    data = {
        "username": "casey",
        "email": "casey@example.com",
        "password1": "neural-implant-9000",
        "password2": "neural-implant-9000",
        **overrides,
    }
    return client.post(reverse("accounts:signup"), data)


def form_errors(response):
    return response.context["form"].errors


# --- Sign-up ---------------------------------------------------------------


def test_signup_asks_for_an_email(client, db):
    page = client.get(reverse("accounts:signup")).content.decode()

    assert 'name="email"' in page
    assert 'type="email"' in page


def test_signup_without_an_email_is_refused_with_a_field_error(client, db):
    response = sign_up(client, email="")

    assert response.status_code == HTTPStatus.OK
    assert form_errors(response)["email"]
    assert not User.objects.filter(username="casey").exists()


def test_signup_stores_the_email_as_entered(client, db):
    sign_up(client, email="Casey.Monroe@Example.COM")

    assert User.objects.get(username="casey").email == "Casey.Monroe@Example.COM"


def test_signup_refuses_an_email_differing_only_by_case(client, db):
    User.objects.create_user("existing", "casey@example.com", "existing123")

    response = sign_up(client, email="Casey@Example.com")

    assert response.status_code == HTTPStatus.OK
    assert "already exists" in form_errors(response)["email"][0]
    assert not User.objects.filter(username="casey").exists()
    # The account that was there first keeps its email untouched.
    assert User.objects.get(username="existing").email == "casey@example.com"


def test_signup_refuses_a_username_containing_an_at_sign(client, db):
    response = sign_up(client, username="casey@home")

    assert "can't contain @" in form_errors(response)["username"][0]
    assert not User.objects.filter(username="casey@home").exists()


def test_signup_refuses_a_username_differing_only_by_case(client, db):
    User.objects.create_user("Casey", "first@example.com", "existing123")

    response = sign_up(client, username="casey")

    assert form_errors(response)["username"]
    assert User.objects.count() == 1


# --- The constraints ---------------------------------------------------------


def test_accounts_without_an_email_do_not_clash(db):
    User.objects.create_user("older-one", password="x")
    User.objects.create_user("older-two", password="x")

    assert User.objects.filter(email="").count() == 2


def test_blank_email_matches_no_account(db):
    User.objects.create_user("older-one", password="x")

    assert not User.objects.with_email("").exists()


def test_the_database_refuses_a_case_insensitive_duplicate_email(db):
    User.objects.create_user("one", "casey@example.com", "x")

    with pytest.raises(IntegrityError):
        User.objects.create_user("two", "CASEY@example.com", "x")


def test_the_database_refuses_a_case_insensitive_duplicate_username(db):
    User.objects.create_user("Casey", password="x")

    with pytest.raises(IntegrityError):
        User.objects.create_user("casey", password="x")


def test_model_validation_refuses_an_at_sign_in_a_username(db):
    user = User(username="casey@home", password="x")

    with pytest.raises(ValidationError, match="can't contain @"):
        user.full_clean()


# --- The migration's duplicate check ---------------------------------------


@pytest.fixture
def before_constraints(transactional_db):
    """Roll accounts back to before the constraints; restore them after.

    Yields the historical ``User`` model of that state, which can hold
    the duplicates the constraints would now refuse.
    """
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE])
    executor.loader.build_graph()
    old_user = executor.loader.project_state([BEFORE]).apps.get_model(
        "accounts", "User"
    )
    try:
        yield old_user
    finally:
        old_user.objects.all().delete()
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def migrate_forward():
    executor = MigrationExecutor(connection)
    executor.migrate([CONSTRAINTS])


def test_migration_names_the_duplicates_and_changes_nothing(before_constraints):
    OldUser = before_constraints
    OldUser.objects.create(username="Casey", email="casey@example.com")
    OldUser.objects.create(username="casey", email="CASEY@Example.com")
    OldUser.objects.create(username="drew", email="drew@example.com")

    with pytest.raises(RuntimeError) as refused:
        migrate_forward()

    message = str(refused.value)
    assert "'Casey', 'casey'" in message
    assert "'casey@example.com', 'CASEY@Example.com'" in message
    assert "drew" not in message
    # Nothing was merged or renamed.
    assert sorted(OldUser.objects.values_list("username", flat=True)) == [
        "Casey",
        "casey",
        "drew",
    ]


def test_migration_passes_on_clean_data(before_constraints):
    OldUser = before_constraints
    OldUser.objects.create(username="casey", email="casey@example.com")
    OldUser.objects.create(username="older-one", email="")
    OldUser.objects.create(username="older-two", email="")

    migrate_forward()

    assert MigrationExecutor(connection).loader.applied_migrations.keys() >= {
        CONSTRAINTS
    }
