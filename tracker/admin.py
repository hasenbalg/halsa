from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    BloodPressureReading,
    GlucoseReading,
    MetricSettings,
    OverdueNotice,
    Profile,
    Schedule,
    WeightReading,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "units", "two_factor_enabled")
    readonly_fields = ("totp_seed", "totp_confirmed", "last_verified_at")


@admin.register(GlucoseReading)
class GlucoseAdmin(admin.ModelAdmin):
    list_display = ("taken_at", "user", "value_mmol", "note")
    list_filter = ("user",)
    search_fields = ("note",)
    date_hierarchy = "taken_at"


@admin.register(WeightReading)
class WeightAdmin(admin.ModelAdmin):
    list_display = ("taken_at", "user", "value_kg", "note")
    list_filter = ("user",)
    date_hierarchy = "taken_at"


@admin.register(BloodPressureReading)
class BPAdmin(admin.ModelAdmin):
    list_display = ("taken_at", "user", "systolic", "diastolic", "pulse")
    list_filter = ("user",)
    date_hierarchy = "taken_at"


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "metric", "time", "weekdays", "active")
    list_filter = ("user", "metric", "active")


@admin.register(MetricSettings)
class MetricSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "metric", "window_minutes", "grace_minutes", "email_enabled")
    list_filter = ("user", "metric")


@admin.register(OverdueNotice)
class OverdueNoticeAdmin(admin.ModelAdmin):
    list_display = ("schedule", "slot", "notified_at")
