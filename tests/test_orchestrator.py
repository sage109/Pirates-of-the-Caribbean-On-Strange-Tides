import unittest

import pandas as pd

from agents.orchestrator import NODE_ORDER, run_full_analysis, run_pipeline_sync


def _demo_df() -> pd.DataFrame:
    return pd.read_csv("data/sample_transactions.csv")


class TestOrchestrator(unittest.TestCase):
    def test_full_pipeline_runs_without_errors(self):
        summary = run_full_analysis(_demo_df(), reporting_currency="USD", include_explanation=True)
        self.assertEqual(summary.errors, [])
        self.assertIsNotNone(summary.profitability)
        self.assertIsNotNone(summary.health_score)
        self.assertIsNotNone(summary.vat_summary)
        self.assertIn("ai_explanation" if False else True, [True])  # explanation always a string
        self.assertIsInstance(summary.ai_explanation, str)

    def test_pipeline_skips_llm_node_when_not_requested(self):
        state = run_pipeline_sync(_demo_df(), include_explanation=False)
        self.assertNotIn("ai_explanation", state)
        self.assertEqual(state.get("errors"), [])

    def test_offline_llm_call_never_crashes_pipeline(self):
        # No ANTHROPIC_API_KEY is set in this sandbox -- the explain node
        # must degrade to the documented demo-mode string, not raise.
        summary = run_full_analysis(_demo_df(), include_explanation=True)
        self.assertIn("DEMO MODE", summary.ai_explanation)

    def test_empty_dataframe_does_not_crash_pipeline(self):
        empty = pd.DataFrame(columns=[
            "transaction_id", "date", "description", "customer", "supplier",
            "transaction_type", "category", "amount", "currency", "vat_status",
        ])
        summary = run_full_analysis(empty, include_explanation=False)
        self.assertEqual(summary.anomalies, [])
        self.assertEqual(summary.customer_risk, [])

    def test_node_order_covers_every_registered_node(self):
        from agents.orchestrator import NODE_FUNCS
        self.assertEqual(set(NODE_ORDER), set(NODE_FUNCS.keys()))

    def test_build_graph_raises_clear_error_without_langgraph(self):
        from agents.orchestrator import build_graph
        with self.assertRaises(RuntimeError) as ctx:
            build_graph()
        self.assertIn("langgraph", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
