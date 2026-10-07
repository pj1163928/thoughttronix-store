"""Account and address validators — small, pure, and unit-testable.

``zip_validator`` lives here rather than in ``orders`` because the
address vocabulary belongs to whoever owns ``Address``. Checkout imports
it, which is the direction the apps already run: ``orders`` knows about
``accounts``, never the other way around.
"""

from django.core.validators import RegexValidator

zip_validator = RegexValidator(
    r"^\d{5}(-\d{4})?$", "Enter a ZIP code like 79016 or 79016-1234."
)

# Sign-in takes a username *or* an email in one box, and the only thing
# telling them apart is the ``@``. Django's own username validator allows
# it, so this one runs alongside it on the model field — which is what
# carries the rule to sign-up, renames and the admin alike.
username_no_at_validator = RegexValidator(
    r"@",
    "Usernames can't contain @. That's how sign-in tells them from email addresses.",
    inverse_match=True,
)
