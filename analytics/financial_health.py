"""
analytics/financial_health.py

Transparent 0-100 financial health score, per Section 7. Weighting is
configurable data (HEALTH_SCORE_WEIGHTS), not buried in logic, and every
component score is returned alongside the total so the UI can always
answer "How was this score calculated?" (Section 7 -- never a black box).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analytics.financial_metrics import (
    liquidity_summary, profitability_summary, working_capital_summary,
)

HEALTH_SCORE_WEIGHTS = {
    "profitability": 0.25,
    "liquidity": 0.25,
    "cash_flow": 0.20,
    "receivables": 0.15,
    "expense_control": 0.15,
}


@dataclass
class HealthScoreComponent:
    name: str
    weight_pct: float
    raw_value: float | None       # the underlying metric (e.g. net margin %)
    component_score: float        # 0-100, already weighted contribution's basis
    explanation: str


@dataclass
class FinancialHealthScore:
    total_score: float            # 0-100
    rating: str                    # POOR | WEAK | MODERATE | GOOD | EXCELLENT
    components: list[HealthScoreComponent]


def _rating_for(score: float) -> str:
    if score >= 80:
        return "EXCELLENT"
    if score >= 65:
        return "GOOD"
    if score >= 45:
        return "MODERATE"
    if score >= 25:
        return "WEAK"
    return "POOR"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def calculate_financial_health(df: pd.DataFrame, amount_col: str = "amount_reporting") -> FinancialHealthScore:
    prof = profitability_summary(df, amount_col)
    liq = liquidity_summary(df, amount_col)
    wc = working_capital_summary(df, amount_col)

    # --- Profitability: scaled from net margin %, 0% margin -> 0, 30%+ -> 100
    net_margin = prof.net_margin_pct if prof.net_margin_pct is not None else 0.0
    profitability_score = _clamp(net_margin / 30 * 100)

    # --- Liquidity: current ratio, 1.0 -> 50, 2.0+ -> 100, below 1.0 scales down
    current_ratio = liq.current_ratio if liq.current_ratio is not None else 0.0
    liquidity_score = _clamp(current_ratio / 2.0 * 100)

    # --- Cash flow: net cash flow as % of revenue, 0% -> 0, 20%+ -> 100
    cash_flow_pct = (liq.net_cash_flow / prof.revenue * 100) if prof.revenue else 0.0
    cash_flow_score = _clamp(cash_flow_pct / 20 * 100)

    # --- Receivables: penalise a shrinking/negative trend, reward stable-to-growing
    rec_trend = wc.receivables_trend_pct if wc.receivables_trend_pct is not None else 0.0
    receivables_score = _clamp(50 + rec_trend)  # trend of 0% -> 50 (neutral), +50% -> 100, -50% -> 0

    # --- Expense control: penalise expenses growing faster than revenue
    from analytics.financial_metrics import expense_growth, revenue_growth
    exp_growth = expense_growth(df, amount_col) or 0.0
    rev_growth = revenue_growth(df, amount_col) or 0.0
    expense_control_score = _clamp(70 - (exp_growth - rev_growth))

    components = [
        HealthScoreComponent(
            "profitability", HEALTH_SCORE_WEIGHTS["profitability"] * 100, net_margin, profitability_score,
            f"Net profit margin of {net_margin:.1f}% -- scored against a 30% benchmark for a strong SME margin.",
        ),
        HealthScoreComponent(
            "liquidity", HEALTH_SCORE_WEIGHTS["liquidity"] * 100, current_ratio, liquidity_score,
            f"Current ratio of {current_ratio:.2f} -- a ratio of 2.0 or higher scores full marks.",
        ),
        HealthScoreComponent(
            "cash_flow", HEALTH_SCORE_WEIGHTS["cash_flow"] * 100, cash_flow_pct, cash_flow_score,
            f"Net cash flow is {cash_flow_pct:.1f}% of revenue -- 20% or higher scores full marks.",
        ),
        HealthScoreComponent(
            "receivables", HEALTH_SCORE_WEIGHTS["receivables"] * 100, rec_trend, receivables_score,
            f"Receivables activity trend of {rec_trend:+.1f}% over the period -- stable-to-growing scores well.",
        ),
        HealthScoreComponent(
            "expense_control", HEALTH_SCORE_WEIGHTS["expense_control"] * 100, exp_growth - rev_growth, expense_control_score,
            f"Expenses grew {exp_growth:.1f}% vs revenue growth of {rev_growth:.1f}% -- expenses outpacing revenue reduces this score.",
        ),
    ]

    total = sum(c.component_score * HEALTH_SCORE_WEIGHTS[c.name] for c in components)
    total = round(_clamp(total), 1)

    return FinancialHealthScore(total_score=total, rating=_rating_for(total), components=components)
