from decimal import Decimal
from django.db import migrations


GHANA_REGIONS = [
    ("Ahafo", "ahafo"),
    ("Ashanti", "ashanti"),
    ("Bono", "bono"),
    ("Bono East", "bono-east"),
    ("Central", "central"),
    ("Eastern", "eastern"),
    ("Greater Accra", "greater-accra"),
    ("North East", "north-east"),
    ("Northern", "northern"),
    ("Oti", "oti"),
    ("Savannah", "savannah"),
    ("Upper East", "upper-east"),
    ("Upper West", "upper-west"),
    ("Volta", "volta"),
    ("Western", "western"),
    ("Western North", "western-north"),
]


def seed_shipping_regions_and_charge(apps, schema_editor):
    ShippingRegion = apps.get_model("store", "ShippingRegion")
    CheckoutCharge = apps.get_model("store", "CheckoutCharge")

    for position, (name, slug) in enumerate(GHANA_REGIONS, start=1):
        ShippingRegion.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "position": position, "active": True},
        )

    CheckoutCharge.objects.get_or_create(
        name="Paystack charge",
        defaults={"percentage": Decimal("1.98"), "active": True},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0003_checkoutcharge_shippingregion_order_payment_charge_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_shipping_regions_and_charge, migrations.RunPython.noop),
    ]
