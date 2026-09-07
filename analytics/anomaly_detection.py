"""
analytics/anomaly_detection.py

Anomaly detection per Section 8. Combines:
  - Isolation Forest (scikit-learn) over amount + category-relative z-score
  - Rule-based duplicate detection (same supplier/customer, amount, and
    date within a short window, different transaction_id)
  - Category-level z-score outliers

Never labels anything "fraud" -- only "potential anomaly" / "requires
review" / "unusual transaction" / "high-risk transaction", per Section 8.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

RiskLevel = str  # "LOW" | "MEDIUM" | "HIGH"


@dataclass
class AnomalyFinding:
    transaction_id: str
    risk_score: float          # 0-1, higher = more unusual
    risk_level: RiskLevel
    reasons: list[str] = field(default_factory=list)
    recommended_action: str = "Review supporting documentation before approval."


def _risk_level_from_score(score: float) -> RiskLevel:
    if score >= 0.75:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


def _low_tier_score(abs_zscore: float, low: float = 1.8, high: float = 2.0,
                     score_floor: float = 0.1, score_ceiling: float = 0.3) -> float:
    """
    Maps a mild category z-score (expected in the `low`-`high` band -- callers
    only invoke this once that's already checked) onto a small, controlled
    LOW-tier score, e.g. z=1.8 -> 0.1, z=1.9 -> 0.2, z=2.0 -> 0.3.

    A pure function on purpose: the raw Isolation Forest score is min-max
    normalised across the whole batch, so its "boundary" case drifts all
    over 0.3-0.5 depending on what else is in the dataset (see the caller's
    comment) -- a controlled, testable formula is what actually lets LOW
    findings land at predictable, low, interpretable scores.
    """
    return round(score_floor + (abs_zscore - low) / (high - low) * (score_ceiling - score_floor), 3)


def _category_zscore(df: pd.DataFrame, amount_col: str) -> pd.Series:
    def z(group: pd.Series) -> pd.Series:
        std = group.std(ddof=0)
        if std == 0 or pd.isna(std):
            return pd.Series(0.0, index=group.index)
        return (group - group.mean()) / std

    return df.groupby("category")[amount_col].transform(z)


def _find_duplicates(df: pd.DataFrame, amount_col: str, window_days: int = 3) -> set[str]:
    """Flag transactions that closely resemble another transaction (same
    supplier/customer + amount) within a short date window -- a classic
    duplicate-submission pattern."""
    flagged: set[str] = set()
    key_col = df["supplier"].astype(str).where(df["supplier"].astype(str).str.strip() != "", df["customer"].astype(str))
    work = df.assign(_key=key_col).sort_values("date")

    for _, group in work[work["_key"].str.strip() != ""].groupby(["_key", amount_col]):
        if len(group) < 2:
            continue
        dates = group["date"].sort_values()
        for i in range(1, len(dates)):
            if (dates.iloc[i] - dates.iloc[i - 1]).days <= window_days:
                flagged.add(group["transaction_id"].iloc[i])
                flagged.add(group["transaction_id"].iloc[i - 1])
    return flagged


def detect_anomalies(
    df: pd.DataFrame,
    amount_col: str = "amount_reporting",
    contamination: float = 0.03,
    random_state: int = 42,
) -> list[AnomalyFinding]:
    """
    Returns one AnomalyFinding per transaction judged unusual (LOW findings
    are typically not surfaced in the UI, but are returned for completeness
    -- filter by risk_level in the caller).
    """
    work = df.dropna(subset=[amount_col]).copy()
    if work.empty or len(work) < 10:
        return []  # not enough data for a meaningful model

    work["_zscore"] = _category_zscore(work, amount_col)
    duplicate_ids = _find_duplicates(work, amount_col)

    # Isolation Forest over [amount, category z-score, transaction_type as int]
    features = pd.DataFrame({
        "amount": work[amount_col],
        "zscore": work["_zscore"],
        "is_expense": (work["transaction_type"] == "expense").astype(int),
    })
    iso = IsolationForest(contamination=contamination, random_state=random_state)
    iso.fit(features)
    raw_scores = -iso.score_samples(features)  # higher = more anomalous
    is_model_outlier = iso.predict(features) == -1  # respects `contamination`, unlike the raw score alone
    # normalise to 0-1
    lo, hi = raw_scores.min(), raw_scores.max()
    norm_scores = (raw_scores - lo) / (hi - lo) if hi > lo else np.zeros_like(raw_scores)

    findings: list[AnomalyFinding] = []
    for i, (_, row) in enumerate(work.iterrows()):
        score = float(norm_scores[i])
        reasons: list[str] = []

        if abs(row["_zscore"]) >= 3:
            reasons.append(f"Amount is significantly above historical {row['category']} transactions.")
            score = max(score, 0.8)
        elif abs(row["_zscore"]) >= 2:
            reasons.append(f"Amount is unusual for this category ({row['category']}).")
            score = max(score, 0.6)
        elif abs(row["_zscore"]) >= 1.8:
            # A mild, LOW-tier signal on a controlled 0.1-0.3 scale (interpolated by
            # how far into the 1.8-2.0 z-score band it falls), rather than the raw
            # Isolation Forest score -- that score is min-max normalised across the
            # whole batch, so its "boundary" case still lands near 0.4-0.5 however
            # many outliers are added (the true extremes dominate the top of the
            # range without pulling the mild cases down). This keeps LOW findings
            # both meaningful and placed where the risk-level bands expect them.
            interpolated = _low_tier_score(abs(row["_zscore"]))
            reasons.append(f"Amount is slightly outside the typical range for this category ({row['category']}).")
            # Direct assignment, not max(): the raw Isolation Forest score is
            # min-max normalised across the whole batch, so it can already sit
            # well above 0.3 for a transaction that's merely mildly unusual --
            # taking max() here would leave LOW findings drifting anywhere up to
            # ~0.5 depending on what else is in the dataset. This tier's whole
            # point is a controlled, low, interpretable score, so it overrides.
            score = round(interpolated, 3)

        if row["transaction_id"] in duplicate_ids:
            reasons.append("A very similar transaction occurred within a few days -- possible duplicate.")
            score = max(score, 0.75)

        if score >= 0.5 and not reasons:
            reasons.append("Transaction pattern is statistically unusual relative to similar transactions.")
        elif is_model_outlier[i] and not reasons:
            # Model flags it among the most unusual ~contamination% of transactions,
            # but nothing crossed the sharper z-score/duplicate rules above -- a
            # genuine but mild anomaly, not just "somewhere in the normalised range"
            # (min-max normalising a continuous Isolation Forest score spreads even
            # ordinary transactions across 0-1, so gating on `is_model_outlier`
            # rather than a raw score floor is what keeps this to a small, real set).
            reasons.append("Transaction pattern is mildly unusual relative to similar transactions, but within normal variation.")

        if not reasons:
            continue  # not flagged

        level = _risk_level_from_score(score)
        action = {
            "HIGH": "Review supporting documentation before approval.",
            "MEDIUM": "Verify against supporting records; monitor for recurrence.",
            "LOW": "No action required; noted for awareness.",
        }[level]

        findings.append(AnomalyFinding(
            transaction_id=row["transaction_id"], risk_score=round(score, 3),
            risk_level=level, reasons=reasons, recommended_action=action,
        ))

    findings.sort(key=lambda f: f.risk_score, reverse=True)
    return findings


def check_rate_anomaly(rate: float, expected_range: tuple[float, float], currency: str) -> AnomalyFinding | None:
    """
    Per Section 0A.4: flag a stale/outlier exchange rate (particularly
    ZWL) as its own anomaly, since a bad FX rate silently corrupts every
    downstream figure.
    """
    low, high = expected_range
    if low <= rate <= high:
        return None
    return AnomalyFinding(
        transaction_id=f"FX-RATE-{currency}",
        risk_score=0.9,
        risk_level="HIGH",
        reasons=[f"{currency} exchange rate ({rate}) is far outside the expected range ({low}-{high})."],
        recommended_action="Verify the exchange rate manually before trusting converted figures.",
    )
