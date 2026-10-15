"""
ui/charts.py

Dependency-free SVG chart + plain-language insight for the Cash Flow Forecast
page. Same approach as the health-score gauge in ui/components.py: pure string
building (no plotly/matplotlib needed, so it is unit-testable and renders the
same everywhere), returned for `st.markdown(..., unsafe_allow_html=True)`.

Rules the SVG follows so Streamlit's markdown renderer never mangles it:
  * no blank lines anywhere (a blank line ends a markdown HTML block),
  * no "$" characters (Streamlit would treat text between two "$" as LaTeX) --
    amounts are always written with the currency *code*, e.g. "USD 40,829",
  * every piece of text that came from outside is HTML-escaped.

Like the rest of the app, every number here is computed in Python from the
forecast; the insight sentence is built from templates, never by an LLM.
"""

from __future__ import annotations

import hashlib
import html
import math
from dataclasses import dataclass

NAVY = "#0b1f3a"
BLUE = "#1b4079"
GRID = "#e8e4d4"
MUTED = "#6b7280"
RED = "#b3261e"
STATUS_COLORS = {"healthy": "#3f7d3f", "watch": "#c9a227", "shortage": RED}


@dataclass(frozen=True)
class ForecastPoint:
    day: int                      # 0 = today
    balance: float
    status: str | None = None     # "healthy" | "watch" | "shortage"; None for today


@dataclass(frozen=True)
class ForecastInsight:
    headline: str                 # one or two plain-language sentences
    runway_days: float | None     # days until the balance reaches zero, if it does within the forecast
    level: str                    # "ok" | "watch" | "risk" -- how loudly the page should say it


# --------------------------------------------------------------------------- helpers
def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """Round-number axis ticks that cover [lo, hi] (first tick <= lo, last >= hi)."""
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if span <= 0:
        span = abs(hi) or 1.0
        lo, hi = lo - span / 2, hi + span / 2
        span = hi - lo
    raw_step = span / max(target, 1)
    magnitude = 10 ** math.floor(math.log10(raw_step))
    residual = raw_step / magnitude
    nice = 1 if residual <= 1.5 else 2 if residual <= 3 else 5 if residual <= 7 else 10
    step = nice * magnitude
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step
    count = int(round((end - start) / step))
    return [round(start + i * step, 10) for i in range(count + 1)]


def days_until_zero(points: list[ForecastPoint]) -> float | None:
    """Day at which the (straight-line) balance first drops below zero, by linear
    interpolation between points. None if it never does, or if it starts below zero."""
    pts = sorted(points, key=lambda p: p.day)
    if not pts or pts[0].balance < 0:
        return None
    for a, b in zip(pts, pts[1:]):
        if a.balance >= 0 > b.balance:
            return a.day + (b.day - a.day) * a.balance / (a.balance - b.balance)
    return None


def _money(currency: str, value: float) -> str:
    return f"{currency} {value:,.0f}"


def outlook_status(points: list[ForecastPoint]) -> str:
    """Cash status at the end of the forecast -- where the balance is heading."""
    last = max(points, key=lambda p: p.day)
    return last.status if last.status in STATUS_COLORS else "healthy"


# --------------------------------------------------------------------------- insight
def forecast_insight(points: list[ForecastPoint], currency: str) -> ForecastInsight:
    """What the forecast means, in a sentence or two. Deterministic templates."""
    pts = sorted(points, key=lambda p: p.day)
    if len(pts) < 2 or pts[-1].day <= pts[0].day:
        return ForecastInsight("Not enough data to project your cash balance yet.", None, "watch")

    start, end = pts[0].balance, pts[-1].balance
    span = pts[-1].day - pts[0].day
    daily = (end - start) / span
    runway = days_until_zero(pts)
    level = {"healthy": "ok", "watch": "watch", "shortage": "risk"}[outlook_status(pts)]
    if start < 0 or end < 0:
        level = "risk"
    flat = abs(end - start) < 0.005 * max(abs(start), 1.0)

    if start < 0:
        trend = "improving" if daily > 0 else "getting worse"
        text = (
            f"Your cash balance is already negative ({_money(currency, start)}). At the current pace it "
            f"would be {_money(currency, end)} in {span} days, {trend} by about "
            f"{_money(currency, abs(daily))} a day."
        )
    elif runway is not None:
        text = (
            f"At the current pace your cash runs out in about {max(1, round(runway))} days: the balance falls "
            f"from {_money(currency, start)} today to {_money(currency, end)} in {span} days "
            f"(about {_money(currency, abs(daily))} less each day)."
        )
    elif flat:
        text = f"Your cash balance is projected to stay roughly flat at about {_money(currency, start)} over the next {span} days."
    else:
        pct = (end - start) / abs(start) * 100 if start else 0.0
        if daily < 0:
            lasts = start / abs(daily)
            lasts_text = "more than a year" if lasts >= 365 else f"about {round(lasts)} days"
            text = (
                f"At the current pace your cash balance falls from {_money(currency, start)} today to "
                f"{_money(currency, end)} in {span} days ({pct:+.0f}%), about {_money(currency, abs(daily))} "
                f"less each day. At that rate it would last {lasts_text}."
            )
        else:
            text = (
                f"At the current pace your cash balance grows from {_money(currency, start)} today to "
                f"{_money(currency, end)} in {span} days ({pct:+.0f}%), about {_money(currency, daily)} more each day."
            )
    return ForecastInsight(text, runway, level)


# --------------------------------------------------------------------------- chart
def forecast_chart_svg(points: list[ForecastPoint], currency: str, width: int = 960, height: int = 400) -> str:
    """Projected cash balance as an SVG line + area chart. Returns "" if there
    are fewer than two points."""
    pts = sorted(points, key=lambda p: p.day)
    if len(pts) < 2 or pts[-1].day <= pts[0].day:
        return ""

    ml, mr, mt, mb = 72, 36, 58, 56
    plot_w, plot_h = width - ml - mr, height - mt - mb
    d0, d1 = pts[0].day, pts[-1].day

    values = [p.balance for p in pts]
    lo, hi = min(values + [0.0]), max(values + [0.0])
    pad = (hi - lo) * 0.12 or 1.0
    ticks = nice_ticks(lo - (pad if lo < 0 else 0.0), hi + pad)
    y_lo, y_hi = ticks[0], ticks[-1]

    def sx(day: float) -> float:
        return ml + (day - d0) / (d1 - d0) * plot_w

    def sy(value: float) -> float:
        return mt + (y_hi - value) / (y_hi - y_lo) * plot_h

    y0 = sy(0.0)
    bottom = mt + plot_h
    # Unique element ids per chart: two charts on one page must not share clip paths.
    uid = hashlib.md5(repr((width, height, currency, [(p.day, round(p.balance, 2)) for p in pts])).encode()).hexdigest()[:8]
    fill_id, above_id, below_id = f"nyFcFill{uid}", f"nyFcAbove{uid}", f"nyFcBelow{uid}"
    cur = html.escape(currency)
    xy = [(sx(p.day), sy(p.balance)) for p in pts]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    area = f"{ml:.1f},{y0:.1f} {line} {sx(d1):.1f},{y0:.1f}"

    out: list[str] = []
    add = out.append
    aria = (
        f"Projected cash balance in {cur}: {_money(cur, pts[0].balance)} today, "
        f"{_money(cur, pts[-1].balance)} after {d1} days."
    )
    add(f'<div class="nyasha-chart"><svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{aria}" preserveAspectRatio="xMidYMin meet" style="width:100%;height:auto;display:block;font-family:inherit">')
    add("<defs>"
        f'<linearGradient id="{fill_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{BLUE}" stop-opacity="0.28"/>'
        f'<stop offset="100%" stop-color="{BLUE}" stop-opacity="0.03"/></linearGradient>'
        f'<clipPath id="{above_id}"><rect x="{ml}" y="{mt}" width="{plot_w}" height="{max(y0 - mt, 0):.1f}"/></clipPath>'
        f'<clipPath id="{below_id}"><rect x="{ml}" y="{y0:.1f}" width="{plot_w}" height="{max(bottom - y0, 0):.1f}"/></clipPath>'
        "</defs>")

    # title + legend
    add(f'<text x="{ml}" y="26" font-size="16" font-weight="700" fill="{NAVY}">Projected cash balance ({cur})</text>')
    lx = width - mr
    for name in ("shortage", "watch", "healthy"):
        label = name.capitalize()
        lx -= 12 + len(label) * 7.4 + 14
        add(f'<circle cx="{lx:.1f}" cy="22" r="5" fill="#fff" stroke="{STATUS_COLORS[name]}" stroke-width="3"/>')
        add(f'<text x="{lx + 11:.1f}" y="26" font-size="12" fill="{MUTED}">{label}</text>')

    # grid + y tick labels
    for t in ticks:
        y = sy(t)
        add(f'<line x1="{ml}" x2="{ml + plot_w}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        add(f'<text x="{ml - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="{MUTED}">{t:,.0f}</text>')

    # area (blue above zero, red below), zero line, trend line
    add(f'<polygon points="{area}" fill="url(#{fill_id})" clip-path="url(#{above_id})"/>')
    add(f'<polygon points="{area}" fill="{RED}" fill-opacity="0.16" clip-path="url(#{below_id})"/>')
    add(f'<line x1="{ml}" x2="{ml + plot_w}" y1="{y0:.1f}" y2="{y0:.1f}" stroke="#9ca3af" stroke-width="1.5"/>')
    add(f'<polyline points="{line}" fill="none" stroke="{BLUE}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')

    # runway marker
    runway = days_until_zero(pts)
    if runway is not None:
        rx = sx(runway)
        anchor = "end" if rx > ml + plot_w * 0.7 else "start"
        tx = rx - 8 if anchor == "end" else rx + 8
        add(f'<line x1="{rx:.1f}" x2="{rx:.1f}" y1="{mt}" y2="{bottom}" stroke="{RED}" stroke-width="1.5" stroke-dasharray="5 4"/>')
        add(f'<text x="{tx:.1f}" y="{mt + 16}" text-anchor="{anchor}" font-size="13" font-weight="700" fill="{RED}">'
            f'Cash runs out in about {max(1, round(runway))} days</text>')

    # x axis
    for p in pts:
        x = sx(p.day)
        name = "Today" if p.day == d0 else f"Day {p.day}"
        add(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{bottom}" y2="{bottom + 5}" stroke="#9ca3af" stroke-width="1"/>')
        add(f'<text x="{x:.1f}" y="{bottom + 22}" text-anchor="middle" font-size="12" fill="{MUTED}">{name}</text>')
    add(f'<text x="{ml + plot_w / 2:.1f}" y="{height - 8}" text-anchor="middle" font-size="12" fill="{MUTED}">Days from today</text>')

    # markers + value labels
    prev_x, prev_below = None, False
    for i, (p, (x, y)) in enumerate(zip(pts, xy)):
        color = STATUS_COLORS.get(p.status or "", BLUE)
        status_note = f" ({html.escape(p.status)})" if p.status else ""
        add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6.5" fill="#fff" stroke="{color}" stroke-width="3">'
            f'<title>{"Today" if p.day == d0 else f"Day {p.day}"}: {_money(cur, p.balance)}{status_note}</title></circle>')
        # Labels sit above the marker; the first and last are anchored inward so they never clip.
        anchor = "start" if i == 0 else "end" if i == len(pts) - 1 else "middle"
        text_x = x - 4 if anchor == "start" else x + 4 if anchor == "end" else x
        # Neighbours closer than 80px would collide, so every other one is labelled below its marker.
        below = prev_x is not None and (x - prev_x) < 80 and not prev_below
        prev_x, prev_below = x, below
        label_y = y + 26 if below else y - 14
        add(f'<text x="{text_x:.1f}" y="{label_y:.1f}" text-anchor="{anchor}" font-size="13" font-weight="700" fill="{NAVY}" '
            f'stroke="#fff" stroke-width="4" paint-order="stroke">{p.balance:,.0f}</text>')

    add("</svg></div>")
    return "\n".join(out)


CHART_FRAME_HEIGHT = 440   # px; pass as `height=` to st.components.v1.html


def chart_page_html(svg: str) -> str:
    """Wrap a chart in a minimal standalone HTML page for st.components.v1.html.

    An iframe shows the SVG exactly as designed, whatever Streamlit's markdown
    renderer would have done to gradients, clip paths and inline styles. The SVG
    fills the frame's width and is scaled to fit its height (top-aligned)."""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><style>"
        "html,body{margin:0;padding:0;background:#ffffff;height:100%;"
        "font-family:'Source Sans Pro','Segoe UI',Arial,sans-serif;}"
        ".nyasha-chart{height:100vh;}"
        ".nyasha-chart svg{width:100% !important;height:100% !important;}"
        "</style></head><body>" + svg + "</body></html>"
    )
