"""Long-term trend analysis: plain-language insights from reading history.

All functions take querysets of readings (newest first, as stored) and a
units string, and return a list of insight dicts:
    {"text": "...", "tone": "good" | "warn" | "bad" | "info"}

Insight text is translated in the active language (issue #10).
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext as _

from . import units as U


def _slope_per_week(points):
    """Least-squares slope. points: [(days_ago, value)] -> value per week."""
    n = len(points)
    if n < 2:
        return None
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom * 7.0


def _mean(values):
    return sum(values) / len(values) if values else None


def weight_insights(readings, units):
    """readings: WeightReading queryset, newest first."""
    out = []
    now = timezone.localdate()
    rows = [(r, r.date) for r in readings if r.date]
    recent = [(r, d) for r, d in rows if (now - d).days <= 28]
    if len(recent) >= 5:
        pts = [(-(d - now).days, float(r.value_kg)) for r, d in recent]
        slope = _slope_per_week(pts)
        if slope is not None:
            disp, label = U.weight_display(Decimal(str(abs(slope))), units)
            if slope < -0.05:
                out.append({"text": _("Weight trending down %(disp)s "
                                      "%(label)s/week over the last 4 weeks")
                            % {"disp": disp, "label": label}, "tone": "good"})
            elif slope > 0.05:
                out.append({"text": _("Weight trending up %(disp)s "
                                      "%(label)s/week over the last 4 weeks")
                            % {"disp": disp, "label": label}, "tone": "warn"})
            else:
                out.append({"text": _("Weight holding steady over the "
                                      "last 4 weeks"), "tone": "good"})
    # long-term: 90 days vs previous 90
    last90 = [float(r.value_kg) for r, d in rows if (now - d).days <= 90]
    prev90 = [float(r.value_kg) for r, d in rows if 90 < (now - d).days <= 180]
    if len(last90) >= 5 and len(prev90) >= 5:
        delta = _mean(last90) - _mean(prev90)
        disp, label = U.weight_display(Decimal(str(abs(delta))), units)
        if abs(float(disp)) < 0.5:
            out.append({"text": _("90-day average unchanged vs the "
                                   "previous quarter"), "tone": "info"})
        elif delta < 0:
            out.append({"text": _("90-day average is %(disp)s %(label)s "
                                  "below the previous quarter")
                        % {"disp": disp, "label": label}, "tone": "good"})
        else:
            out.append({"text": _("90-day average is %(disp)s %(label)s "
                                  "above the previous quarter")
                        % {"disp": disp, "label": label}, "tone": "info"})
    return out


def glucose_insights(readings, units):
    """readings: GlucoseReading queryset, newest first."""
    out = []
    now = timezone.now()
    rows = [(r, r.taken_at) for r in readings]
    recent = [float(r.value_mmol) for r, t in rows if (now - t) <= timedelta(days=14)]
    prior = [float(r.value_mmol) for r, t in rows if timedelta(days=14) < (now - t) <= timedelta(days=28)]

    def disp(v):
        d, _lbl = U.glucose_display(Decimal(str(v)), units)
        return str(d)

    if len(recent) >= 3:
        avg = _mean(recent)
        text = _("Average glucose %(v)s %(unit)s over the last 14 days") % {
            "v": disp(avg), "unit": U.glucose_unit_label(units)}
        tone = "info"
        if avg > 7.0:
            text += _(" - above target")
            tone = "warn"
        if len(prior) >= 3:
            diff = avg - _mean(prior)
            if abs(float(disp(abs(diff)))) >= 0.1 or abs(diff) >= 0.05:
                arrow = _("up") if diff > 0 else _("down")
                text += _(", %(arrow)s from %(v)s in the prior two weeks") % {
                    "arrow": arrow, "v": disp(_mean(prior))}
                if diff > 0:
                    tone = "warn" if tone == "warn" else "info"
        out.append({"text": text, "tone": tone})

    # estimated HbA1c from 90 days of data
    last90 = [float(r.value_mmol) for r, t in rows if (now - t) <= timedelta(days=90)]
    if len(last90) >= 10:
        avg_mmol = _mean(last90)
        avg_mgdl = float(avg_mmol) * 18.0182
        ea1c = (avg_mgdl + 46.7) / 28.7
        tone = "good" if ea1c < 5.7 else ("warn" if ea1c < 6.5 else "bad")
        out.append({"text": _("Estimated HbA1c %(v)s%% from the last 90 days")
                    % {"v": f"{ea1c:.1f}"}, "tone": tone})
        lo, hi = 3.9, 10.0
        in_range = sum(1 for v in last90 if lo <= v <= hi) / len(last90) * 100
        tone = "good" if in_range >= 80 else ("warn" if in_range >= 60 else "bad")
        out.append({"text": _("%(pct)s%% of readings in range "
                              "(3.9-10.0 mmol/L) over 90 days")
                    % {"pct": f"{in_range:.0f}"}, "tone": tone})
    return out


def bp_insights(readings, units):
    """readings: BloodPressureReading queryset, newest first."""
    out = []
    now = timezone.now()
    rows = [(r, r.taken_at) for r in readings]
    recent = [(r.systolic, r.diastolic) for r, t in rows if (now - t) <= timedelta(days=14)]
    prior = [
        (r.systolic, r.diastolic)
        for r, t in rows
        if timedelta(days=14) < (now - t) <= timedelta(days=28)
    ]
    if len(recent) >= 3:
        sys_avg = _mean([s for s, d in recent])
        dia_avg = _mean([d for s, d in recent])
        text = _("Average blood pressure %(sys)s/%(dia)s mmHg "
                 "over the last 14 days") % {
            "sys": f"{sys_avg:.0f}", "dia": f"{dia_avg:.0f}"}
        if sys_avg >= 135 or dia_avg >= 85:
            text += _(" - consistently elevated")
            out.append({"text": text, "tone": "warn"})
        else:
            out.append({"text": text, "tone": "good"})
        if len(prior) >= 3:
            d_sys = sys_avg - _mean([s for s, d in prior])
            if abs(d_sys) >= 3:
                arrow = _("up") if d_sys > 0 else _("down")
                tone = "warn" if d_sys > 0 else "good"
                out.append({"text": _("Systolic %(arrow)s %(v)s mmHg "
                                      "vs the prior two weeks")
                            % {"arrow": arrow, "v": f"{abs(d_sys):.0f}"},
                            "tone": tone})
    # long-term slope on systolic
    last90 = [(t, r.systolic) for r, t in rows if (now - t) <= timedelta(days=90)]
    if len(last90) >= 10:
        pts = [(-(now - t).total_seconds() / 86400, float(s)) for t, s in last90]
        slope = _slope_per_week(pts)
        if slope is not None and abs(slope) >= 0.5:
            arrow = _("rising") if slope > 0 else _("falling")
            tone = "warn" if slope > 0 else "good"
            out.append({"text": _("Systolic %(arrow)s about %(v)s mmHg/week "
                                  "across 90 days")
                        % {"arrow": arrow, "v": f"{abs(slope):.1f}"},
                        "tone": tone})
    return out
