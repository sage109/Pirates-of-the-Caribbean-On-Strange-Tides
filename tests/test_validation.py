import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.validation import validate_transactions


class TestValidation(unittest.TestCase):
    def test_missing_required_column(self):
        df = pd.DataFrame([{"transaction_id": "T1", "date": "2025-01-01"}])  # missing amount, currency, etc.
        result = validate_transactions(df)
        self.assertTrue(result.errors)
        self.assertEqual(result.valid_count, 0)

    def test_duplicate_transaction_ids_flagged(self):
        rows = [
            dict(transaction_id="T1", date="2025-01-01", description="Sale", transaction_type="income",
                 amount=100, currency="USD"),
            dict(transaction_id="T1", date="2025-01-02", description="Sale 2", transaction_type="income",
                 amount=200, currency="USD"),
        ]
        result = validate_transactions(pd.DataFrame(rows))
        self.assertEqual(result.duplicate_ids, ["T1"])
        self.assertEqual(result.valid_count, 0)  # both copies excluded as invalid

    def test_invalid_date_excluded(self):
        rows = [
            dict(transaction_id="T1", date="not-a-date", description="Sale", transaction_type="income",
                 amount=100, currency="USD"),
        ]
        result = validate_transactions(pd.DataFrame(rows))
        self.assertEqual(result.valid_count, 0)
        self.assertIn("invalid date", result.invalid_rows.iloc[0]["validation_notes"])

    def test_zero_and_negative_amount(self):
        rows = [
            dict(transaction_id="T1", date="2025-01-01", description="Sale", transaction_type="income",
                 amount=0, currency="USD"),
            dict(transaction_id="T2", date="2025-01-02", description="Sale", transaction_type="income",
                 amount=-50, currency="USD"),
        ]
        result = validate_transactions(pd.DataFrame(rows))
        self.assertEqual(result.valid_count, 1)  # negative amount is valid (a reversal); zero is not
        self.assertIn("T1", result.invalid_rows["transaction_id"].tolist())

    def test_unknown_currency_is_warning_not_hard_fail(self):
        rows = [
            dict(transaction_id="T1", date="2025-01-01", description="Sale", transaction_type="income",
                 amount=100, currency="XXX"),
        ]
        result = validate_transactions(pd.DataFrame(rows))
        self.assertEqual(result.valid_count, 1)
        self.assertIn("T1", result.unknown_currencies)

    def test_missing_vat_status_counted(self):
        rows = [
            dict(transaction_id="T1", date="2025-01-01", description="Sale", transaction_type="income",
                 amount=100, currency="USD", vat_status=""),
        ]
        result = validate_transactions(pd.DataFrame(rows))
        self.assertEqual(result.missing_vat_status_count, 1)

    def test_empty_dataset(self):
        df = pd.DataFrame(columns=["transaction_id", "date", "description", "transaction_type", "amount", "currency"])
        result = validate_transactions(df)
        self.assertEqual(result.total_rows, 0)
        self.assertEqual(result.valid_count, 0)


if __name__ == "__main__":
    unittest.main()
