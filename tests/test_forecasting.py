import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.currency_normalisation import normalise_to_reporting_currency
from analytics.forecasting import forecast_all_horizons, forecast_cash_flow


def _steady_df(days=60, daily_income=100.0, daily_expense=60.0):
    rows = []
    base = pd.Timestamp("2025-01-01")
    for d in range(days):
        date = (base + pd.Timedelta(days=d)).date().isoformat()
        rows.append(dict(transaction_id=f"IN{d}", date=date, description="Sale", customer="A", supplier="",
                          transaction_type="income", category="Sales - Retail", amount=daily_income,
                          currency="USD", vat_status="standard"))
        rows.append(dict(transaction_id=f"EX{d}", date=date, description="Expense", customer="", supplier="Supp",
                          transaction_type="expense", category="Operating Expenses", amount=daily_expense,
                          currency="USD", vat_status="standard"))
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return normalise_to_reporting_currency(df, "USD").df


class TestForecasting(unittest.TestCase):
    def test_all_horizons_present(self):
        df = _steady_df()
        forecasts = forecast_all_horizons(df)
        self.assertEqual(set(forecasts.keys()), {7, 14, 30, 60, 90})

    def test_positive_net_flow_trends_healthy(self):
        df = _steady_df(daily_income=200, daily_expense=50)
        f = forecast_cash_flow(df, 30)
        self.assertGreater(f.expected_closing_balance, f.starting_balance)

    def test_empty_data_does_not_crash(self):
        empty = pd.DataFrame(columns=[
            "transaction_id", "date", "description", "transaction_type",
            "category", "amount", "currency", "customer", "supplier",
        ])
        empty["date"] = pd.to_datetime(empty["date"])
        norm = normalise_to_reporting_currency(empty, "USD")
        f = forecast_cash_flow(norm.df, 30)
        self.assertEqual(f.expected_closing_balance, 0)


if __name__ == "__main__":
    unittest.main()
