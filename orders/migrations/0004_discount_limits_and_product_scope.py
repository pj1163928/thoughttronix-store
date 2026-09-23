"""Usage limits, and a product set in place of a single product.

The order of operations is the point of this file. The new columns are
added first, the old ``product`` foreign key is copied into them while
both still exist, and only then is it dropped — so no code loses the
product it was written for.

``per_user_limit`` arrives with its model default of 1, which means
every code that already exists becomes one-per-customer. That is the
store's rule now, and applying it uniformly keeps the field's declared
default honest about the data underneath it.
"""

from django.db import migrations, models


def copy_product_into_products(apps, schema_editor):
    """A code for one product becomes a SELECTED code covering that one product."""
    DiscountCode = apps.get_model("orders", "DiscountCode")
    for code in DiscountCode.objects.filter(product__isnull=False):
        code.applies_to = "SELECTED"
        code.save(update_fields=["applies_to"])
        code.products.add(code.product)


def copy_products_back(apps, schema_editor):
    """Reverse: a SELECTED code keeps its first product, and loses the rest."""
    DiscountCode = apps.get_model("orders", "DiscountCode")
    for code in DiscountCode.objects.filter(applies_to="SELECTED"):
        first = code.products.order_by("pk").first()
        code.product = first
        code.save(update_fields=["product"])


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0003_order_discount_amount_order_discount_code_and_more"),
        ("products", "0003_product_is_featured"),
    ]

    operations = [
        migrations.AddField(
            model_name="discountcode",
            name="applies_to",
            field=models.CharField(
                choices=[
                    ("ALL", "The whole order"),
                    ("SELECTED", "Only the products I choose"),
                ],
                default="ALL",
                help_text=(
                    "Whether the discount covers everything in the cart or a chosen few."
                ),
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="discountcode",
            name="counting_since",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="discountcode",
            name="per_user_limit",
            field=models.PositiveIntegerField(
                blank=True,
                default=1,
                help_text=(
                    "How many times one customer may use it. Blank means unlimited."
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="discountcode",
            name="products",
            field=models.ManyToManyField(
                blank=True,
                help_text="Only used when the discount covers chosen products.",
                related_name="discount_codes",
                to="products.product",
            ),
        ),
        migrations.AddField(
            model_name="discountcode",
            name="total_limit",
            field=models.PositiveIntegerField(
                blank=True,
                help_text=(
                    "How many times it may be used across all customers. "
                    "Blank means unlimited."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(copy_product_into_products, copy_products_back),
        migrations.RemoveField(
            model_name="discountcode",
            name="product",
        ),
    ]
