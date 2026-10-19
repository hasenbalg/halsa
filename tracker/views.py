import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Avg, Max, Min
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("halsa")

from . import charts, pdfexport, scheduling, trends, units as U
from .forms import (
    BloodPressureForm,
    GlucoseForm,
    MetricSettingsForm,
    QuickAddForm,
    RestoreForm,
    ScheduleForm,
    UnitsForm,
    WeightForm,
)
from .models import (
    BloodPressureReading,
    GlucoseReading,
    Metric,
    MetricSettings,
    Profile,
    Schedule,
    WeightReading,
)

RANGES = {"7": 7, "30": 30, "90": 90, "365": 365, "all": None}


def get_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _range_days(request):
    return RANGES.get(request.GET.get("range", "30"), 30)


def _since(days):
    return timezone.now() - timedelta(days=days) if days else None


def _fmt_dt(dt, units):
    local = timezone.localtime(dt)
    today = timezone.localdate()
    if local.date() == today:
        return f"today {local:%H:%M}"
    if local.date() == today - timedelta(days=1):
        return f"yesterday {local:%H:%M}"
    return f"{local:%d.%m. %H:%M}"


def _delta_html(latest, ref, fmt):
    if ref is None or latest is None:
        return ""
    diff = latest - ref
    if abs(diff) < Decimal("0.05"):
        return '<span class="delta flat">steady</span>'
    arrow = "&#9650;" if diff > 0 else "&#9660;"
    cls = "up" if diff > 0 else "down"
    return f'<span class="delta {cls}">{arrow} {fmt(abs(diff))}</span>'


# --- auth ------------------------------------------------------------------

PENDING_KEY = "halsa_" + "2fa_user" + "_pk"


def login_view(request):
    next_url = request.POST.get("next") or request.GET.get("next") or "/"
    if not url_has_allowed_host_and_scheme(
            url=next_url, allowed_hosts={request.get_host()},
            require_https=request.is_secure()):
        next_url = "/"

    if request.method == "POST" and request.session.get(PENDING_KEY):
        pk = request.session.pop(PENDING_KEY)
        profile_row = Profile.objects.filter(user_id=pk).first()
        user = profile_row.user if profile_row else None
        # 2FA disabled or account gone mid-login -> back to password step
        if user and user.is_active and profile_row.two_factor_enabled:
            token = request.POST.get("code", "")
            profile = get_profile(user)
            if profile.verify(token):
                logger.info("login ok (2fa)")
                auth_login(request, user)
                return redirect(next_url)
            logger.warning("login 2fa code failed")
            return render(
                request, "login.html",
                {"step": "code", "next": next_url,
                 "error": "That code didn't work. Check your authenticator app."},
            )
        # stale pending entry -> back to password step
        return render(
            request, "login.html",
            {"step": "password", "next": next_url, "form": AuthenticationForm(),
             "error": "Sign in again to continue."},
        )

    if request.user.is_authenticated:
        return redirect(next_url)

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()
            profile = get_profile(user)
            if profile.two_factor_enabled:
                logger.info("login password ok, 2fa pending")
                request.session[PENDING_KEY] = user.pk
                return render(
                    request, "login.html",
                    {"step": "code", "next": next_url},
                )
            auth_login(request, user)
            logger.info("login ok")
            messages.success(request, "Welcome back.")
            return redirect(next_url)
        if request.method == "POST":
            logger.warning("login failed")
    return render(
        request, "login.html",
        {"step": "password", "next": next_url, "form": form},
    )


@require_POST
def logout_view(request):
    logger.info("logout")
    auth_logout(request)
    return redirect("login")


# --- dashboard ---------------------------------------------------------------

@login_required
def dashboard(request):
    user = request.user
    units = get_profile(user).units
    now = timezone.now()
    since30 = now - timedelta(days=30)

    g_all = GlucoseReading.objects.filter(user=user)
    w_all = WeightReading.objects.filter(user=user)
    b_all = BloodPressureReading.objects.filter(user=user)

    g30 = list(g_all.filter(taken_at__gte=since30).order_by("taken_at"))
    w30 = list(w_all.filter(date__gte=now.date() - timedelta(days=30)).order_by("date"))
    b30 = list(b_all.filter(taken_at__gte=since30).order_by("taken_at"))

    latest_g = g_all.first()
    latest_w = w_all.first()
    latest_b = b_all.first()

    def g_delta():
        if not latest_g:
            return ""
        ref = GlucoseReading.objects.filter(
            user=user,
            taken_at__range=(latest_g.taken_at - timedelta(days=8),
                             latest_g.taken_at - timedelta(days=6)),
        ).aggregate(a=Avg("value_mmol"))["a"]
        return _delta_html(latest_g.value_mmol, ref, lambda d: f"{U.glucose_display(d, units)[0]}")

    def w_delta():
        if not latest_w:
            return ""
        ref = WeightReading.objects.filter(
            user=user,
            date__range=(latest_w.date - timedelta(days=8),
                         latest_w.date - timedelta(days=6)),
        ).aggregate(a=Avg("value_kg"))["a"]
        return _delta_html(latest_w.value_kg, ref, lambda d: f"{U.weight_display(d, units)[0]} kg")

    cards = [
        {
            "name": "Glucose",
            "url": "glucose",
            "css": "glucose",
            "value": (
                f'{U.glucose_display(latest_g.value_mmol, units)[0]}'
                f'<span class="unit">{U.glucose_unit_label(units)}</span>'
            ) if latest_g else "&ndash;",
            "when": _fmt_dt(latest_g.taken_at, units) if latest_g else "no readings",
            "delta": g_delta(),
            "chart": charts.sparkline(
                [(r.taken_at, float(r.value_mmol)) for r in g30],
                color="var(--glucose)",
            ),
            "insights": trends.glucose_insights(g_all[:400], units)[:1],
        },
        {
            "name": "Weight",
            "url": "weight",
            "css": "weight",
            "value": (
                f'{U.weight_display(latest_w.value_kg, units)[0]}'
                f'<span class="unit">{U.weight_unit_label(units)}</span>'
            ) if latest_w else "&ndash;",
            "when": (f"on {latest_w.date}" if latest_w else "no readings"),
            "delta": w_delta(),
            "chart": charts.sparkline(
                [(r.date, float(r.value_kg)) for r in w30],
                color="var(--weight)",
            ),
            "insights": trends.weight_insights(w_all[:400], units)[:1],
        },
        {
            "name": "Blood pressure",
            "url": "pressure",
            "css": "bp",
            "value": f'{latest_b.systolic}/{latest_b.diastolic}<span class="unit">mmHg</span>' if latest_b else "&ndash;",
            "when": _fmt_dt(latest_b.taken_at, units) if latest_b else "no readings",
            "delta": "",
            "chart": charts.sparkline(
                [(r.taken_at, float(r.systolic)) for r in b30],
                color="var(--bp)",
            ),
            "insights": trends.bp_insights(b_all[:400], units)[:1],
        },
    ]

    insights = {
        "glucose": trends.glucose_insights(g_all[:400], units),
        "weight": trends.weight_insights(w_all[:400], units),
        "bp": trends.bp_insights(b_all[:400], units),
    }
    has_insights = any(insights.values())

    recent = sorted(
        [("glucose", r.taken_at, r) for r in g_all[:10]]
        + [("weight", timezone.make_aware(
            timezone.datetime.combine(r.date, timezone.datetime.min.time())), r)
           for r in w_all[:10]]
        + [("bp", r.taken_at, r) for r in b_all[:10]],
        key=lambda t: t[1], reverse=True
    )[:8]

    return render(request, "dashboard.html", {
        "schedule_rows": [r for r in scheduling.status_rows(user) if r["s"].active],
        "cards": cards,
        "insights": insights,
        "has_insights": has_insights,
        "recent": recent,
        "units": units,
    })


# --- quick add ---------------------------------------------------------------

@login_required
def add(request):
    units = get_profile(request.user).units
    if request.method == "POST":
        form = QuickAddForm(request.POST, units=units)
        if form.is_valid():
            created = form.save(request.user)
            names = {
                GlucoseReading: "glucose",
                WeightReading: "weight",
                BloodPressureReading: "blood pressure",
            }
            saved = ", ".join(names[type(r)] for r in created)
            logger.info("readings saved: %s", saved)
            messages.success(request, f"Saved: {saved}.")
            return redirect("/add/?saved=1")
    else:
        form = QuickAddForm(initial={"taken_at": timezone.localtime().replace(microsecond=0)}, units=units)
    return render(request, "add.html", {"form": form, "units": units})


# --- per-metric detail ---------------------------------------------------------

@login_required
def glucose_detail(request):
    units = get_profile(request.user).units
    days = _range_days(request)
    qs = GlucoseReading.objects.filter(user=request.user)
    rows = list(qs.filter(taken_at__gte=_since(days)).order_by("taken_at")) if days else list(qs.order_by("taken_at"))
    points = [(r.taken_at, float(r.value_mmol)) for r in rows]
    rolling = _rolling(points, window=7)
    stats = qs.aggregate(avg=Avg("value_mmol"), lo=Min("value_mmol"), hi=Max("value_mmol"))
    return render(request, "metric.html", {
        "title": "Glucose",
        "css": "glucose",
        "unit": U.glucose_unit_label(units),
        "chart": charts.line_chart(
            [
                {"points": points, "color": "var(--glucose)"},
                {"points": rolling, "color": "var(--muted)", "fill": False, "dashed": True},
            ],
            band=(3.9, 7.8),
            y_decimals=1,
            aria_label="Glucose over time, mmol per litre",
        ),
        "rows": rows,
        "kind": "glucose",
        "stats": _fmt_stats(stats, lambda v: str(U.glucose_display(v, units)[0])),
        "insights": trends.glucose_insights(qs[:400], units),
        "days": days,
        "units": units,
    })


@login_required
def weight_detail(request):
    units = get_profile(request.user).units
    days = _range_days(request)
    qs = WeightReading.objects.filter(user=request.user)
    rows = list(qs.filter(date__gte=timezone.localdate() - timedelta(days=days)).order_by("date")) if days else list(qs.order_by("date"))
    points = [(r.date, float(r.value_kg)) for r in rows]
    rolling = _rolling(points, window=7)
    stats = qs.aggregate(avg=Avg("value_kg"), lo=Min("value_kg"), hi=Max("value_kg"))
    return render(request, "metric.html", {
        "title": "Weight",
        "css": "weight",
        "unit": U.weight_unit_label(units),
        "chart": charts.line_chart(
            [
                {"points": points, "color": "var(--weight)"},
                {"points": rolling, "color": "var(--muted)", "fill": False, "dashed": True},
            ],
            y_decimals=1,
            aria_label="Weight over time",
        ),
        "rows": rows,
        "kind": "weight",
        "stats": _fmt_stats(stats, lambda v: str(U.weight_display(v, units)[0])),
        "insights": trends.weight_insights(qs[:400], units),
        "days": days,
        "units": units,
    })


@login_required
def bp_detail(request):
    units = get_profile(request.user).units
    days = _range_days(request)
    qs = BloodPressureReading.objects.filter(user=request.user)
    rows = list(qs.filter(taken_at__gte=_since(days)).order_by("taken_at")) if days else list(qs.order_by("taken_at"))
    stats = qs.aggregate(avg_s=Avg("systolic"), avg_d=Avg("diastolic"))
    return render(request, "metric.html", {
        "title": "Blood pressure",
        "css": "bp",
        "unit": "mmHg",
        "chart": charts.line_chart(
            [
                {"points": [(r.taken_at, r.systolic) for r in rows], "color": "var(--bp)"},
                {"points": [(r.taken_at, r.diastolic) for r in rows], "color": "var(--accent)", "fill": False},
            ],
            band=(90, 120),
            y_decimals=0,
            aria_label="Blood pressure over time, systolic and diastolic",
        ),
        "rows": rows,
        "kind": "bp",
        "stats": [
            ("Average", f"{stats['avg_s']:.0f}/{stats['avg_d']:.0f}" if stats["avg_s"] else "-"),
            ("Systolic range", f"{qs.aggregate(m=Min('systolic'))['m']}&ndash;{qs.aggregate(m=Max('systolic'))['m']}" if rows else "-"),
        ],
        "insights": trends.bp_insights(qs[:400], units),
        "days": days,
        "units": units,
    })


def _rolling(points, window=7):
    """Trailing mean over `window` most recent points (smooth trend line)."""
    out = []
    n = len(points)
    for i in range(n):
        lo = max(0, i - window + 1)
        chunk = points[lo:i + 1]
        out.append((points[i][0], sum(p[1] for p in chunk) / len(chunk)))
    return out if n >= 3 else []


def _fmt_stats(stats, fmt):
    return [
        ("Average", fmt(stats["avg"]) if stats["avg"] is not None else "-"),
        ("Lowest", fmt(stats["lo"]) if stats["lo"] is not None else "-"),
        ("Highest", fmt(stats["hi"]) if stats["hi"] is not None else "-"),
    ]


# --- edit / delete -------------------------------------------------------------

MODELS = {
    "glucose": (GlucoseReading, GlucoseForm, "taken_at"),
    "weight": (WeightReading, WeightForm, "date"),
    "bp": (BloodPressureReading, BloodPressureForm, "taken_at"),
}


@login_required
def edit(request, kind, pk):
    model, form_class, _ = MODELS[kind]
    obj = get_object_or_404(model, pk=pk, user=request.user)
    units = get_profile(request.user).units
    kwargs = {"units": units} if form_class is not BloodPressureForm else {}
    if request.method == "POST":
        form = form_class(request.POST, instance=obj, **kwargs)
        if form.is_valid():
            form.save()
            logger.info("reading updated: %s", kind)
            messages.success(request, "Updated.")
            return redirect(f"/{kind}/")
    else:
        form = form_class(instance=obj, **kwargs)
    return render(request, "edit.html", {"form": form, "kind": kind, "obj": obj, "units": units})


@login_required
@require_POST
def delete(request, kind, pk):
    model, _, _ = MODELS[kind]
    obj = get_object_or_404(model, pk=pk, user=request.user)
    obj.delete()
    logger.info("reading deleted: %s", kind)
    messages.success(request, "Deleted.")
    return redirect(f"/{kind}/")


@login_required
def history(request):
    units = get_profile(request.user).units
    g = GlucoseReading.objects.filter(user=request.user)[:50]
    w = WeightReading.objects.filter(user=request.user)[:50]
    b = BloodPressureReading.objects.filter(user=request.user)[:50]
    rows = sorted(
        [("glucose", r.taken_at, r) for r in g]
        + [("weight", timezone.make_aware(
            timezone.datetime.combine(r.date, timezone.datetime.min.time())), r)
           for r in w]
        + [("bp", r.taken_at, r) for r in b],
        key=lambda t: t[1], reverse=True,
    )
    return render(request, "history.html", {"rows": rows, "units": units})


# --- settings --------------------------------------------------------------------

@login_required
def settings_view(request):
    profile = get_profile(request.user)
    if request.method == "POST" and request.POST.get("units"):
        form = UnitsForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            logger.info("units changed")
            messages.success(request, "Units updated.")
            return redirect("settings")
    elif request.method == "POST":
        forms_ = []
        for metric, label in Metric.choices:
            ms = scheduling.settings_for(request.user, metric)
            forms_.append(MetricSettingsForm(
                request.POST, instance=ms, prefix=f"m{metric}"))
        if all(f.is_valid() for f in forms_):
            for f in forms_:
                f.save()
            logger.info("scheduling settings updated")
            messages.success(request, "Scheduling settings updated.")
            return redirect("settings")
    form = UnitsForm(instance=profile)
    metric_forms = []
    for metric, label in Metric.choices:
        ms = scheduling.settings_for(request.user, metric)
        metric_forms.append((label, MetricSettingsForm(instance=ms,
                                                        prefix=f"m{metric}")))
    return render(request, "settings.html", {
        "form": form,
        "profile": profile,
        "metric_forms": metric_forms,
        "restore_form": RestoreForm(),
    })


@login_required
def two_factor(request):
    import segno

    profile = get_profile(request.user)
    qr = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "enroll":
            import pyotp

            profile.totp_seed = pyotp.random_base32()
            profile.totp_confirmed = False
            profile.save(update_fields=["totp_seed", "totp_confirmed"])
            logger.info("2fa enrollment started")
            messages.info(request, "Scan the QR code, then confirm with a code.")
            return redirect("two_factor")
        elif action == "confirm":
            if profile.verify_enrollment(request.POST.get("code", "")):
                profile.totp_confirmed = True
                profile.save(update_fields=["totp_confirmed", "last_verified_at"])
                logger.info("2fa enabled")
                messages.success(request, "Two-factor authentication enabled.")
                return redirect("settings")
            logger.warning("2fa confirm failed")
            messages.error(request, "Wrong code - try the next one from your app.")
        elif action == "disable":
            if profile._check_token(request.POST.get("code", "")):
                profile.totp_seed = ""
                profile.totp_confirmed = False
                profile.save(update_fields=["totp_seed", "totp_confirmed"])
                logger.info("2fa disabled")
                messages.success(request, "Two-factor authentication disabled.")
                return redirect("settings")
            logger.warning("2fa disable rejected")
            messages.error(request, "A current valid code is required to disable 2FA.")
    if profile.totp_seed and not profile.two_factor_enabled:
        try:
            qr = segno.make(profile.provisioning_uri()).svg_data_uri(scale=5, border=2)
        except Exception:
            qr = None
    return render(request, "two_factor.html", {
        "profile": profile,
        "qr": qr,
        "seed": profile.totp_seed,
    })


# --- scheduler -----------------------------------------------------------------

@csrf_exempt
def tick(request):
    """Overdue check endpoint. Bearer-token protected; GET or POST."""
    from django.conf import settings as dj_settings
    from django.http import HttpResponseForbidden, JsonResponse

    expected = getattr(dj_settings, "SCHEDULER_TOKEN", "")
    auth = request.headers.get("Authorization", "")
    if not expected or auth != f"Bearer {expected}":
        logger.warning("scheduler tick: bad token")
        return HttpResponseForbidden("invalid token")
    result = scheduling.run_tick()
    logger.info("tick: checked=%(checked)s overdue=%(overdue_users)s "
                "emails=%(emails_sent)s", result)
    return JsonResponse(result)


@login_required
def schedules(request):
    rows = scheduling.status_rows(request.user)
    return render(request, "schedules.html", {"rows": rows})


@login_required
def schedule_edit(request, pk=None):
    from .models import Schedule
    obj = get_object_or_404(Schedule, pk=pk, user=request.user) if pk else None
    if request.method == "POST":
        form = ScheduleForm(request.POST, instance=obj)
        if form.is_valid():
            s = form.save(commit=False)
            s.user = request.user
            s.save()
            logger.info("schedule saved")
            messages.success(request, "Schedule saved.")
            return redirect("schedules")
    else:
        form = ScheduleForm(instance=obj)
    return render(request, "schedule_form.html", {"form": form, "obj": obj})


@login_required
@require_POST
def schedule_delete(request, pk):
    from .models import Schedule
    obj = get_object_or_404(Schedule, pk=pk, user=request.user)
    obj.delete()
    logger.info("schedule deleted")
    messages.success(request, "Schedule deleted.")
    return redirect("schedules")


# --- export ---------------------------------------------------------------------

def _backup_payload(user):
    def iso(dt):
        return dt.isoformat()

    return {
        "app": "halsa",
        "export_version": 1,
        "exported_at": iso(timezone.now()),
        "profile": {
            "username": user.username,
            "email": user.email,
            "units": get_profile(user).units,
        },
        "glucose_readings": [
            {"id": str(r.id), "taken_at": iso(r.taken_at),
             "value_mmol": str(r.value_mmol), "note": r.note}
            for r in GlucoseReading.objects.filter(user=user).order_by("taken_at")
        ],
        "weight_readings": [
            {"id": str(r.id), "date": r.date.isoformat(),
             "value_kg": str(r.value_kg), "note": r.note}
            for r in WeightReading.objects.filter(user=user).order_by("date")
        ],
        "blood_pressure_readings": [
            {"id": str(r.id), "taken_at": iso(r.taken_at),
             "systolic": r.systolic, "diastolic": r.diastolic,
             "pulse": r.pulse, "note": r.note}
            for r in BloodPressureReading.objects.filter(user=user).order_by("taken_at")
        ],
        "schedules": [
            {"id": str(s.id), "name": s.name, "metric": s.metric,
             "time": s.time.strftime("%H:%M"), "weekdays": s.weekdays,
             "active": s.active}
            for s in Schedule.objects.filter(user=user)
        ],
        "metric_settings": [
            {"metric": ms.metric, "window_minutes": ms.window_minutes,
             "grace_minutes": ms.grace_minutes, "email_enabled": ms.email_enabled}
            for ms in MetricSettings.objects.filter(user=user)
        ],
    }


@login_required
def export_json(request):
    from django.http import JsonResponse as _Json
    payload = _backup_payload(request.user)
    logger.info("json export: %d readings", sum(
        len(payload[k]) for k in ("glucose_readings", "weight_readings",
                                  "blood_pressure_readings")))
    response = _Json(payload)
    day = timezone.localdate().strftime("%Y%m%d")
    response["Content-Disposition"] = f'attachment; filename="halsa-backup-{day}.json"'
    return response


@login_required
def export_pdf(request):
    from django.http import HttpResponse
    days = _range_days(request)
    logger.info("pdf export: range=%s", days)
    pdf = pdfexport.build_report(request.user, get_profile(request.user).units, days)
    response = HttpResponse(pdf, content_type="application/pdf")
    day = timezone.localdate().strftime("%Y%m%d")
    response["Content-Disposition"] = f'attachment; filename="halsa-report-{day}.pdf"'
    return response


@login_required
@require_POST
def restore(request):
    from .restore import RestoreError, restore_from_json

    upload = request.FILES.get("backup")
    if not upload:
        messages.error(request, "Choose a backup file first.")
        return redirect("settings")
    if upload.size > 20 * 1024 * 1024:
        messages.error(request, "Backup file too large (max 20 MB).")
        return redirect("settings")
    raw = upload.read().decode("utf-8", errors="replace")
    try:
        summary = restore_from_json(request.user, raw)
    except RestoreError as e:
        logger.warning("restore failed: %s", e)
        messages.error(request, f"Restore failed: {e}")
    else:
        created = sum(summary["created"].values())
        updated = sum(summary["updated"].values())
        logger.info("restore: %d created, %d updated", created, updated)
        messages.success(
            request, f"Restore complete: {created} records created, {updated} updated."
        )
    return redirect("settings")
