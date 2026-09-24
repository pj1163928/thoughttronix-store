"""Address validators — small, pure, and unit-testable.

``zip_validator`` lives here rather than in ``orders`` because the
address vocabulary belongs to whoever owns ``Address``. Checkout imports
it, which is the direction the apps already run: ``orders`` knows about
``accounts``, never the other way around.
"""

from django.core.validators import RegexValidator

zip_validator = RegexValidator(
    r"^\d{5}(-\d{4})?$", "Enter a ZIP code like 79016 or 79016-1234."
)
