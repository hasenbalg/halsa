"""Overdue-measurement engine, run by the /scheduler/tick/ endpoint.

For every active schedule: walk its recent slots, find slots that are past
slot + grace, check whether a reading of that metric landed within the
user's configured window around the slot, and if not - and we have not
emailed about this exact slot yet - record an OverdueNotice and queue it.

All overdue items for one user are combined into ONE email per tick.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _, override

from .models import (
    BloodPressureReading,
    GlucoseReading,
    Metric,
    MetricSettings,
    OverdueNotice,
    Schedule,
    WeightReading,
)

READING_MODEL = {
    Metric.GLUCOSE: GlucoseReading,
    Metric.WEIGHT: WeightReading,
    Metric.BP: BloodPressureReading,
}

# Weight is stored per-day; a same-day reading satisfies any slot.
DATE_FIELD = {
    Metric.GLUCOSE: "taken_at",
    Metric.WEIGHT: "taken_at__date",
    Metric.BP: "taken_at",
}


def settings_for(user, metric):
    ms, _x = MetricSettings.objects.get_or_create(user=user, metric=metric)
    return ms


def is_satisfied(schedule, slot, ms):
    """True if a reading of the metric landed within the window around slot."""
    model = READING_MODEL[schedule.metric]
    field = DATE_FIELD[schedule.metric]
    qs = model.objects.filter(user=schedule.user)
    if schedule.metric == Metric.WEIGHT:
        return qs.filter(**{field: slot.date()}).exists()
    lo = slot - timezone.timedelta(minutes=ms.window_minutes)
    hi = slot + timezone.timedelta(minutes=ms.window_minutes)
    return qs.filter(**{f"{field}__range": (lo, hi)}).exists()


def collect_overdue(now=None):
    """-> dict user -> list of (schedule, slot) that need their first email."""
    now = now or timezone.now()
    overdue = {}
    for schedule in Schedule.objects.filter(active=True).select_related("user"):
        ms = settings_for(schedule.user, schedule.metric)
        grace = timezone.timedelta(minutes=ms.grace_minutes)
        notified = set(schedule.notices.values_list("slot", flat=True))
        for slot in schedule.recent_slots(now, count=8):
            if now - slot > timezone.timedelta(hours=36):
                continue  # too old to nag about
            if now < slot + grace:
                continue  # not overdue yet
            if slot in notified:
                continue  # already emailed about this slot
            if is_satisfied(schedule, slot, ms):
                continue
            overdue.setdefault(schedule.user, []).append((schedule, slot))
            try:
                OverdueNotice.objects.create(schedule=schedule, slot=slot)
            except IntegrityError:
                pass  # concurrent tick won the race for this slot
    return overdue


def build_email(user, items):
    lines = [_("Hi %(name)s,") % {"name": user.username}, ""]
    when_fmt = "D d.m. H:i"
    if len(items) == 1:
        sched, slot = items[0]
        lines.append(_("Your measurement '%(name)s' (%(metric)s)")
                     % {"name": sched.name,
                        "metric": sched.get_metric_display()})
        lines.append(_("was due %(when)s and is still missing.")
                     % {"when": date_format(timezone.localtime(slot),
                                            when_fmt)})
    else:
        lines.append(_("You have %(n)s measurements that are overdue:")
                     % {"n": len(items)})
        for sched, slot in items:
            lines.append("  - %s (%s) %s %s" % (
                sched.name, sched.get_metric_display(),
                _("due"),
                date_format(timezone.localtime(slot), when_fmt)))
    base = getattr(settings, "SITE_BASE_URL", "").rstrip("/")
    lines += ["", _("Log it now: %(url)s") % {"url": f"{base}/add/"}, ""]
    lines.append(_("(or open %(url)s to see your trends)") % {"url": f"{base}/"})
    subject = (
        _("Hälsa: 1 measurement overdue")
        if len(items) == 1
        else _("Hälsa: %(n)s measurements overdue") % {"n": len(items)}
    )
    return subject, "\n".join(lines)


def run_tick(now=None):
    """Full tick: collect overdue slots, send one combined email per user."""
    overdue = collect_overdue(now)
    sent = []
    for user, items in overdue.items():
        # keep only metrics whose email is enabled for this user
        enabled = {
            ms.metric
            for ms in MetricSettings.objects.filter(user=user)
            if ms.email_enabled
        }
        items = [(s, slot) for s, slot in items if s.metric in enabled]
        if not items:
            continue
        if not user.email:
            continue
        lang = getattr(user, "profile", None) and user.profile.language
        with override(lang or None):
            subject, body = build_email(user, items)
        send_mail(
            subject,
            body,
            getattr(settings, "DEFAULT_FROM_EMAIL", "halsa@localhost"),
            [user.email],
            fail_silently=True,
        )
        sent.append({"user": user.username, "items": len(items)})
    return {
        "checked": Schedule.objects.filter(active=True).count(),
        "overdue_users": len(overdue),
        "emails_sent": len(sent),
        "detail": sent,
    }


def status_rows(user, now=None):
    """Per-schedule status for today, for the dashboard and schedules page."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    rows = []
    for s in Schedule.objects.filter(user=user):
        ms = settings_for(user, s.metric)
        slot = None
        status = None
        if s.active and s.occurs_on(today):
            slot = s.slot_on(today)
            if is_satisfied(s, slot, ms):
                status = "done"
            elif now >= slot + timezone.timedelta(minutes=ms.grace_minutes):
                status = "overdue"
            elif now >= slot:
                status = "due"
            else:
                status = "today"
        rows.append({
            "s": s, "slot": slot, "status": status, "ms": ms,
            "status_label": {
                "done": _("done"), "overdue": _("overdue"),
                "due": _("due"), "today": _("today"),
            }.get(status or "", ""),
            "next": s.next_slot(now) if s.active else None,
        })
    return rows
