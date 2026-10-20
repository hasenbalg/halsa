from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0002_note_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="glucosereading",
            name="context",
            field=models.CharField(
                blank=True,
                choices=[
                    ("fasting", "Fasting"),
                    ("pre", "Before meal"),
                    ("post", "After meal"),
                    ("random", "Random"),
                ],
                max_length=10,
            ),
        ),
    ]
