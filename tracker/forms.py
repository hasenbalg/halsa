from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from . import units as U
from .models import (
    BloodPressureReading,
    GlucoseContext,
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
        label=_("When"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"],
    )
    glucose = forms.DecimalField(label=_("Glucose"), required=False, min_value=0, max_value=2000)
    glucose_context = forms.ChoiceField(
        label=_("Context"), required=False,
        choices=[("", "—")] + list(GlucoseContext.choices),
    )
    weight = forms.DecimalField(label=_("Weight"), required=False, min_value=0, max_value=2000)
    systolic = forms.IntegerField(label=_("Systolic"), required=False, min_value=60, max_value=260)
    diastolic = forms.IntegerField(label=_("Diastolic"), required=False, min_value=30, max_value=160)
    pulse = forms.IntegerField(label=_("Pulse"), required=False, min_value=20, max_value=250)

    def __init__(self, *args, units=Profile.Units.METRIC, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = units
        imp = U.is_imperial(units)
        self.fields["glucose"].label = _("Glucose ({unit})").format(unit=U.glucose_unit_label(units))
        self.fields["glucose"].min_value = 9 if imp else 0.5
        self.fields["glucose"].max_value = 720 if imp else 40
        self.fields["weight"].label = _("Weight ({unit})").format(unit=U.weight_unit_label(units))
        self.fields["weight"].min_value = 4 if imp else 2
        self.fields["weight"].max_value = 1100 if imp else 500
        self.fields["systolic"].label = _("Systolic (mmHg)")
        self.fields["diastolic"].label = _("Diastolic (mmHg)")

    def clean(self):
        data = super().clean()
        errors = []
        sys_v, dia_v = data.get("systolic"), data.get("diastolic")
        if (sys_v is None) != (dia_v is None):
            errors.append(_("Blood pressure needs both systolic and diastolic."))
        if sys_v and dia_v and dia_v >= sys_v:
            errors.append(_("Diastolic must be lower than systolic."))
        if all(data.get(k) is None for k in ("glucose", "weight", "systolic")):
            errors.append(_("Enter at least one value."))
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
                    context=cd.get("glucose_context") or "",
                )
            )
        if cd.get("weight") is not None:
            created.append(
                WeightReading.objects.create(
                    user=user,
                    taken_at=cd["taken_at"],
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
    value = forms.DecimalField(label=_("Glucose"), min_value=0, max_value=2000)

    class Meta:
        model = GlucoseReading
        fields = ["taken_at", "context", "note"]
        widgets = {"taken_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, units=Profile.Units.METRIC, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = units
        imp = U.is_imperial(units)
        self.fields["value"].label = _("Glucose ({unit})").format(unit=U.glucose_unit_label(units))
        self.fields["value"].min_value = 9 if imp else 0.5
        self.fields["value"].max_value = 720 if imp else 40
        self.fields["taken_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        if self.instance.pk:
            d, _lbl = U.glucose_display(self.instance.value_mmol, units)
            self.initial["value"] = d

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.value_mmol = U.glucose_from_display(self.cleaned_data["value"], self.units)
        if commit:
            obj.save()
        return obj


class WeightForm(forms.ModelForm):
    value = forms.DecimalField(label=_("Weight"), min_value=0, max_value=2000)

    class Meta:
        model = WeightReading
        fields = ["taken_at", "note"]
        widgets = {"taken_at": forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, units=Profile.Units.METRIC, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = units
        imp = U.is_imperial(units)
        self.fields["value"].label = _("Weight ({unit})").format(unit=U.weight_unit_label(units))
        self.fields["taken_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        self.fields["value"].min_value = 4 if imp else 2
        self.fields["value"].max_value = 1100 if imp else 500
        if self.instance.pk:
            d, _lbl = U.weight_display(self.instance.value_kg, units)
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
            self.add_error("diastolic", _("Diastolic must be lower than systolic."))
        return data


class UnitsForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["units"]
        widgets = {"units": forms.RadioSelect}


class LanguageForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["language"]


WEEKDAYS = [(0, _("Mon")), (1, _("Tue")), (2, _("Wed")),
            (3, _("Thu")), (4, _("Fri")), (5, _("Sat")),
            (6, _("Sun"))]


class ScheduleForm(forms.ModelForm):
    weekdays = forms.MultipleChoiceField(
        choices=WEEKDAYS, widget=forms.CheckboxSelectMultiple, label=_("Repeat on")
    )

    def clean_weekdays(self):
        return sorted(int(w) for w in self.cleaned_data["weekdays"])

    class Meta:
        model = Schedule
        fields = ["name", "metric", "time", "weekdays", "active"]
        labels = {
            "name": _("Name"),
            "metric": _("Metric"),
            "time": _("Time"),
            "active": _("Active"),
        }
        widgets = {"time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["time"].input_formats = ["%H:%M", "%H:%M:%S"]


class MetricSettingsForm(forms.ModelForm):
    class Meta:
        model = MetricSettings
        fields = ["window_minutes", "grace_minutes", "email_enabled"]
        labels = {
            "window_minutes": _("A reading counts as done if within this many minutes of the slot"),
            "grace_minutes": _("Email me this many minutes after a missed slot"),
            "email_enabled": _("Send overdue reminder emails for this metric"),
        }


class RestoreForm(forms.Form):
    backup = forms.FileField(label=_("Backup file (Hälsa JSON)"))
