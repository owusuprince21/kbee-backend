from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0007_alter_order_receipt_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="stock_deducted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
