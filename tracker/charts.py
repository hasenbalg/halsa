"""Server-rendered SVG charts. Zero JavaScript.

Colors reference CSS custom properties (var(--...)) so the charts follow
light/dark mode automatically.
"""

import uuid as _uuid
from datetime import datetime, timedelta
from html import escape

from django.utils.safestring import SafeString, mark_safe

FONT = "font-size:11px;fill:var(--muted);font-family:var(--font)"


def _x(dt):
    if isinstance(dt, datetime):
        return dt.timestamp()
    # date objects -> midnight timestamp
    return datetime(dt.year, dt.month, dt.day).timestamp()


def _fmt_date(ts, span_days):
    dt = datetime.fromtimestamp(ts)
    if span_days <= 2:
        return dt.strftime("%H:%M")
    if span_days <= 70:
        return dt.strftime("%d.%m.")
    return dt.strftime("%b %y")


def _ticks(lo, hi, count=4):
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / count
    # nice step: 1/2/5 * 10^n
    import math

    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw / mag <= m:
            step = m * mag
            break
    else:
        step = 10 * mag
    start = math.ceil(lo / step) * step
    out = []
    v = start
    while v <= hi + step * 0.001:
        out.append(v)
        v += step
    return out


def _fmt_val(v, decimals):
    return f"{v:.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{v:.0f}"


def line_chart(
    series,
    *,
    width=760,
    height=240,
    band=None,
    y_decimals=1,
    show_x=True,
    dots=True,
    aria_label="",
):
    """series: list of dicts:
        points: [(datetime|date, number)], color: 'var(--x)', label, fill, dashed
       band: (lo, hi) target band drawn as a soft green zone.
    Returns inline <svg> Markup, or an empty-state div.
    """
    series = [s for s in series if s.get("points")]
    if not series:
        return mark_safe('<div class="chart-empty">No data yet</div>')

    pad_l, pad_r, pad_t, pad_b = 46, 14, 14, (26 if show_x else 12)
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    all_vals = [p[1] for s in series for p in s["points"]]
    if band:
        all_vals += [band[0], band[1]]
    lo, hi = min(all_vals), max(all_vals)
    if hi == lo:
        hi, lo = hi + 1, max(lo - 1, 0)
    margin = (hi - lo) * 0.08
    lo, hi = lo - margin, hi + margin

    xs = [_x(p[0]) for s in series for p in s["points"]]
    x_lo, x_hi = min(xs), max(xs)
    if x_hi == x_lo:
        x_lo, x_hi = x_lo - 43200, x_hi + 43200  # +/- 12h around a single point
    span_days = (x_hi - x_lo) / 86400

    def px(ts):
        return pad_l + (ts - x_lo) / (x_hi - x_lo) * plot_w

    def py(v):
        return pad_t + (hi - v) / (hi - lo) * plot_h

    gid = _uuid.uuid4().hex[:8]
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" '
        f'aria-label="{escape(aria_label)}" preserveAspectRatio="none">'
    ]

    # horizontal grid + y labels
    for t in _ticks(lo, hi, 4):
        y = py(t)
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="var(--grid)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{pad_l - 8}" y="{y + 4:.1f}" text-anchor="end" style="{FONT}">'
            f"{_fmt_val(t, y_decimals)}</text>"
        )

    # target band
    if band:
        y1, y2 = py(min(band[1], hi)), py(max(band[0], lo))
        parts.append(
            f'<rect x="{pad_l}" y="{y1:.1f}" width="{plot_w}" height="{max(y2 - y1, 0):.1f}" '
            f'fill="var(--good)" opacity="0.09"/>'
        )

    # vertical grid + x labels
    if show_x:
        n = 4 if span_days > 2 else 3
        for i in range(n + 1):
            ts = x_lo + (x_hi - x_lo) * i / n
            x = px(ts)
            parts.append(
                f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + plot_h}" '
                f'stroke="var(--grid)" stroke-width="1"/>'
            )
            parts.append(
                f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" style="{FONT}">'
                f"{_fmt_date(ts, span_days)}</text>"
            )

    for s in series:
        pts = sorted(s["points"], key=lambda p: _x(p[0]))
        coords = " ".join(f"{px(_x(p[0])):.1f},{py(p[1]):.1f}" for p in pts)
        color = s.get("color", "var(--accent)")
        if s.get("fill", True) and len(pts) > 1:
            parts.append(
                f'<defs><linearGradient id="g{gid}" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0%" stop-color="{color}" stop-opacity="0.22"/>'
                f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
            )
            first, last = pts[0], pts[-1]
            parts.append(
                f'<path d="M {px(_x(first[0])):.1f},{py(first[1]):.1f} '
                f'L {coords.replace(" ", " L ", 1)} '
                f'L {px(_x(last[0])):.1f},{pad_t + plot_h:.1f} '
                f'L {px(_x(first[0])):.1f},{pad_t + plot_h:.1f} Z" '
                f'fill="url(#g{gid})" stroke="none"/>'
            )
        dash = ' stroke-dasharray="5 4"' if s.get("dashed") else ""
        width_attr = 'stroke-width="1.6"' if s.get("dashed") else 'stroke-width="2"'
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{color}" '
            f'{width_attr} stroke-linejoin="round" stroke-linecap="round"{dash}/>'
        )
        if dots and len(pts) <= 45 and not s.get("dashed"):
            for p in pts:
                parts.append(
                    f'<circle cx="{px(_x(p[0])):.1f}" cy="{py(p[1]):.1f}" r="2.6" '
                    f'fill="var(--card)" stroke="{color}" stroke-width="1.6"/>'
                )

    parts.append("</svg>")
    return mark_safe("".join(parts))


def sparkline(points, *, color="var(--accent)", width=280, height=64):
    return line_chart(
        [{"points": points, "color": color}],
        width=width,
        height=height,
        show_x=False,
        dots=False,
        y_decimals=1,
    )
