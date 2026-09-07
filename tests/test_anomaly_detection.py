import unittest

import numpy as np
import pandas as pd

from analytics.anomaly_detection import (
    _low_tier_score, _risk_level_from_score, check_rate_anomaly, detect_anomalies,
)
from analytics.currency_normalisation import normalise_to_reporting_currency


def _make_df(n_normal: int, category: str, base_amount: float, spread: float,
             extra_rows: list[dict] | None = None) -> pd.DataFrame:
    """Builds a normalised (amount_reporting-bearing) dataframe with n_normal
    "ordinary" transactions in one category, plus any extra rows appended."""
    rng = np.random.default_rng(42)
    rows = []
    for i in range(n_normal):
        rows.append(dict(
            transaction_id=f"N{i:04d}", date=pd.Timestamp("2025-01-01") + pd.Timedelta(days=i),
            description="Normal", customer="", supplier="Regular Supplier",
            transaction_type="expense", category=category,
            amount=round(base_amount + rng.normal(0, spread), 2), currency="USD",
            vat_status="standard",
        ))
    for j, extra in enumerate(extra_rows or []):
        row = dict(
            transaction_id=f"X{j:04d}", date=pd.Timestamp("2025-06-01"),
            description="Extra", customer="", supplier="Regular Supplier",
            transaction_type="expense", category=category, currency="USD",
            vat_status="standard",
        )
        row.update(extra)
        rows.append(row)
    df = pd.DataFrame(rows)
    return normalise_to_reporting_currency(df, "USD").df


class TestLowTierScoreFormula(unittest.TestCase):
    def test_band_endpoints(self):
        self.assertAlmostEqual(_low_tier_score(1.8), 0.1)
        self.assertAlmostEqual(_low_tier_score(2.0), 0.3)

    def test_midpoint(self):
        self.assertAlmostEqual(_low_tier_score(1.9), 0.2)

    def test_stays_within_low_band(self):
        for z in (1.8, 1.85, 1.9, 1.95, 2.0):
            score = _low_tier_score(z)
            self.assertEqual(_risk_level_from_score(score), "LOW")


class TestRiskLevelBands(unittest.TestCase):
    def test_high_band(self):
        self.assertEqual(_risk_level_from_score(0.75), "HIGH")
        self.assertEqual(_risk_level_from_score(1.0), "HIGH")

    def test_medium_band(self):
        self.assertEqual(_risk_level_from_score(0.5), "MEDIUM")
        self.assertEqual(_risk_level_from_score(0.74), "MEDIUM")

    def test_low_band(self):
        self.assertEqual(_risk_level_from_score(0.0), "LOW")
        self.assertEqual(_risk_level_from_score(0.49), "LOW")


class TestDetectAnomalies(unittest.TestCase):
    def test_empty_dataframe_returns_no_findings(self):
        empty = pd.DataFrame(columns=[
            "transaction_id", "date", "description", "customer", "supplier",
            "transaction_type", "category", "amount_reporting", "currency", "vat_status",
        ])
        self.assertEqual(detect_anomalies(empty), [])

    def test_small_dataset_returns_no_findings(self):
        # detect_anomalies requires >= 10 rows for a meaningful model
        df = _make_df(n_normal=5, category="Rent", base_amount=500, spread=10)
        self.assertEqual(detect_anomalies(df), [])

    def test_extreme_spike_is_flagged_high(self):
        df = _make_df(
            n_normal=30, category="Supplier Payments", base_amount=500, spread=15,
            extra_rows=[dict(amount=50000.00)],
        )
        findings = detect_anomalies(df)
        spike = [f for f in findings if f.transaction_id == "X0000"]
        self.assertEqual(len(spike), 1)
        self.assertEqual(spike[0].risk_level, "HIGH")
        self.assertGreaterEqual(spike[0].risk_score, 0.75)

    def test_mild_outlier_lands_in_low_band_not_flagged_as_medium_or_high(self):
        # Regression test using the real demo dataset (large and heterogeneous
        # enough for Isolation Forest to behave predictably, unlike a tiny
        # synthetic set): confirms the LOW tier is reachable and genuinely
        # low-scored, and that this doesn't regress back into flagging most
        # of the dataset -- a same-day fix once flagged 266 of 365 demo
        # transactions (every transaction with any positive Isolation Forest
        # score) before being corrected to today's gated approach.
        raw = pd.read_csv("data/sample_transactions.csv")
        from analytics.validation import validate_transactions
        df = normalise_to_reporting_currency(validate_transactions(raw).valid_rows, "USD").df
        findings = detect_anomalies(df)

        low_findings = [f for f in findings if f.risk_level == "LOW"]
        self.assertGreater(len(low_findings), 0, "expected at least one LOW-severity finding in the demo dataset")
        for f in low_findings:
            self.assertGreaterEqual(f.risk_score, 0.1)
            self.assertLess(f.risk_score, 0.5)

        # The whole point of gating on is_model_outlier / the 1.8+ z-score
        # band (rather than "any positive score") is to keep this a small,
        # meaningful set -- not most of the dataset.
        self.assertLess(len(findings), len(df) * 0.2)

    def test_duplicate_transaction_flagged(self):
        df = _make_df(
            n_normal=30, category="Supplier Payments", base_amount=500, spread=15,
            extra_rows=[
                dict(transaction_id="D1", amount=777.0, date=pd.Timestamp("2025-06-01")),
                dict(transaction_id="D2", amount=777.0, date=pd.Timestamp("2025-06-02")),
            ],
        )
        findings = detect_anomalies(df)
        flagged_ids = {f.transaction_id for f in findings}
        self.assertIn("D1", flagged_ids)
        self.assertIn("D2", flagged_ids)


class TestRateAnomaly(unittest.TestCase):
    def test_rate_within_range_returns_none(self):
        self.assertIsNone(check_rate_anomaly(1.1, (0.5, 2.0), "EUR"))

    def test_rate_outside_range_flagged_high(self):
        finding = check_rate_anomaly(50.0, (0.5, 2.0), "ZWL")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.risk_level, "HIGH")
        self.assertIn("ZWL", finding.reasons[0])


if __name__ == "__main__":
    unittest.main()
