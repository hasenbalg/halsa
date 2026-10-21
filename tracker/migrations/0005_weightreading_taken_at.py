import datetime

from django.db import migrations, models
from django.utils import timezone


def copy_date_to_taken_at(apps, schema_editor):
    WeightReading = apps.get_model("tracker", "WeightReading")
    for r in WeightReading.objects.filter(taken_at__isnull=True):
        naive = datetime.datetime.combine(r.date, datetime.time(0, 0))
        r.taken_at = timezone.make_aware(naive, timezone.get_current_timezone())
        r.save(update_fields=["taken_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0004_profile_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="weightreading",
            name="taken_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(copy_date_to_taken_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="weightreading",
            name="taken_at",
            field=models.DateTimeField(default=timezone.now),
        ),
        migrations.RemoveField(
            model_name="weightreading",
            name="date",
        )    ]
