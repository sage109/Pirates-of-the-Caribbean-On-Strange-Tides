"""
analytics/forecasting.py

Cash-flow forecasting per Section 9. Uses a simple, explainable moving-
average-of-daily-net-flow projection rather than a black-box model --
university evaluators and SME owners both need to understand *why* a
number was produced (Section 7/38: explainability & data lineage).

Forecast horizons: 7 / 14 / 30 / 60 / 90 days.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

STATUS_THRESHOLDS = {
    # closing balance vs. average monthly outflow -> status
    "healthy": 1.0,   # closing balance >= 1x avg monthly outflow -> healthy
    "watch": 0.25,     # >= 0.25x -> watch, else shortage
}


@dataclass
class ForecastResult:
    horizon_days: int
    starting_balance: float
    expected_inflows: float
    expected_outflows: float
    expected_closing_balance: float
    status: str              # "healthy" | "watch" | "shortage"
    status_emoji: str
    main_driver: str


def _daily_net_flow_series(df: pd.DataFrame, amount_col: str) -> pd.Series:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    signed = np.where(work["transaction_type"] == "income", work[amount_col], -work[amount_col])
    daily = pd.Series(signed, index=work["date"]).groupby(level=0).sum()
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    return daily.reindex(full_range, fill_value=0.0)


def forecast_cash_flow(
    df: pd.DataFrame,
    horizon_days: int,
    amount_col: str = "amount_reporting",
    lookback_days: int = 60,
) -> ForecastResult:
    work = df.dropna(subset=[amount_col]).copy()
    if work.empty:
        return ForecastResult(horizon_days, 0, 0, 0, 0, "watch", "🟡", "Insufficient data for a forecast.")

    daily_net = _daily_net_flow_series(work, amount_col)
    recent = daily_net.tail(lookback_days)

    avg_daily_net = float(recent.mean())
    avg_daily_inflow = float(recent.clip(lower=0).mean())
    avg_daily_outflow = float((-recent.clip(upper=0)).mean())

    starting_balance = round(float(daily_net.cumsum().iloc[-1]), 2)
    expected_inflows = round(avg_daily_inflow * horizon_days, 2)
    expected_outflows = round(avg_daily_outflow * horizon_days, 2)
    closing_balance = round(starting_balance + avg_daily_net * horizon_days, 2)

    monthly_outflow_estimate = avg_daily_outflow * 30 or 1.0
    ratio = closing_balance / monthly_outflow_estimate

    if ratio >= STATUS_THRESHOLDS["healthy"]:
        status, emoji = "healthy", "🟢"
    elif ratio >= STATUS_THRESHOLDS["watch"]:
        status, emoji = "watch", "🟡"
    else:
        status, emoji = "shortage", "🔴"

    if avg_daily_outflow > avg_daily_inflow:
        driver = "Expected outflows are running ahead of expected inflows based on recent activity."
    elif expected_inflows < abs(starting_balance) * 0.1 and starting_balance < 0:
        driver = "Cash position is starting from a deficit that recent inflows are not expected to close."
    else:
        driver = "Inflows and outflows are broadly balanced based on recent activity."

    return ForecastResult(
        horizon_days=horizon_days, starting_balance=starting_balance,
        expected_inflows=expected_inflows, expected_outflows=expected_outflows,
        expected_closing_balance=closing_balance, status=status, status_emoji=emoji,
        main_driver=driver,
    )


def forecast_all_horizons(df: pd.DataFrame, amount_col: str = "amount_reporting") -> dict[int, ForecastResult]:
    return {h: forecast_cash_flow(df, h, amount_col) for h in (7, 14, 30, 60, 90)}
