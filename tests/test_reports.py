import unittest

import pandas as pd

from agents.orchestrator import run_full_analysis
from reports.report_generator import (
    build_anomalies_csv, build_customer_risk_csv, build_html_report,
    build_transactions_csv, export_pdf_if_available,
)


class TestReportGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        df = pd.read_csv("data/sample_transactions.csv")
        cls.df = df
        cls.summary = run_full_analysis(df, reporting_currency="USD", include_explanation=False)

    def test_html_report_contains_key_figures(self):
        report = build_html_report(
            business_name="Moyo Retail & Services", reporting_currency="USD",
            profitability=self.summary.profitability, health_score=self.summary.health_score,
            anomalies=self.summary.anomalies, forecasts=self.summary.forecasts,
            vat_summary=self.summary.vat_summary,
        )
        self.assertIn("<html", report)
        self.assertIn("Moyo Retail &amp; Services", report)
        self.assertIn(f"{self.summary.health_score.total_score}/100", report)
        self.assertIn("does not replace professional tax", report)

    def test_html_report_handles_no_anomalies(self):
        report = build_html_report(
            business_name="Test Co", reporting_currency="USD",
            profitability=self.summary.profitability, health_score=self.summary.health_score,
            anomalies=[], forecasts=self.summary.forecasts, vat_summary=self.summary.vat_summary,
        )
        self.assertIn("No anomalies detected", report)

    def test_html_report_escapes_untrusted_text(self):
        report = build_html_report(
            business_name="<script>alert(1)</script>", reporting_currency="USD",
            profitability=self.summary.profitability, health_score=self.summary.health_score,
            anomalies=[], forecasts=self.summary.forecasts, vat_summary=self.summary.vat_summary,
        )
        self.assertNotIn("<script>alert(1)</script>", report)
        self.assertIn("&lt;script&gt;", report)

    def test_transactions_csv_round_trips(self):
        csv_text = build_transactions_csv(self.df)
        self.assertIn("transaction_id", csv_text.splitlines()[0])
        self.assertEqual(len(csv_text.splitlines()), len(self.df) + 1)

    def test_anomalies_csv_has_a_row_per_finding(self):
        csv_text = build_anomalies_csv(self.summary.anomalies)
        self.assertEqual(len(csv_text.strip().splitlines()), len(self.summary.anomalies) + 1)

    def test_customer_risk_csv_handles_empty_list(self):
        self.assertEqual(build_customer_risk_csv([]), "customer,risk_level\n")

    def test_pdf_export_returns_none_without_a_backend(self):
        # Neither xhtml2pdf nor weasyprint is installed in this sandbox --
        # confirms the fallback never raises.
        report = build_html_report(
            business_name="Test Co", reporting_currency="USD",
            profitability=self.summary.profitability, health_score=self.summary.health_score,
            anomalies=[], forecasts=self.summary.forecasts, vat_summary=self.summary.vat_summary,
        )
        self.assertIsNone(export_pdf_if_available(report))


if __name__ == "__main__":
    unittest.main()
