from django.db import migrations, models


def seed_glucose_units(apps, schema_editor):
    """Glucose units used to be tied to the combined weight/glucose
    preference; keep existing users' current display by seeding the new
    field from it."""
    Profile = apps.get_model("tracker", "Profile")
    Profile.objects.filter(units="imperial").update(glucose_units="imperial")


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0006_alter_weightreading_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="glucose_units",
            field=models.CharField(
                choices=[("metric", "mmol/L"), ("imperial", "mg/dL")],
                default="metric",
                max_length=10,
            ),
        ),
        migrations.RunPython(seed_glucose_units, migrations.RunPython.noop),
    ]
