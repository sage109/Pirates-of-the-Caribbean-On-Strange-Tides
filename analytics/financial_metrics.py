"""
analytics/financial_metrics.py

Deterministic financial calculations, per Section 6 of the master prompt.
The LLM must NEVER compute any of these figures -- this module is the
single source of truth for revenue, expenses, profit, margins, and
liquidity ratios.

All functions take a validated transactions DataFrame that has already
been normalised to a single reporting currency (see
analytics/currency_normalisation.py) with a numeric 'amount_reporting'
column, unless noted otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


def _month_key(dates: pd.Series) -> pd.Series:
    return dates.dt.to_period("M").astype(str)


# --------------------------------------------------------------------------- Revenue
def total_revenue(df: pd.DataFrame, amount_col: str = "amount_reporting") -> float:
    return round(df.loc[df["transaction_type"] == "income", amount_col].sum(), 2)


def revenue_by_category(df: pd.DataFrame, amount_col: str = "amount_reporting") -> dict[str, float]:
    income = df[df["transaction_type"] == "income"]
    return income.groupby("category")[amount_col].sum().round(2).to_dict()


def revenue_by_customer(df: pd.DataFrame, amount_col: str = "amount_reporting") -> dict[str, float]:
    income = df[(df["transaction_type"] == "income") & (df["customer"].astype(str).str.strip() != "")]
    return income.groupby("customer")[amount_col].sum().round(2).to_dict()


def revenue_by_currency(df: pd.DataFrame, amount_col: str = "amount") -> dict[str, float]:
    """Uses ORIGINAL currency amounts, not converted -- see Section 12: never mix currencies silently."""
    income = df[df["transaction_type"] == "income"]
    return income.groupby("currency")[amount_col].sum().round(2).to_dict()


def average_monthly_revenue(df: pd.DataFrame, amount_col: str = "amount_reporting") -> float:
    income = df[df["transaction_type"] == "income"].copy()
    if income.empty:
        return 0.0
    income["month"] = _month_key(income["date"])
    monthly = income.groupby("month")[amount_col].sum()
    return round(monthly.mean(), 2)


def revenue_growth(df: pd.DataFrame, amount_col: str = "amount_reporting") -> float | None:
    """Percentage growth between the first and last month present in the data."""
    income = df[df["transaction_type"] == "income"].copy()
    if income.empty:
        return None
    income["month"] = _month_key(income["date"])
    monthly = income.groupby("month")[amount_col].sum().sort_index()
    if len(monthly) < 2:
        return None
    first, last = monthly.iloc[0], monthly.iloc[-1]
    if first == 0:
        return None
    return round((last - first) / first * 100, 2)


# --------------------------------------------------------------------------- Expenses
def total_expenses(df: pd.DataFrame, amount_col: str = "amount_reporting") -> float:
    return round(df.loc[df["transaction_type"] == "expense", amount_col].sum(), 2)


def expense_by_category(df: pd.DataFrame, amount_col: str = "amount_reporting") -> dict[str, float]:
    exp = df[df["transaction_type"] == "expense"]
    return exp.groupby("category")[amount_col].sum().round(2).to_dict()


def expense_by_supplier(df: pd.DataFrame, amount_col: str = "amount_reporting") -> dict[str, float]:
    exp = df[(df["transaction_type"] == "expense") & (df["supplier"].astype(str).str.strip() != "")]
    return exp.groupby("supplier")[amount_col].sum().round(2).to_dict()


def expense_by_currency(df: pd.DataFrame, amount_col: str = "amount") -> dict[str, float]:
    exp = df[df["transaction_type"] == "expense"]
    return exp.groupby("currency")[amount_col].sum().round(2).to_dict()


def expense_growth(df: pd.DataFrame, amount_col: str = "amount_reporting") -> float | None:
    exp = df[df["transaction_type"] == "expense"].copy()
    if exp.empty:
        return None
    exp["month"] = _month_key(exp["date"])
    monthly = exp.groupby("month")[amount_col].sum().sort_index()
    if len(monthly) < 2:
        return None
    first, last = monthly.iloc[0], monthly.iloc[-1]
    if first == 0:
        return None
    return round((last - first) / first * 100, 2)


OPERATING_EXPENSE_CATEGORIES = {
    "Rent", "Salaries", "Utilities", "Transport", "Bank Charges",
    "Operating Expenses", "Marketing", "Repairs & Maintenance",
}


def operating_expenses(df: pd.DataFrame, amount_col: str = "amount_reporting") -> float:
    exp = df[(df["transaction_type"] == "expense") & (df["category"].isin(OPERATING_EXPENSE_CATEGORIES))]
    return round(exp[amount_col].sum(), 2)


# --------------------------------------------------------------------------- Profitability
@dataclass
class ProfitabilitySummary:
    revenue: float
    expenses: float
    cogs: float                 # cost of goods sold (supplier payments proxy)
    gross_profit: float
    gross_margin_pct: float | None
    operating_profit: float
    operating_margin_pct: float | None
    net_profit: float
    net_margin_pct: float | None


def profitability_summary(df: pd.DataFrame, amount_col: str = "amount_reporting") -> ProfitabilitySummary:
    revenue = total_revenue(df, amount_col)
    expenses = total_expenses(df, amount_col)
    cogs = round(
        df.loc[(df["transaction_type"] == "expense") & (df["category"] == "Supplier Payments"), amount_col].sum(), 2
    )
    gross_profit = round(revenue - cogs, 2)
    opex = operating_expenses(df, amount_col)
    operating_profit = round(gross_profit - opex, 2)
    net_profit = round(revenue - expenses, 2)

    def pct(numerator: float) -> float | None:
        return round(numerator / revenue * 100, 2) if revenue else None

    return ProfitabilitySummary(
        revenue=revenue, expenses=expenses, cogs=cogs,
        gross_profit=gross_profit, gross_margin_pct=pct(gross_profit),
        operating_profit=operating_profit, operating_margin_pct=pct(operating_profit),
        net_profit=net_profit, net_margin_pct=pct(net_profit),
    )


# --------------------------------------------------------------------------- Liquidity
@dataclass
class LiquiditySummary:
    cash_inflows: float
    cash_outflows: float
    net_cash_flow: float
    current_ratio: float | None
    quick_ratio: float | None


CURRENT_LIABILITY_CATEGORIES = {"Supplier Payments", "Bank Charges"}


def liquidity_summary(df: pd.DataFrame, amount_col: str = "amount_reporting") -> LiquiditySummary:
    inflows = round(df.loc[df["transaction_type"] == "income", amount_col].sum(), 2)
    outflows = round(df.loc[df["transaction_type"] == "expense", amount_col].sum(), 2)
    net_cash_flow = round(inflows - outflows, 2)

    # Simplified proxy ratios from transaction data (no formal balance sheet
    # is available from a transaction feed alone) -- current assets ~ cash +
    # receivables proxy; current liabilities ~ near-term payables proxy.
    current_assets = inflows  # proxy: cash generated in period
    current_liabilities = round(
        df.loc[(df["transaction_type"] == "expense") & (df["category"].isin(CURRENT_LIABILITY_CATEGORIES)), amount_col].sum(), 2
    )
    current_ratio = round(current_assets / current_liabilities, 2) if current_liabilities else None
    quick_assets = current_assets  # no inventory data available from transactions
    quick_ratio = round(quick_assets / current_liabilities, 2) if current_liabilities else None

    return LiquiditySummary(
        cash_inflows=inflows, cash_outflows=outflows, net_cash_flow=net_cash_flow,
        current_ratio=current_ratio, quick_ratio=quick_ratio,
    )


# --------------------------------------------------------------------------- Working capital
@dataclass
class WorkingCapitalSummary:
    receivables: float
    payables: float
    receivables_trend_pct: float | None
    payables_trend_pct: float | None


def working_capital_summary(df: pd.DataFrame, amount_col: str = "amount_reporting") -> WorkingCapitalSummary:
    """
    Proxy receivables/payables from transaction categories, since raw
    transaction feeds don't carry an AR/AP subledger. 'Customer Receipts'
    are treated as receivables activity; 'Supplier Payments' as payables
    activity. Trend = growth between first and last month present.
    """
    receivables_df = df[df["category"] == "Customer Receipts"].copy()
    payables_df = df[df["category"] == "Supplier Payments"].copy()

    receivables = round(receivables_df[amount_col].sum(), 2)
    payables = round(payables_df[amount_col].sum(), 2)

    def trend(sub_df: pd.DataFrame) -> float | None:
        if sub_df.empty:
            return None
        sub_df["month"] = _month_key(sub_df["date"])
        monthly = sub_df.groupby("month")[amount_col].sum().sort_index()
        if len(monthly) < 2 or monthly.iloc[0] == 0:
            return None
        return round((monthly.iloc[-1] - monthly.iloc[0]) / monthly.iloc[0] * 100, 2)

    return WorkingCapitalSummary(
        receivables=receivables, payables=payables,
        receivables_trend_pct=trend(receivables_df), payables_trend_pct=trend(payables_df),
    )
