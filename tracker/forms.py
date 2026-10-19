from decimal import Decimal

from django import forms

from . import units as U
from .models import (
    BloodPressureReading,
    GlucoseReading,
    MetricSettings,
    Profile,
    Schedule,
    WeightReading,
)


def _units_cleaned(form):
    return getattr(form, "units", Profile.Units.METRIC)


class QuickAddForm(forms.Form):
    """One page, all three metrics. Every field optional, but not all empty."""

    taken_at = forms.DateTimeField(
        label="When",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"],
    )
    glucose = forms.DecimalField(label="Glucose", required=False, min_value=0, max_value=2000)
    weight = forms.DecimalField(label="Weight", required=False, min_value=0, max_value=2000)
    systolic = forms.IntegerField(label="Systolic", required=False, min_value=60, max_value=260)
    diastolic = forms.IntegerField(label="Diastolic", required=False, min_value=30, max_value=160)
    pulse = forms.IntegerField(label="Pulse", required=False, min_value=20, max_value=250)

    def __init__(self, *args, units=Profile.Units.METRIC, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = units
        imp = U.is_imperial(units)
        self.fields["glucose"].label = f"Glucose ({U.glucose_unit_label(units)})"
        self.fields["glucose"].min_value = 9 if imp else 0.5
        self.fields["glucose"].max_value = 720 if imp else 40
        self.fields["weight"].label = f"Weight ({U.weight_unit_label(units)})"
        self.fields["weight"].min_value = 4 if imp else 2
        self.fields["weight"].max_value = 1100 if imp else 500
        self.fields["systolic"].label = "Systolic (mmHg)"
        self.fields["diastolic"].label = "Diastolic (mmHg)"

    def clean(self):
        data = super().clean()
        errors = []
        sys_v, dia_v = data.get("systolic"), data.get("diastolic")
        if (sys_v is None) != (dia_v is None):
            errors.append("Blood pressure needs both systolic and diastolic.")
        if sys_v and dia_v and dia_v >= sys_v:
            errors.append("Diastolic must be lower than systolic.")
        if all(data.get(k) is None for k in ("glucose", "weight", "systolic")):
            errors.append("Enter at least one value.")
        for e in errors:
            self.add_error(None, e)
        return data

    def save(self, user):
        cd = self.cleaned_data
        created = []
        if cd.get("glucose") is not None:
            created.append(
                GlucoseReading.objects.create(
                    user=user,
                    taken_at=cd["taken_at"],
                    value_mmol=U.glucose_from_display(cd["glucose"], self.units),
                )
            )
        if cd.get("weight") is not None:
            created.append(
                WeightReading.objects.create(
                    user=user,
                    date=cd["taken_at"].date(),
                    value_kg=U.weight_from_display(cd["weight"], self.units),
                )
            )
        if cd.get("systolic") is not None:
            created.append(
                BloodPressureReading.objects.create(
                    user=user,
                    taken_at=cd["taken_at"],
                    systolic=cd["systolic"],
                    diastolic=cd["diastolic"],
                    pulse=cd.get("pulse"),
                )
            )
        return created


class GlucoseForm(forms.ModelForm):
    value = forms.DecimalField(label="Glucose", min_value=0, max_value=2000)

    class Meta:
        model = GlucoseReading
        fields = ["taken_at", "note"]
        widgets = {"taken_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, units=Profile.Units.METRIC, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = units
        imp = U.is_imperial(units)
        self.fields["value"].label = f"Glucose ({U.glucose_unit_label(units)})"
        self.fields["value"].min_value = 9 if imp else 0.5
        self.fields["value"].max_value = 720 if imp else 40
        self.fields["taken_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        if self.instance.pk:
            d, _ = U.glucose_display(self.instance.value_mmol, units)
            self.initial["value"] = d

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.value_mmol = U.glucose_from_display(self.cleaned_data["value"], self.units)
        if commit:
            obj.save()
        return obj


class WeightForm(forms.ModelForm):
    value = forms.DecimalField(label="Weight", min_value=0, max_value=2000)

    class Meta:
        model = WeightReading
        fields = ["date", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, units=Profile.Units.METRIC, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = units
        imp = U.is_imperial(units)
        self.fields["value"].label = f"Weight ({U.weight_unit_label(units)})"
        self.fields["value"].min_value = 4 if imp else 2
        self.fields["value"].max_value = 1100 if imp else 500
        self.fields["date"].input_formats = ["%Y-%m-%d"]
        if self.instance.pk:
            d, _ = U.weight_display(self.instance.value_kg, units)
            self.initial["value"] = d

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.value_kg = U.weight_from_display(self.cleaned_data["value"], self.units)
        if commit:
            obj.save()
        return obj


class BloodPressureForm(forms.ModelForm):
    class Meta:
        model = BloodPressureReading
        fields = ["taken_at", "systolic", "diastolic", "pulse", "note"]
        widgets = {"taken_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["taken_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]

    def clean(self):
        data = super().clean()
        sys_v, dia_v = data.get("systolic"), data.get("diastolic")
        if sys_v and dia_v and dia_v >= sys_v:
            self.add_error("diastolic", "Diastolic must be lower than systolic.")
        return data


class UnitsForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["units"]
        widgets = {"units": forms.RadioSelect}


WEEKDAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"),
            (5, "Sat"), (6, "Sun")]


class ScheduleForm(forms.ModelForm):
    weekdays = forms.MultipleChoiceField(
        choices=WEEKDAYS, widget=forms.CheckboxSelectMultiple, label="Repeat on"
    )

    def clean_weekdays(self):
        return sorted(int(w) for w in self.cleaned_data["weekdays"])

    class Meta:
        model = Schedule
        fields = ["name", "metric", "time", "weekdays", "active"]
        widgets = {"time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["time"].input_formats = ["%H:%M", "%H:%M:%S"]


class MetricSettingsForm(forms.ModelForm):
    class Meta:
        model = MetricSettings
        fields = ["window_minutes", "grace_minutes", "email_enabled"]
        labels = {
            "window_minutes": "A reading counts as done if within this many minutes of the slot",
            "grace_minutes": "Email me this many minutes after a missed slot",
            "email_enabled": "Send overdue reminder emails for this metric",
        }


class RestoreForm(forms.Form):
    backup = forms.FileField(label="Backup file (Hälsa JSON)")
