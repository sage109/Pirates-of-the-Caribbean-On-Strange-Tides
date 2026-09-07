"""
ui/components.py

Small, dependency-free HTML/SVG components for app.py. No plotly/matplotlib
required (neither is guaranteed installed) -- everything here is inline
SVG or CSS, returned as a string for `st.markdown(..., unsafe_allow_html=True)`.

Kept deliberately last (Section 0A.3: cosmetic work goes last, after every
functional item), and deliberately pure string-building so it can be
snapshot-tested without a running Streamlit process.
"""

from __future__ import annotations

import html
import math

WATERMARK_CSS = """
<style>
.nyasha-watermark {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    display: flex; align-items: center; justify-content: center;
    pointer-events: none;
    z-index: 0;
    opacity: 0.045;
}
.nyasha-watermark span {
    font-size: 11vw;
    font-weight: 800;
    letter-spacing: 0.05em;
    color: #0b1f3a;
    transform: rotate(-18deg);
    white-space: nowrap;
}
/* Keep normal Streamlit content above the watermark layer */
section.main > div { position: relative; z-index: 1; }
</style>
"""


def nyasha_watermark_html() -> str:
    """Section 31: full-page NYASHA watermark. Cosmetic only -- an
    extremely low-opacity, fixed, click-through layer so it never
    interferes with reading the dashboard or clicking controls."""
    return WATERMARK_CSS + '<div class="nyasha-watermark"><span>NYASHA AI</span></div>'


_RATING_COLORS = {
    "POOR": "#b3261e",
    "WEAK": "#c9622a",
    "MODERATE": "#c9a227",
    "GOOD": "#3f7d3f",
    "EXCELLENT": "#1f6f4a",
}


def health_score_gauge_svg(score: float, rating: str, width: int = 260, height: int = 160) -> str:
    """
    A simple 0-100 semicircular gauge as raw SVG -- no charting library
    needed. `score` should be 0-100 (matches FinancialHealthScore.total_score).
    """
    score = max(0.0, min(100.0, float(score)))
    color = _RATING_COLORS.get(rating, "#0b1f3a")

    cx, cy, r = width / 2, height - 20, min(width, height * 2) / 2 - 20
    start_angle, end_angle = 180.0, 0.0  # semicircle, left to right
    angle = math.radians(start_angle + (end_angle - start_angle) * (score / 100.0))

    def point(deg: float) -> tuple[float, float]:
        rad = math.radians(deg)
        return cx + r * math.cos(rad), cy - r * math.sin(rad)

    x0, y0 = point(start_angle)
    x1, y1 = point(start_angle + (end_angle - start_angle) * (score / 100.0))
    large_arc = 1 if (score / 100.0) > 0.5 else 0
    needle_x, needle_y = point(start_angle + (end_angle - start_angle) * (score / 100.0))

    track_x0, track_y0 = point(start_angle)
    track_x1, track_y1 = point(end_angle)

    return f"""
<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Financial health score {score} out of 100, rating {html.escape(rating)}">
  <path d="M {track_x0:.1f} {track_y0:.1f} A {r:.1f} {r:.1f} 0 1 1 {track_x1:.1f} {track_y1:.1f}"
        fill="none" stroke="#e3ddc6" stroke-width="16" stroke-linecap="round" />
  <path d="M {x0:.1f} {y0:.1f} A {r:.1f} {r:.1f} 0 {large_arc} 1 {x1:.1f} {y1:.1f}"
        fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" />
  <circle cx="{needle_x:.1f}" cy="{needle_y:.1f}" r="7" fill="{color}" stroke="white" stroke-width="2" />
  <text x="{cx}" y="{cy - r / 2}" text-anchor="middle" font-size="28" font-weight="700" fill="#0b1f3a">{score:.0f}</text>
  <text x="{cx}" y="{cy - r / 2 + 20}" text-anchor="middle" font-size="12" fill="#666">/ 100</text>
  <text x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="14" font-weight="600" fill="{color}">{html.escape(rating)}</text>
</svg>
"""


def demo_mode_banner_html() -> str:
    return (
        '<div style="background:#fdf6e3;border:1px solid #e3ddc6;border-radius:8px;'
        'padding:0.6rem 1rem;margin-bottom:1rem;font-size:0.9rem;">'
        "🎬 <b>Demo Mode</b> -- walking through the Moyo Retail &amp; Services dataset "
        "with guided commentary. Turn this off in the sidebar to explore freely."
        "</div>"
    )
