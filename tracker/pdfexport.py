"""Doctor-report PDF built with reportlab (pure Python, no system deps).

Layout: header, then per metric: title, summary stats, trend insights,
a native line chart, and a compact readings table.
"""

from datetime import timedelta
from io import BytesIO

from django.utils import timezone

from . import trends, units as U
from .models import (
    GLUCOSE_CONTEXT_LATIN,
    BloodPressureReading,
    GlucoseReading,
    WeightReading,
)

PAGE = (595, 842)  # A4 pt
MARGIN = 42
ACCENT = "#1f2937"
MUTED = "#6b7280"
GRID = "#e5e7eb"
COLORS = {"glucose": "#d97706", "weight": "#7c3aed", "bp": "#e11d48",
          "bp2": "#4f46e5"}

MAX_TABLE_ROWS = 200


def _styles():
    from reportlab.lib.styles import ParagraphStyle
    return {
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20,
                             textColor=ACCENT, spaceAfter=2),
        "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5,
                              textColor=MUTED, spaceAfter=14),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
                             textColor=ACCENT, spaceBefore=16, spaceAfter=4),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5,
                               textColor=ACCENT, leading=13),
        "ins": ParagraphStyle("ins", fontName="Helvetica", fontSize=9,
                              textColor=MUTED, leading=12, leftIndent=8),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8,
                                textColor=MUTED),
    }


def _chart(points, color, height=130, width=PAGE[0] - 2 * MARGIN, y_fmt=None):
    from reportlab.lib.colors import HexColor
    color = HexColor(color)
    """Native reportlab line chart; x = days, y = value."""
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String

    if len(points) < 2:
        return None
    t0 = points[0][0]
    data = [[((p[0] - t0).total_seconds() / 86400.0, float(p[1])) for p in points]]
    d = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y = 40, 18
    lp.width, lp.height = width - 55, height - 34
    lp.data = data
    lp.lines[0].strokeColor = color
    lp.lines[0].strokeWidth = 1.4
    lp.lines[0].strokeDashArray = None
    lp.xValueAxis.labels.fontSize = 7
    lp.xValueAxis.labels.fillColor = HexColor(MUTED)
    lp.yValueAxis.labels.fontSize = 7
    lp.yValueAxis.labels.fillColor = HexColor(MUTED)
    lp.yValueAxis.strokeColor = HexColor(GRID)
    lp.xValueAxis.strokeColor = HexColor(GRID)
    lp.yValueAxis.gridStrokeColor = HexColor(GRID)
    lp.yValueAxis.gridStrokeWidth = 0.5
    if y_fmt:
        lp.yValueAxis.valueFormatter = y_fmt
    d.add(lp)
    return d


def _dual_chart(rows, y_fmt=None):
    """Systolic + diastolic in one chart."""
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.colors import HexColor  # noqa: F401

    if len(rows) < 2:
        return None
    t0 = rows[0].taken_at
    sys_pts = [((r.taken_at - t0).total_seconds() / 86400.0, r.systolic) for r in rows]
    dia_pts = [((r.taken_at - t0).total_seconds() / 86400.0, r.diastolic) for r in rows]
    width, height = PAGE[0] - 2 * MARGIN, 130
    d = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y = 40, 18
    lp.width, lp.height = width - 55, height - 34
    lp.data = [sys_pts, dia_pts]
    lp.lines[0].strokeColor = HexColor(COLORS["bp"])
    lp.lines[1].strokeColor = HexColor(COLORS["bp2"])
    for i in (0, 1):
        lp.lines[i].strokeWidth = 1.3
        lp.lines[i].strokeDashArray = None
    lp.xValueAxis.labels.fontSize = 7
    lp.xValueAxis.labels.fillColor = HexColor(MUTED)
    lp.yValueAxis.labels.fontSize = 7
    lp.yValueAxis.labels.fillColor = HexColor(MUTED)
    lp.yValueAxis.strokeColor = HexColor(GRID)
    lp.xValueAxis.strokeColor = HexColor(GRID)
    lp.yValueAxis.gridStrokeColor = HexColor(GRID)
    lp.yValueAxis.gridStrokeWidth = 0.5
    d.add(lp)
    return d


def _table(header, rows):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors as rc

    data = [header] + rows
    t = Table(data, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 1), (-1, -1), "#374151"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def build_report(user, units, days):
    from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate,
                                    Spacer)

    now = timezone.now()
    since = now - timedelta(days=days) if days else None
    period = f"last {days} days" if days else "all time"
    st = _styles()

    story = [
        Paragraph("Hälsa", st["h1"]),
        Paragraph(
            f"Health report for {user.username} &nbsp;·&nbsp; {period} "
            f"&nbsp;·&nbsp; generated {now:%d.%m.%Y %H:%M}",
            st["sub"],
        ),
    ]

    def window(qs, field):
        if since:
            qs = qs.filter(**{f"{field}__gte": since})
        return qs

    # --- glucose ---
    g = list(window(GlucoseReading.objects.filter(user=user), "taken_at")
             .order_by("taken_at"))
    g_all = GlucoseReading.objects.filter(user=user)
    story.append(Paragraph(f"Glucose ({U.glucose_unit_label(units)})", st["h2"]))
    if g:
        vals = [float(r.value_mmol) for r in g]
        avg = sum(vals) / len(vals)
        d, _ = U.glucose_display(avg, units)
        lo, _ = U.glucose_display(min(vals), units)
        hi, _ = U.glucose_display(max(vals), units)
        story.append(Paragraph(
            f"{len(g)} readings &nbsp;·&nbsp; average {d} &nbsp;·&nbsp; "
            f"range {lo}&ndash;{hi}", st["body"]))
        for i in trends.glucose_insights(g_all[:400], units):
            story.append(Paragraph(f"&bull; {i['text']}", st["ins"]))
        chart = _chart([(r.taken_at, float(r.value_mmol)) for r in g],
                       COLORS["glucose"])
        if chart:
            story.append(Spacer(1, 6))
            story.append(chart)
        rows = []
        for r in g[-MAX_TABLE_ROWS:]:
            v, _ = U.glucose_display(r.value_mmol, units)
            rows.append([f"{timezone.localtime(r.taken_at):%d.%m.%Y %H:%M}",
                         str(v),
                         GLUCOSE_CONTEXT_LATIN.get(r.context, "")])
        story.append(Spacer(1, 8))
        note = "" if len(g) <= MAX_TABLE_ROWS else \
            f" (showing most recent {MAX_TABLE_ROWS})"
        story.append(Paragraph(f"Readings{note}", st["small"]))
        story.append(_table(["When", U.glucose_unit_label(units),
                             "Context"], rows))
    else:
        story.append(Paragraph("No readings in this period.", st["body"]))

    # --- weight ---
    w = list(window(WeightReading.objects.filter(user=user), "date")
             .order_by("date"))
    w_all = WeightReading.objects.filter(user=user)
    story.append(Paragraph(f"Weight ({U.weight_unit_label(units)})", st["h2"]))
    if w:
        vals = [float(r.value_kg) for r in w]
        avg = sum(vals) / len(vals)
        d, _ = U.weight_display(avg, units)
        lo, _ = U.weight_display(min(vals), units)
        hi, _ = U.weight_display(max(vals), units)
        story.append(Paragraph(
            f"{len(w)} readings &nbsp;·&nbsp; average {d} &nbsp;·&nbsp; "
            f"range {lo}&ndash;{hi}", st["body"]))
        for i in trends.weight_insights(w_all[:400], units):
            story.append(Paragraph(f"&bull; {i['text']}", st["ins"]))
        chart = _chart([(timezone.datetime.combine(
            r.date, timezone.datetime.min.time()), float(r.value_kg)) for r in w],
            COLORS["weight"])
        if chart:
            story.append(Spacer(1, 6))
            story.append(chart)
        rows = []
        for r in w[-MAX_TABLE_ROWS:]:
            v, _ = U.weight_display(r.value_kg, units)
            rows.append([f"{r.date:%d.%m.%Y}", str(v)])
        story.append(Spacer(1, 8))
        story.append(_table(["Date", U.weight_unit_label(units)], rows))
    else:
        story.append(Paragraph("No readings in this period.", st["body"]))

    # --- blood pressure ---
    b = list(window(BloodPressureReading.objects.filter(user=user), "taken_at")
             .order_by("taken_at"))
    b_all = BloodPressureReading.objects.filter(user=user)
    story.append(Paragraph("Blood pressure (mmHg)", st["h2"]))
    if b:
        s_avg = sum(r.systolic for r in b) / len(b)
        d_avg = sum(r.diastolic for r in b) / len(b)
        story.append(Paragraph(
            f"{len(b)} readings &nbsp;·&nbsp; average {s_avg:.0f}/{d_avg:.0f}",
            st["body"]))
        for i in trends.bp_insights(b_all[:400], units):
            story.append(Paragraph(f"&bull; {i['text']}", st["ins"]))
        chart = _dual_chart(b)
        if chart:
            story.append(Spacer(1, 6))
            story.append(chart)
            story.append(Paragraph(
                f'<font color="{COLORS["bp"]}">&#9473;</font> systolic &nbsp; '
                f'<font color="{COLORS["bp2"]}">&#9473;</font> diastolic',
                st["small"]))
        rows = []
        for r in b[-MAX_TABLE_ROWS:]:
            rows.append([f"{timezone.localtime(r.taken_at):%d.%m.%Y %H:%M}",
                         f"{r.systolic}/{r.diastolic}",
                         str(r.pulse or "")])
        story.append(Spacer(1, 8))
        story.append(_table(["When", "mmHg", "Pulse"], rows))
    else:
        story.append(Paragraph("No readings in this period.", st["body"]))

    story.append(Spacer(1, 18))
    story.append(Paragraph(
        "Generated by Hälsa. Self-reported data, not a medical diagnosis.",
        st["small"]))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=f"Hälsa health report {period}", author="Hälsa",
    )
    doc.build(story)
    return buf.getvalue()
