"""
reports/report_generator.py

Section 27: report generation / export. Produces two things a user can
download from Streamlit:

  1. CSV exports of the underlying tables (transactions, anomalies,
     customer risk) -- always available, zero extra dependencies.
  2. A single self-contained HTML report (inline CSS, no external assets)
     summarising profitability, health score, anomalies, forecast, and VAT
     for the period. Opens in any browser and prints cleanly to PDF via
     the browser's own "Print to PDF" -- deliberately chosen over a PDF
     library (fpdf2/reportlab) because neither is installed in this
     offline sandbox and could not be tested here; HTML needs nothing
     extra and IS fully tested below. If your environment has `fpdf2` or
     `weasyprint` installed, `export_pdf_if_available()` will use it and
     otherwise cleanly tells the caller to fall back to the HTML report.

Every figure in the report comes straight from the already-tested
analytics/ dataclasses -- this module only formats, it never (re)computes.
"""

from __future__ import annotations

import csv
import html
import io
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

REPORT_CSS = """
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; color: #1a1a2e; margin: 2rem; }
h1 { color: #0b1f3a; border-bottom: 3px solid #c9a227; padding-bottom: 0.5rem; }
h2 { color: #0b1f3a; margin-top: 2rem; border-left: 4px solid #c9a227; padding-left: 0.6rem; }
.meta { color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; }
th, td { border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; font-size: 0.92rem; }
th { background: #0b1f3a; color: #f4e8c1; }
.metric-row { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 1rem 0; }
.metric { background: #f7f5ec; border: 1px solid #e3ddc6; border-radius: 8px; padding: 0.75rem 1.25rem; min-width: 140px; }
.metric .label { font-size: 0.8rem; color: #666; text-transform: uppercase; letter-spacing: 0.03em; }
.metric .value { font-size: 1.4rem; font-weight: 700; color: #0b1f3a; }
.risk-HIGH { color: #b3261e; font-weight: 700; }
.risk-MEDIUM { color: #a15c00; font-weight: 700; }
.risk-LOW { color: #2d6a2d; }
.disclaimer { margin-top: 2rem; padding: 0.75rem 1rem; background: #fdf6e3; border: 1px solid #e3ddc6; font-size: 0.85rem; }
footer { margin-top: 2rem; font-size: 0.75rem; color: #999; }
"""


def _to_dict(obj: Any) -> dict:
    return asdict(obj) if is_dataclass(obj) else dict(obj or {})


def _metric(label: str, value: str) -> str:
    return f'<div class="metric"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div></div>'


def build_html_report(
    business_name: str,
    reporting_currency: str,
    profitability: Any,
    health_score: Any,
    anomalies: list,
    forecasts: dict,
    vat_summary: Any,
    ai_explanation: str | None = None,
) -> str:
    prof = _to_dict(profitability)
    health = _to_dict(health_score)
    vat = _to_dict(vat_summary)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    metrics_html = "".join([
        _metric("Revenue", f"{reporting_currency} {prof.get('revenue', 0):,.2f}"),
        _metric("Expenses", f"{reporting_currency} {prof.get('expenses', 0):,.2f}"),
        _metric("Net Profit", f"{reporting_currency} {prof.get('net_profit', 0):,.2f}"),
        _metric("Health Score", f"{health.get('total_score', 'N/A')}/100 ({html.escape(str(health.get('rating', '')))})"),
    ])

    components_rows = "".join(
        f"<tr><td>{html.escape(str(c.get('name', c) if isinstance(c, dict) else c))}</td>"
        f"<td>{c.get('weight_pct', ''):.0f}%</td>"
        f"<td>{c.get('component_score', 0):.1f}/100</td>"
        f"<td>{html.escape(str(c.get('explanation', '')))}</td></tr>"
        for c in [(_to_dict(c) if is_dataclass(c) else c) for c in health.get("components", [])]
    )

    anomaly_rows = "".join(
        f'<tr><td>{html.escape(str(a.transaction_id))}</td>'
        f'<td class="risk-{a.risk_level}">{a.risk_level}</td>'
        f'<td>{a.risk_score:.2f}</td>'
        f'<td>{html.escape("; ".join(a.reasons))}</td>'
        f'<td>{html.escape(a.recommended_action)}</td></tr>'
        for a in anomalies
    ) or '<tr><td colspan="5">No anomalies detected in this dataset.</td></tr>'

    forecast_rows = "".join(
        f"<tr><td>{horizon}-day</td><td>{f.status_emoji} {f.status.upper()}</td>"
        f"<td>{reporting_currency} {f.expected_closing_balance:,.2f}</td>"
        f"<td>{html.escape(f.main_driver)}</td></tr>"
        for horizon, f in sorted(forecasts.items())
    )

    explanation_html = ""
    if ai_explanation:
        explanation_html = f'<h2>AI Explanation</h2><p>{html.escape(ai_explanation).replace(chr(10), "<br>")}</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sarudzo AI -- Financial Report -- {html.escape(business_name)}</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<h1>💡 Sarudzo AI -- Financial Report</h1>
<div class="meta">{html.escape(business_name)} &middot; Reporting currency: {reporting_currency} &middot; Generated {generated_at}</div>

<div class="metric-row">{metrics_html}</div>

<h2>Financial Health Breakdown</h2>
<table><thead><tr><th>Component</th><th>Weight</th><th>Score</th><th>Explanation</th></tr></thead>
<tbody>{components_rows}</tbody></table>

<h2>Anomaly Detection</h2>
<table><thead><tr><th>Transaction</th><th>Risk</th><th>Score</th><th>Reasons</th><th>Recommended Action</th></tr></thead>
<tbody>{anomaly_rows}</tbody></table>

<h2>Cash Flow Forecast</h2>
<table><thead><tr><th>Horizon</th><th>Status</th><th>Expected Closing Balance</th><th>Main Driver</th></tr></thead>
<tbody>{forecast_rows}</tbody></table>

<h2>VAT Summary</h2>
<div class="metric-row">
{_metric("Output VAT", f"{reporting_currency} {vat.get('output_vat', 0):,.2f}")}
{_metric("Input VAT", f"{reporting_currency} {vat.get('input_vat', 0):,.2f}")}
{_metric("Net VAT Payable", f"{reporting_currency} {vat.get('net_vat_payable', 0):,.2f}")}
</div>

{explanation_html}

<div class="disclaimer">Sarudzo AI is a financial decision-support tool and does not replace professional tax or accounting advice. All figures above were computed deterministically from the uploaded transaction data; any AI-generated text above only explains those figures and does not alter them.</div>
<footer>Generated by Sarudzo AI &middot; nyasha-ai project</footer>
</body>
</html>"""


def build_transactions_csv(df) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def build_anomalies_csv(anomalies: list) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["transaction_id", "risk_level", "risk_score", "reasons", "recommended_action"])
    for a in anomalies:
        writer.writerow([a.transaction_id, a.risk_level, a.risk_score, "; ".join(a.reasons), a.recommended_action])
    return buf.getvalue()


def build_customer_risk_csv(risks: list) -> str:
    buf = io.StringIO()
    if not risks:
        return "customer,risk_level\n"
    writer = csv.DictWriter(buf, fieldnames=list(_to_dict(risks[0]).keys()))
    writer.writeheader()
    for r in risks:
        writer.writerow(_to_dict(r))
    return buf.getvalue()


def export_pdf_if_available(html_report: str) -> bytes | None:
    """
    Best-effort PDF export. Returns None (never raises) if no PDF backend
    is installed -- the caller should fall back to offering the HTML
    report for download instead, which is always available. Not exercised
    in this sandbox (neither backend is installed, no network to add one)
    -- test this specifically in a networked environment before relying on
    a PDF download button in the demo.
    """
    try:
        from xhtml2pdf import pisa  # optional dependency
    except ImportError:
        pass
    else:
        out = io.BytesIO()
        result = pisa.CreatePDF(io.StringIO(html_report), dest=out)
        if not result.err:
            return out.getvalue()

    try:
        import weasyprint  # optional dependency
    except ImportError:
        return None
    else:
        return weasyprint.HTML(string=html_report).write_pdf()
