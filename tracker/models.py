import time
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UUIDModel(models.Model):
    """Abstract base: every table in Hälsa uses UUID primary keys."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Profile(UUIDModel):
    class Units(models.TextChoices):
        METRIC = "metric", _("Metric (mmol/L, kg)")
        IMPERIAL = "imperial", _("Imperial (mg/dL, lb)")

    class Language(models.TextChoices):
        AUTO = "", _("Auto (browser)")
        EN = "en", "English"
        DE = "de", "Deutsch"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    units = models.CharField(max_length=10, choices=Units.choices, default=Units.METRIC)
    # Empty means "auto": follow the browser's Accept-Language.
    language = models.CharField(max_length=10, blank=True, choices=Language.choices,
                                default=Language.AUTO)

    # TOTP two-factor enrollment. Enforcement starts only after the user
    # proves the seed with a code (nobody gets locked out mid-setup).
    totp_seed = models.CharField(max_length=64, blank=True)
    totp_confirmed = models.BooleanField(default=False)
    last_verified_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"profile of {self.user}"

    @property
    def two_factor_enabled(self):
        return bool(self.totp_seed) and self.totp_confirmed

    def totp(self):
        import pyotp

        return pyotp.TOTP(self.totp_seed)

    def provisioning_uri(self, issuer="Hälsa"):
        import pyotp

        return pyotp.totp.TOTP(self.totp_seed).provisioning_uri(
            name=self.user.username, issuer_name=issuer
        )

    def _check_token(self, token):
        token = (token or "").strip()
        if not token:
            return False
        now = time.time()
        totp = self.totp()
        valid = {totp.at(now + off) for off in (-30, 0, 30)}
        if token in valid:
            self.last_verified_at = timezone.now()
            self.save(update_fields=["last_verified_at"])
            return True
        return False

    def verify(self, token):
        """Login-time check: only once enrollment is confirmed."""
        if not self.two_factor_enabled:
            return False
        return self._check_token(token)

    def verify_enrollment(self, token):
        """Enrollment confirmation: seed set but not yet confirmed."""
        if not self.totp_seed:
            return False
        return self._check_token(token)


class GlucoseContext(models.TextChoices):
    """Meal context of a glucose reading (issue #9).

    Plain language in the app, Latin terms in the doctor report.
    Empty string means "not specified" and is always allowed.
    """

    FASTING = "fasting", _("Fasting")
    PRE = "pre", _("Before meal")
    POST = "post", _("After meal")
    RANDOM = "random", _("Random")


# Latin terms for the doctor report (issue #9); app UI uses the plain
# labels above.
GLUCOSE_CONTEXT_LATIN = {
    "fasting": "Fasting",
    "pre": "Preprandial",
    "post": "Postprandial",
    "random": "Random",
}


class GlucoseReading(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="glucose_readings"
    )
    taken_at = models.DateTimeField(default=timezone.now)
    # Canonical storage unit: mmol/L (European standard).
    value_mmol = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0.5), MaxValueValidator(40)],
    )
    context = models.CharField(
        max_length=10, blank=True, choices=GlucoseContext.choices
    )
    note = models.TextField(blank=True, max_length=2000)

    class Meta:
        ordering = ["-taken_at"]
        indexes = [models.Index(fields=["user", "-taken_at"])]

    def __str__(self):
        return f"{self.value_mmol} mmol/L @ {self.taken_at:%Y-%m-%d %H:%M}"


class WeightReading(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="weight_readings"
    )
    date = models.DateField(default=timezone.localdate)
    # Canonical storage unit: kg.
    value_kg = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(2), MaxValueValidator(500)],
    )
    note = models.TextField(blank=True, max_length=2000)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["user", "-date"])]

    def __str__(self):
        return f"{self.value_kg} kg on {self.date}"


class BloodPressureReading(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bp_readings"
    )
    taken_at = models.DateTimeField(default=timezone.now)
    systolic = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(60), MaxValueValidator(260)]
    )
    diastolic = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(30), MaxValueValidator(160)]
    )
    pulse = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(20), MaxValueValidator(250)]
    )
    note = models.TextField(blank=True, max_length=2000)

    class Meta:
        ordering = ["-taken_at"]
        indexes = [models.Index(fields=["user", "-taken_at"])]
        verbose_name = "blood pressure reading"

    def __str__(self):
        return f"{self.systolic}/{self.diastolic} @ {self.taken_at:%Y-%m-%d %H:%M}"


class Metric(models.TextChoices):
    GLUCOSE = "glucose", _("Glucose")
    WEIGHT = "weight", _("Weight")
    BP = "bp", _("Blood pressure")


class MetricSettings(UUIDModel):
    """Per-user, per-metric scheduling knobs."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="metric_settings"
    )
    metric = models.CharField(max_length=10, choices=Metric.choices)
    # A reading counts as satisfying a slot if it lies within
    # [slot - window_minutes, slot + window_minutes].
    window_minutes = models.PositiveIntegerField(default=120)
    # The overdue email goes out at slot + grace_minutes.
    grace_minutes = models.PositiveIntegerField(default=60)
    email_enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "metric"], name="uniq_user_metric_settings"
            )
        ]

    def __str__(self):
        return (
            f"{self.user} {self.metric}: +/-%s m, grace %s m"
            % (self.window_minutes, self.grace_minutes)
        )


class Schedule(UUIDModel):
    """A named recurring measurement: metric + weekdays + time of day."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="schedules"
    )
    name = models.CharField(max_length=80)
    metric = models.CharField(max_length=10, choices=Metric.choices)
    time = models.TimeField()
    # Python weekday numbers, Monday=0 ... Sunday=6.
    weekdays = models.JSONField(default=list, help_text="Weekdays 0=Mon..6=Sun")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["metric", "time", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_metric_display()} {self.time:%H:%M})"

    def occurs_on(self, date):
        return date.weekday() in (self.weekdays or [])

    def slot_on(self, date):
        """Aware datetime of this schedule slot on a given local date."""
        naive = timezone.datetime.combine(date, self.time)
        return timezone.make_aware(naive)

    def recent_slots(self, now, count=8):
        """Most recent `count` slots at or before `now`, oldest first."""
        slots = []
        day = timezone.localdate(now)
        for _ in range(64):
            if self.occurs_on(day):
                slot = self.slot_on(day)
                if slot <= now:
                    slots.append(slot)
                    if len(slots) >= count:
                        break
            day -= timezone.timedelta(days=1)
        return list(reversed(slots))

    def next_slot(self, now):
        if not self.active:
            return None
        day = timezone.localdate(now)
        for _ in range(8):
            if self.occurs_on(day):
                slot = self.slot_on(day)
                if slot > now:
                    return slot
            day += timezone.timedelta(days=1)
        return None


class OverdueNotice(UUIDModel):
    """One row per (schedule, slot) already emailed about."""

    schedule = models.ForeignKey(
        Schedule, on_delete=models.CASCADE, related_name="notices"
    )
    slot = models.DateTimeField()
    notified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["schedule", "slot"], name="uniq_notice_per_slot")
        ]

    def __str__(self):
        return f"overdue notice {self.schedule} @ {self.slot}"
