"""
analytics/currency_normalisation.py

Adds an 'amount_reporting' column to a validated transactions DataFrame by
converting every row's original-currency amount into the selected
reporting currency, per Section 12. The original 'amount' and 'currency'
columns are always preserved untouched -- Section 12 rule #1/#2.

Also returns the exact rate used per currency pair, for the audit trail
(Section 24) and the 'exchange rate used / date / source' display
requirement (Section 12 rule #4-6).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.exchange_rates import RateResult, get_live_rate


@dataclass
class NormalisationResult:
    df: pd.DataFrame                      # copy of input + 'amount_reporting' column
    reporting_currency: str
    rates_used: dict[str, RateResult]      # currency -> RateResult applied


def normalise_to_reporting_currency(df: pd.DataFrame, reporting_currency: str) -> NormalisationResult:
    reporting_currency = reporting_currency.upper()
    work = df.copy()
    currencies_present = sorted(work["currency"].astype(str).str.upper().unique())

    rates_used: dict[str, RateResult] = {}
    for cur in currencies_present:
        if cur == reporting_currency:
            continue
        try:
            rates_used[cur] = get_live_rate(cur, reporting_currency)
        except ValueError:
            # Unknown/unsupported currency code (e.g. a data-quality issue
            # like 'XXX') -- leave unconverted and flag via NaN so it's
            # visibly excluded from reporting-currency totals rather than
            # silently mis-converted. See Section 12 rule #8.
            rates_used[cur] = None  # type: ignore[assignment]

    def convert_row(row) -> float:
        cur = str(row["currency"]).upper()
        if cur == reporting_currency:
            return round(float(row["amount"]), 2)
        rr = rates_used.get(cur)
        if rr is None:
            return float("nan")
        return rr.convert(float(row["amount"]))

    work["amount_reporting"] = work.apply(convert_row, axis=1)
    return NormalisationResult(df=work, reporting_currency=reporting_currency, rates_used=rates_used)
