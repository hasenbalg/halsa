"""Seed a synthetic demo account ("John") for README screenshots.

Idempotent: re-running refreshes John's data instead of duplicating.
Standalone: docker compose exec web python scripts/demo_seed.py
"""
import random
from datetime import timedelta

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "halsa.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone

from tracker.models import (
    BloodPressureReading,
    GlucoseReading,
    Schedule,
    WeightReading,
)

random.seed(42)
U = get_user_model()

user, created = U.objects.get_or_create(
    username="John",
    defaults={"email": "john@example.invalid"},
)
user.set_password("demo-password-9182!")
user.is_staff = False
user.save()
if not created:
    for m in (GlucoseReading, WeightReading, BloodPressureReading):
        m.objects.filter(user=user).delete()
    Schedule.objects.filter(user=user).delete()

now = timezone.localtime()
start = (now - timedelta(days=89)).replace(hour=0, minute=0, second=0,
                                           microsecond=0)

g, w, p = [], [], []
for day in range(90):
    d0 = start + timedelta(days=day)
    frac = day / 89.0
    # glucose: mild fasting drift up, bigger post-meal excursions
    for hour, minute, kind in ((7, 10, "fasting"), (13, 30, "post lunch"),
                               (20, 0, "post dinner")):
        t = d0.replace(hour=hour, minute=minute) + timedelta(
            minutes=random.randint(-25, 25))
        if kind == "fasting":
            base = 5.1 + 0.35 * frac
        elif kind == "post lunch":
            base = 6.6 + 0.5 * frac
        else:
            base = 7.2 + 0.6 * frac
        val = round(base + random.gauss(0, 0.35), 1)
        g.append(GlucoseReading(user=user, taken_at=t, value_mmol=val,
                                note=kind if random.random() < 0.25 else ""))
    # weight: slow downward trend
    t = d0.replace(hour=6, minute=45) + timedelta(minutes=random.randint(0, 40))
    kg = 82.4 - 2.1 * frac + random.gauss(0, 0.18)
    w.append(WeightReading(user=user, taken_at=t,
                           value_kg=round(kg, 1)))
    # blood pressure: morning + evening, slightly wider systolic
    for hour in (8, 21):
        if random.random() < 0.85:
            t = d0.replace(hour=hour, minute=15) + timedelta(
                minutes=random.randint(-30, 60))
            sys = int(131 - 4 * frac + random.gauss(0, 5))
            dia = int(83 - 2 * frac + random.gauss(0, 3.5))
            p.append(BloodPressureReading(user=user, taken_at=t,
                                          systolic=sys, diastolic=dia))

GlucoseReading.objects.bulk_create(g)
WeightReading.objects.bulk_create(w)
BloodPressureReading.objects.bulk_create(p)

Schedule.objects.create(user=user, name="Morning glucose", metric="glucose",
                        time=timezone.datetime.strptime("07:30", "%H:%M").time(),
                        weekdays=[0, 1, 2, 3, 4, 5, 6])
Schedule.objects.create(user=user, name="Evening weight", metric="weight",
                        time=timezone.datetime.strptime("21:00", "%H:%M").time(),
                        weekdays=[0, 1, 2, 3, 4])
Schedule.objects.create(user=user, name="BP check", metric="bp",
                        time=timezone.datetime.strptime("08:00", "%H:%M").time(),
                        weekdays=[0, 3])

print(f"John seeded: {len(g)} glucose, {len(w)} weight, {len(p)} bp, "
      f"{Schedule.objects.filter(user=user).count()} schedules")
