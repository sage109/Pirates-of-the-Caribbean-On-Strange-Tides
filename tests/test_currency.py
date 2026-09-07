import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.currency_normalisation import normalise_to_reporting_currency
from services.exchange_rates import convert_currency, get_manual_rate, get_supported_currencies


class TestCurrencyConversion(unittest.TestCase):
    def test_same_currency_no_op(self):
        amount, rr = convert_currency(1000, "USD", "USD")
        self.assertEqual(amount, 1000)
        self.assertEqual(rr.rate, 1.0)

    def test_conversion_never_crashes_offline(self):
        # In this sandbox there is no network -- convert_currency must fall
        # back to a cached/manual rate rather than raising.
        amount, rr = convert_currency(1000, "USD", "ZAR")
        self.assertGreater(amount, 0)
        self.assertIn(rr.rate_type, ("live", "cached"))

    def test_manual_rate_labeled_manual_never_live(self):
        rr = get_manual_rate("USD", "ZWL", 30000)
        self.assertEqual(rr.rate_type, "manual")

    def test_unsupported_currency_raises(self):
        with self.assertRaises(ValueError):
            convert_currency(100, "USD", "NOTACURRENCY")

    def test_supported_currencies_include_required_set(self):
        supported = set(get_supported_currencies())
        required = {"USD", "ZWL", "ZAR", "GBP", "EUR", "BWP", "ZMW"}
        self.assertTrue(required.issubset(supported))

    def test_normalisation_preserves_original_amount_and_currency(self):
        df = pd.DataFrame([
            dict(transaction_id="T1", date="2025-01-01", description="Sale", customer="A", supplier="",
                 transaction_type="income", category="Sales - Retail", amount=1000.0, currency="ZAR",
                 vat_status="standard"),
        ])
        df["date"] = pd.to_datetime(df["date"])
        norm = normalise_to_reporting_currency(df, "USD")
        # original untouched
        self.assertEqual(norm.df.iloc[0]["amount"], 1000.0)
        self.assertEqual(norm.df.iloc[0]["currency"], "ZAR")
        # reporting column added and different (ZAR -> USD is not 1:1)
        self.assertIn("amount_reporting", norm.df.columns)
        self.assertNotEqual(norm.df.iloc[0]["amount_reporting"], 1000.0)

    def test_unknown_currency_produces_nan_not_silent_mix(self):
        df = pd.DataFrame([
            dict(transaction_id="T1", date="2025-01-01", description="Sale", customer="A", supplier="",
                 transaction_type="income", category="Sales - Retail", amount=1000.0, currency="XXX",
                 vat_status="standard"),
        ])
        df["date"] = pd.to_datetime(df["date"])
        norm = normalise_to_reporting_currency(df, "USD")
        self.assertTrue(pd.isna(norm.df.iloc[0]["amount_reporting"]))


if __name__ == "__main__":
    unittest.main()
