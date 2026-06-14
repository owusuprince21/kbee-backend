from django.db import migrations, models
import store.models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0008_order_stock_deducted_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="review",
            name="rating",
            field=models.DecimalField(
                decimal_places=1,
                max_digits=2,
                validators=[store.models.validate_rating],
            ),
        ),
    ]
