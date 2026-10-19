from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="glucosereading",
            name="note",
            field=models.TextField(blank=True, max_length=2000),
        ),
        migrations.AlterField(
            model_name="weightreading",
            name="note",
            field=models.TextField(blank=True, max_length=2000),
        ),
        migrations.AlterField(
            model_name="bloodpressurereading",
            name="note",
            field=models.TextField(blank=True, max_length=2000),
        ),
    ]
