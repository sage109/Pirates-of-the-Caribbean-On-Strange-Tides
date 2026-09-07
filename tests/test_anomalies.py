import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.anomaly_detection import check_rate_anomaly, detect_anomalies
from analytics.currency_normalisation import normalise_to_reporting_currency


def _build_df(n_normal=20, spike_amount=None):
    rows = []
    for i in range(n_normal):
        rows.append(dict(
            transaction_id=f"T{i}", date=f"2025-01-{(i % 28) + 1:02d}", description="Purchase",
            customer="", supplier="Supp", transaction_type="expense", category="Supplier Payments",
            amount=100.0 + (i % 5), currency="USD", vat_status="standard",
        ))
    if spike_amount is not None:
        rows.append(dict(
            transaction_id="SPIKE", date="2025-01-15", description="Large payment",
            customer="", supplier="Supp", transaction_type="expense", category="Supplier Payments",
            amount=spike_amount, currency="USD", vat_status="standard",
        ))
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return normalise_to_reporting_currency(df, "USD").df


class TestAnomalyDetection(unittest.TestCase):
    def test_spike_transaction_flagged_high(self):
        df = _build_df(n_normal=20, spike_amount=50000.0)
        findings = detect_anomalies(df)
        flagged_ids = {f.transaction_id: f for f in findings}
        self.assertIn("SPIKE", flagged_ids)
        self.assertEqual(flagged_ids["SPIKE"].risk_level, "HIGH")

    def test_too_little_data_returns_empty(self):
        df = _build_df(n_normal=5)
        findings = detect_anomalies(df)
        self.assertEqual(findings, [])

    def test_no_findings_never_labels_fraud(self):
        df = _build_df(n_normal=20, spike_amount=50000.0)
        findings = detect_anomalies(df)
        for f in findings:
            for r in f.reasons:
                self.assertNotIn("fraud", r.lower())
            self.assertNotIn("fraud", f.recommended_action.lower())

    def test_rate_anomaly_flags_out_of_range(self):
        finding = check_rate_anomaly(rate=999999, expected_range=(20000, 35000), currency="ZWL")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.risk_level, "HIGH")

    def test_rate_anomaly_none_when_in_range(self):
        finding = check_rate_anomaly(rate=26000, expected_range=(20000, 35000), currency="ZWL")
        self.assertIsNone(finding)


if __name__ == "__main__":
    unittest.main()
