"""Restore data from a Hälsa JSON backup (the format produced by export_json).

Import is idempotent: rows are matched by their UUID id, so re-importing the
same backup updates existing rows and inserts only genuinely new ones.
Schedules and metric settings are matched by id as well.
"""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import (
    BloodPressureReading,
    GlucoseReading,
    MetricSettings,
    Profile,
    Schedule,
    WeightReading,
)


class RestoreError(Exception):
    pass


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise RestoreError(f"bad datetime: {value!r}")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise RestoreError(f"bad date: {value!r}")


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise RestoreError(f"bad number: {value!r}")


def _parse_time(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (ValueError, TypeError):
        raise RestoreError(f"bad time: {value!r}")


def restore_from_json(user, raw_text):
    """Validate and upsert a backup. Returns a summary dict."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RestoreError(f"not valid JSON: {e}")
    if not isinstance(data, dict):
        raise RestoreError("backup must be a JSON object")
    if data.get("app") != "halsa":
        raise RestoreError("not a Hälsa backup file")
    version = data.get("export_version")
    if version not in (1, None):
        raise RestoreError(f"unsupported export_version {version}")

    summary = {
        "glucose": [0, 0], "weight": [0, 0], "bp": [0, 0],
        "schedules": [0, 0], "metric_settings": [0, 0], "profile": [0, 0],
    }

    def upsert(model, bucket, obj_kwargs, id_field="id"):
        pk = obj_kwargs.get(id_field)
        existing = model.objects.filter(pk=pk, user=user).first() if pk else None
        if existing:
            for k, v in obj_kwargs.items():
                if k != id_field:
                    setattr(existing, k, v)
            existing.save()
            bucket[1] += 1
        else:
            model.objects.create(user=user, **obj_kwargs)
            bucket[0] += 1

    with transaction.atomic():
        for r in data.get("glucose_readings", []):
            upsert(GlucoseReading, summary["glucose"], {
                "id": r.get("id"),
                "taken_at": _parse_dt(r.get("taken_at")),
                "value_mmol": _dec(r.get("value_mmol")),
                "context": r.get("context", "") or "",
                "note": r.get("note", "") or "",
            })
        for r in data.get("weight_readings", []):
            upsert(WeightReading, summary["weight"], {
                "id": r.get("id"),
                "date": _parse_date(r.get("date")),
                "value_kg": _dec(r.get("value_kg")),
                "note": r.get("note", "") or "",
            })
        for r in data.get("blood_pressure_readings", []):
            upsert(BloodPressureReading, summary["bp"], {
                "id": r.get("id"),
                "taken_at": _parse_dt(r.get("taken_at")),
                "systolic": int(r.get("systolic")),
                "diastolic": int(r.get("diastolic")),
                "pulse": int(r["pulse"]) if r.get("pulse") is not None else None,
                "note": r.get("note", "") or "",
            })
        for s in data.get("schedules", []):
            upsert(Schedule, summary["schedules"], {
                "id": s.get("id"),
                "name": s.get("name", "")[:80],
                "metric": s.get("metric"),
                "time": _parse_time(s.get("time")),
                "weekdays": s.get("weekdays") or [],
                "active": bool(s.get("active", True)),
            })
        for ms in data.get("metric_settings", []):
            obj, created = MetricSettings.objects.get_or_create(
                user=user, metric=ms.get("metric"),
                defaults={
                    "window_minutes": int(ms.get("window_minutes", 120)),
                    "grace_minutes": int(ms.get("grace_minutes", 60)),
                    "email_enabled": bool(ms.get("email_enabled", True)),
                },
            )
            if not created:
                obj.window_minutes = int(ms.get("window_minutes", 120))
                obj.grace_minutes = int(ms.get("grace_minutes", 60))
                obj.email_enabled = bool(ms.get("email_enabled", True))
                obj.save()
            summary["metric_settings"][0 if created else 1] += 1

        prof = data.get("profile") or {}
        if prof.get("units") in ("metric", "imperial"):
            profile, _ = Profile.objects.get_or_create(user=user)
            if profile.units != prof["units"]:
                profile.units = prof["units"]
                profile.save(update_fields=["units"])
                summary["profile"][0] += 1
            else:
                summary["profile"][1] += 1

    return {
        "created": {k: v[0] for k, v in summary.items()},
        "updated": {k: v[1] for k, v in summary.items()},
    }
