"""
tests/test_financials.py

Run with: python3 -m unittest discover -s tests -v
(pytest not available in this sandbox -- swap to pytest freely in a
networked environment; these tests use only stdlib unittest + assertions
so they run either way.)
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.currency_normalisation import normalise_to_reporting_currency
from analytics.financial_metrics import (
    liquidity_summary, profitability_summary, total_expenses, total_revenue,
)


def _sample_df():
    return pd.DataFrame([
        dict(transaction_id="T1", date="2025-01-05", description="Sale", account="", customer="A", supplier="",
             transaction_type="income", category="Sales - Retail", amount=1000.0, currency="USD",
             payment_method="Cash", invoice_number="", vat_status="standard"),
        dict(transaction_id="T2", date="2025-01-10", description="Rent", account="", customer="", supplier="Landlord",
             transaction_type="expense", category="Rent", amount=300.0, currency="USD",
             payment_method="Bank Transfer", invoice_number="", vat_status="standard"),
        dict(transaction_id="T3", date="2025-02-05", description="Sale", account="", customer="B", supplier="",
             transaction_type="income", category="Sales - Retail", amount=500.0, currency="USD",
             payment_method="Cash", invoice_number="", vat_status="zero_rated"),
        dict(transaction_id="T4", date="2025-02-10", description="Supplier payment", account="", customer="", supplier="Supp1",
             transaction_type="expense", category="Supplier Payments", amount=200.0, currency="USD",
             payment_method="Bank Transfer", invoice_number="", vat_status="standard"),
    ])


class TestFinancialMetrics(unittest.TestCase):
    def setUp(self):
        df = _sample_df()
        df["date"] = pd.to_datetime(df["date"])
        norm = normalise_to_reporting_currency(df, "USD")
        self.df = norm.df

    def test_total_revenue(self):
        self.assertEqual(total_revenue(self.df), 1500.0)

    def test_total_expenses(self):
        self.assertEqual(total_expenses(self.df), 500.0)

    def test_profitability_summary(self):
        p = profitability_summary(self.df)
        self.assertEqual(p.revenue, 1500.0)
        self.assertEqual(p.expenses, 500.0)
        self.assertEqual(p.net_profit, 1000.0)
        self.assertAlmostEqual(p.net_margin_pct, 66.67, places=1)

    def test_liquidity_summary(self):
        liq = liquidity_summary(self.df)
        self.assertEqual(liq.cash_inflows, 1500.0)
        self.assertEqual(liq.cash_outflows, 500.0)
        self.assertEqual(liq.net_cash_flow, 1000.0)

    def test_zero_revenue_no_divide_by_zero(self):
        df = _sample_df()
        df = df[df["transaction_type"] == "expense"].copy()  # no income rows at all
        df["date"] = pd.to_datetime(df["date"])
        norm = normalise_to_reporting_currency(df, "USD")
        p = profitability_summary(norm.df)
        self.assertEqual(p.revenue, 0.0)
        self.assertIsNone(p.net_margin_pct)  # must not raise ZeroDivisionError


class TestEdgeCases(unittest.TestCase):
    def test_empty_dataframe(self):
        empty = pd.DataFrame(columns=[
            "transaction_id", "date", "description", "transaction_type",
            "category", "amount", "currency", "customer", "supplier",
        ])
        empty["date"] = pd.to_datetime(empty["date"])
        norm = normalise_to_reporting_currency(empty, "USD")
        self.assertEqual(total_revenue(norm.df), 0.0)
        self.assertEqual(total_expenses(norm.df), 0.0)

    def test_negative_amount_does_not_crash_totals(self):
        df = _sample_df()
        df.loc[df["transaction_id"] == "T1", "amount"] = -1000.0
        df["date"] = pd.to_datetime(df["date"])
        norm = normalise_to_reporting_currency(df, "USD")
        # should compute without raising, even if the figure is unusual
        total_revenue(norm.df)


if __name__ == "__main__":
    unittest.main()
