"""
analytics/customer_analysis.py

Customer payment-risk analysis per Section 10. Works from transaction-level
data only (no formal AR ageing subledger is assumed) -- payment "delay" is
proxied from the gap between consecutive invoices/receipts for a customer,
and outstanding receivables are proxied from 'Customer Receipts' category
activity. Document this proxy clearly in the report output (Section 38:
data lineage / explainability) so nobody mistakes it for a true AR ageing
report.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class CustomerRisk:
    customer: str
    avg_payment_gap_days: float | None
    total_receivable_activity: float
    payment_frequency: int          # number of receipt transactions
    avg_invoice_value: float
    concentration_pct: float        # % of total customer revenue this customer represents
    risk_level: str                  # LOW | MEDIUM | HIGH
    recommended_action: str


def _risk_from_signals(avg_gap: float | None, concentration_pct: float, frequency: int) -> str:
    score = 0
    if avg_gap is not None and avg_gap > 45:
        score += 2
    elif avg_gap is not None and avg_gap > 21:
        score += 1
    if concentration_pct > 30:
        score += 1
    if frequency <= 1:
        score += 1
    if score >= 3:
        return "HIGH"
    if score >= 1:
        return "MEDIUM"
    return "LOW"


def _action_for(level: str) -> str:
    return {
        "HIGH": "Escalate overdue account; review credit terms before extending further credit.",
        "MEDIUM": "Send a payment reminder and monitor this customer closely.",
        "LOW": "No action required; continue standard monitoring.",
    }[level]


def analyse_customer_risk(df: pd.DataFrame, amount_col: str = "amount_reporting") -> list[CustomerRisk]:
    income = df[(df["transaction_type"] == "income") & (df["customer"].astype(str).str.strip() != "")].copy()
    if income.empty:
        return []

    income["date"] = pd.to_datetime(income["date"])
    total_customer_revenue = income[amount_col].sum()

    results: list[CustomerRisk] = []
    for customer, group in income.groupby("customer"):
        group = group.sort_values("date")
        gaps = group["date"].diff().dt.days.dropna()
        avg_gap = round(float(gaps.mean()), 1) if not gaps.empty else None

        total_activity = round(float(group[amount_col].sum()), 2)
        frequency = int(len(group))
        avg_invoice = round(total_activity / frequency, 2) if frequency else 0.0
        concentration = round(total_activity / total_customer_revenue * 100, 2) if total_customer_revenue else 0.0

        level = _risk_from_signals(avg_gap, concentration, frequency)
        results.append(CustomerRisk(
            customer=customer, avg_payment_gap_days=avg_gap,
            total_receivable_activity=total_activity, payment_frequency=frequency,
            avg_invoice_value=avg_invoice, concentration_pct=concentration,
            risk_level=level, recommended_action=_action_for(level),
        ))

    results.sort(key=lambda r: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[r.risk_level])
    return results
