"""
rules/vat_rules.py

Configurable VAT rules engine, per Section 11. Rates are stored here as
data, not hard-coded into calculation logic, so they can be updated
without touching business logic elsewhere (Zimbabwe's VAT rate has
changed over time -- do not assume today's rate stays fixed).

Sarudzo AI is a financial decision-support tool and does not replace
professional tax or accounting advice. This disclaimer must be shown
alongside any VAT output in the UI (Section 11).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# --- Configurable rates (edit here, not in calculation code) ---------------
VAT_RATES: dict[str, float] = {
    "standard": 0.155,      # Zimbabwe standard VAT rate -- raised from 15% to 15.5% effective
                             # 1 Jan 2026 (Finance Act 2025 / ZIMRA Public Notice 7 of 2026).
                             # Re-verify before relying on this if the rate changes again.
    "zero_rated": 0.0,
    "exempt": 0.0,
}
DISCLAIMER = (
    "Sarudzo AI is a financial decision-support tool and does not replace "
    "professional tax or accounting advice."
)


@dataclass
class VatSummary:
    output_vat: float          # VAT on sales (income)
    input_vat: float           # VAT on purchases (expenses)
    net_vat_payable: float     # output - input (positive = owed to authority)
    transactions_missing_vat_status: int
    transactions_flagged_for_review: list[str]


def _vat_rate_for(status: str) -> float:
    return VAT_RATES.get(str(status).strip().lower(), 0.0)


def calculate_vat_summary(df: pd.DataFrame, amount_col: str = "amount_reporting") -> VatSummary:
    work = df.copy()
    work["vat_status_clean"] = work["vat_status"].astype(str).str.strip().str.lower()
    missing_mask = ~work["vat_status_clean"].isin(VAT_RATES.keys())
    missing_count = int(missing_mask.sum())

    work["vat_rate"] = work["vat_status_clean"].apply(_vat_rate_for)
    # VAT-exclusive assumption: amount is the VAT-exclusive value; VAT = amount * rate.
    # (Flag in README if source data is VAT-inclusive -- rate calc would then be amount * rate/(1+rate).)
    work["vat_amount"] = work[amount_col] * work["vat_rate"]

    output_vat = round(work.loc[work["transaction_type"] == "income", "vat_amount"].sum(), 2)
    input_vat = round(work.loc[work["transaction_type"] == "expense", "vat_amount"].sum(), 2)
    net_vat_payable = round(output_vat - input_vat, 2)

    flagged = work.loc[missing_mask, "transaction_id"].astype(str).tolist()

    return VatSummary(
        output_vat=output_vat, input_vat=input_vat, net_vat_payable=net_vat_payable,
        transactions_missing_vat_status=missing_count,
        transactions_flagged_for_review=flagged,
    )


def vat_by_category(df: pd.DataFrame, amount_col: str = "amount_reporting") -> dict[str, float]:
    work = df.copy()
    work["vat_status_clean"] = work["vat_status"].astype(str).str.strip().str.lower()
    work["vat_rate"] = work["vat_status_clean"].apply(_vat_rate_for)
    work["vat_amount"] = work[amount_col] * work["vat_rate"]
    return work.groupby("category")["vat_amount"].sum().round(2).to_dict()
