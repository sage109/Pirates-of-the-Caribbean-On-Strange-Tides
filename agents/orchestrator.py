"""
agents/orchestrator.py

Section 18: orchestrates the individual analysis steps into a single agent
pipeline using LangGraph, so NYASHA AI behaves like one coherent agent
rather than a set of unrelated Streamlit pages calling functions ad hoc.

Design rule (Section 0A.3, 17, 37): every node in this graph either calls a
function already unit-tested in analytics/ or rules/ (deterministic, no
LLM), or is the single designated "explain" node that hands verified
results to services/llm_service.py. No node recomputes or estimates a
number the deterministic layer already produced.

IMPORTANT -- sandbox limitation: `langgraph` is not installed in the
offline environment this was built in (no network access there). This
module is written and structured against LangGraph's documented
StateGraph API but has NOT been run against the real library. It has,
however, been exercised end-to-end via `run_pipeline_sync`, which contains
the exact same node logic in a plain-Python fallback so the whole pipeline
is tested and correct *before* LangGraph is even in the picture. Once
`pip install langgraph` succeeds in a networked environment:

    from agents.orchestrator import build_graph
    graph = build_graph()
    result = graph.invoke(initial_state)

should behave identically to `run_pipeline_sync`. If anything differs,
trust the plain-Python fallback's node functions (`NODE_FUNCS` below) --
they are the tested source of truth; `build_graph` only wires them up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict

import pandas as pd

from analytics.anomaly_detection import check_rate_anomaly, detect_anomalies
from analytics.currency_normalisation import normalise_to_reporting_currency
from analytics.customer_analysis import analyse_customer_risk
from analytics.financial_health import calculate_financial_health
from analytics.financial_metrics import (
    liquidity_summary, profitability_summary, working_capital_summary,
)
from analytics.forecasting import forecast_all_horizons
from analytics.validation import validate_transactions
from rules.vat_rules import calculate_vat_summary
from services.llm_service import explain_financial_result


class AgentState(TypedDict, total=False):
    """Shared state threaded through every node. Mirrors LangGraph's
    dict-based state convention so this maps 1:1 onto a StateGraph."""

    raw_df: pd.DataFrame
    reporting_currency: str
    language: str

    validation_result: Any
    normalised_df: pd.DataFrame
    fx_rate_result: Any

    profitability: Any
    liquidity: Any
    working_capital: Any
    health_score: Any
    anomalies: list
    forecasts: dict
    customer_risk: list
    vat_summary: Any

    ai_explanation: str
    errors: list[str]


def _node_validate(state: AgentState) -> AgentState:
    result = validate_transactions(state["raw_df"])
    state["validation_result"] = result
    return state


def _node_normalise_currency(state: AgentState) -> AgentState:
    result = state["validation_result"]
    norm = normalise_to_reporting_currency(result.valid_rows, state.get("reporting_currency", "USD"))
    state["normalised_df"] = norm.df
    state["fx_rate_result"] = norm.rates_used  # dict[currency -> RateResult | None]
    return state


def _node_financial_metrics(state: AgentState) -> AgentState:
    df = state["normalised_df"]
    state["profitability"] = profitability_summary(df)
    state["liquidity"] = liquidity_summary(df)
    state["working_capital"] = working_capital_summary(df)
    return state


def _node_health_score(state: AgentState) -> AgentState:
    state["health_score"] = calculate_financial_health(state["normalised_df"])
    return state


def _node_anomalies(state: AgentState) -> AgentState:
    from services.exchange_rates import CACHED_RATES

    df = state["normalised_df"]
    findings = detect_anomalies(df)

    # Section 0A.4 -- a bad/stale FX rate corrupts every downstream figure,
    # so each rate actually used to normalise this dataset is itself
    # checked against a wide tolerance band around the bundled cached
    # table (the only reference point available offline). This deliberately
    # only flags gross outliers (e.g. a mistyped or badly stale rate), not
    # ordinary day-to-day FX movement.
    rates_used: dict = state.get("fx_rate_result") or {}
    for currency, rr in rates_used.items():
        if rr is None or currency not in CACHED_RATES or CACHED_RATES[currency] == 0:
            continue
        baseline = CACHED_RATES[currency]  # units of `currency` per 1 USD
        implied_rate_vs_usd = 1.0 / rr.rate if rr.to_currency == "USD" and rr.rate else None
        if implied_rate_vs_usd is None:
            continue
        expected_range = (baseline * 0.5, baseline * 2.0)
        fx_finding = check_rate_anomaly(implied_rate_vs_usd, expected_range, currency)
        if fx_finding:
            findings.append(fx_finding)

    state["anomalies"] = findings
    return state


def _node_forecast(state: AgentState) -> AgentState:
    state["forecasts"] = forecast_all_horizons(state["normalised_df"])
    return state


def _node_customer_risk(state: AgentState) -> AgentState:
    state["customer_risk"] = analyse_customer_risk(state["normalised_df"])
    return state


def _node_vat(state: AgentState) -> AgentState:
    state["vat_summary"] = calculate_vat_summary(state["normalised_df"])
    return state


def _node_explain(state: AgentState) -> AgentState:
    """The single node permitted to call the LLM (Section 17/37) -- it
    receives only already-computed figures, never raw transactions."""
    payload = {
        "profitability": state.get("profitability"),
        "liquidity": state.get("liquidity"),
        "health_score": state.get("health_score"),
        "top_anomalies": (state.get("anomalies") or [])[:5],
        "vat_summary": state.get("vat_summary"),
    }
    state["ai_explanation"] = explain_financial_result(payload, language=state.get("language", "en"))
    return state


# Node registry -- the tested source of truth (see module docstring).
NODE_FUNCS: dict[str, Callable[[AgentState], AgentState]] = {
    "validate": _node_validate,
    "normalise_currency": _node_normalise_currency,
    "financial_metrics": _node_financial_metrics,
    "health_score": _node_health_score,
    "anomalies": _node_anomalies,
    "forecast": _node_forecast,
    "customer_risk": _node_customer_risk,
    "vat": _node_vat,
    "explain": _node_explain,
}

# Execution order for the plain-Python fallback / LangGraph edge wiring.
# financial_metrics must run before health_score (health score depends on
# the same summaries); everything else is independent of one another and
# only depends on normalise_currency having run.
NODE_ORDER = [
    "validate",
    "normalise_currency",
    "financial_metrics",
    "health_score",
    "anomalies",
    "forecast",
    "customer_risk",
    "vat",
    "explain",
]


def run_pipeline_sync(
    raw_df: pd.DataFrame,
    reporting_currency: str = "USD",
    language: str = "en",
    include_explanation: bool = True,
) -> AgentState:
    """
    Plain-Python execution of the same pipeline `build_graph()` wires up
    with LangGraph. This is what actually runs today (no `langgraph`
    dependency needed) and is what the test suite exercises -- treat it as
    the reference implementation, not a placeholder.

    Set include_explanation=False to skip the one node that calls the LLM
    (e.g. for fast unit tests, or a "quick view" UI mode).
    """
    state: AgentState = {
        "raw_df": raw_df,
        "reporting_currency": reporting_currency,
        "language": language,
        "errors": [],
    }
    order = NODE_ORDER if include_explanation else [n for n in NODE_ORDER if n != "explain"]
    for name in order:
        try:
            state = NODE_FUNCS[name](state)
        except Exception as exc:  # a single failed node must not crash the whole agent
            state.setdefault("errors", []).append(f"{name}: {exc}")
    return state


def build_graph():
    """
    Builds the real LangGraph StateGraph. Requires `langgraph` to be
    installed -- raises a clear, actionable error otherwise rather than a
    raw ImportError, mirroring the pattern in services/llm_service.py.

    Callers that don't strictly need LangGraph's graph semantics (branching,
    checkpointing, streaming, visualisation) can use `run_pipeline_sync`
    instead and get identical results.
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "The 'langgraph' package is not installed. Run: pip install langgraph "
            "-- or call agents.orchestrator.run_pipeline_sync() instead, which runs "
            "the same nodes without it."
        ) from exc

    graph = StateGraph(AgentState)
    for name, func in NODE_FUNCS.items():
        graph.add_node(name, func)

    graph.set_entry_point(NODE_ORDER[0])
    for a, b in zip(NODE_ORDER, NODE_ORDER[1:]):
        graph.add_edge(a, b)
    graph.add_edge(NODE_ORDER[-1], END)

    return graph.compile()


@dataclass
class PipelineSummary:
    """Convenience wrapper the UI can use instead of digging through the
    raw AgentState dict."""

    profitability: Any
    liquidity: Any
    health_score: Any
    anomalies: list
    forecasts: dict
    customer_risk: list
    vat_summary: Any
    ai_explanation: str | None
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_state(cls, state: AgentState) -> "PipelineSummary":
        return cls(
            profitability=state.get("profitability"),
            liquidity=state.get("liquidity"),
            health_score=state.get("health_score"),
            anomalies=state.get("anomalies") or [],
            forecasts=state.get("forecasts") or {},
            customer_risk=state.get("customer_risk") or [],
            vat_summary=state.get("vat_summary"),
            ai_explanation=state.get("ai_explanation"),
            errors=state.get("errors") or [],
        )


def run_full_analysis(
    raw_df: pd.DataFrame, reporting_currency: str = "USD", language: str = "en",
    include_explanation: bool = True,
) -> PipelineSummary:
    """Single entry point the UI (or a future API) should call."""
    state = run_pipeline_sync(raw_df, reporting_currency, language, include_explanation)
    return PipelineSummary.from_state(state)
