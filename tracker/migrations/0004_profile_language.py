from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0003_glucosereading_context"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="language",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Auto (browser)"),
                    ("en", "English"),
                    ("de", "Deutsch"),
                ],
                default="",
                max_length=10,
            ),
        ),
    ]
