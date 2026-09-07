"""
analytics/validation.py

Deterministic validation of uploaded transaction data, per Section 5 of the
master prompt. No LLM involved -- this is pure Python/pandas.

Usage:
    df = pd.read_csv("data/sample_transactions.csv")
    result = validate_transactions(df)
    print(result.summary())
    clean_df = result.valid_rows
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "transaction_id", "date", "description", "transaction_type",
    "amount", "currency",
]
OPTIONAL_COLUMNS = [
    "account", "customer", "supplier", "category", "payment_method",
    "invoice_number", "vat_status",
]
VALID_TRANSACTION_TYPES = {"income", "expense", "transfer"}
VALID_VAT_STATUSES = {"standard", "zero_rated", "exempt"}
KNOWN_CURRENCIES = {"USD", "ZWL", "ZAR", "GBP", "EUR", "BWP", "ZMW"}


@dataclass
class ValidationResult:
    total_rows: int
    valid_rows: pd.DataFrame
    invalid_rows: pd.DataFrame
    missing_columns: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    unknown_currencies: list[str] = field(default_factory=list)
    missing_vat_status_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.valid_rows)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid_rows)

    def summary(self) -> str:
        lines = ["DATA VALIDATION", ""]
        if self.errors:
            for e in self.errors:
                lines.append(f"✗ {e}")
            return "\n".join(lines)

        lines.append(f"✓ {self.valid_count:,} valid transactions")
        if self.duplicate_ids:
            lines.append(f"⚠ {len(self.duplicate_ids)} duplicate transaction IDs")
        else:
            lines.append("✓ No duplicate transaction IDs")
        if self.missing_vat_status_count:
            lines.append(f"⚠ {self.missing_vat_status_count} transactions missing VAT status")
        if self.unknown_currencies:
            lines.append(f"⚠ {len(self.unknown_currencies)} transactions contain unknown currencies")
        if self.invalid_count:
            lines.append(f"⚠ {self.invalid_count} transactions failed validation and were excluded")
        for w in self.warnings:
            lines.append(f"⚠ {w}")
        return "\n".join(lines)


def validate_transactions(df: pd.DataFrame) -> ValidationResult:
    total_rows = len(df)
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]

    if missing_columns:
        return ValidationResult(
            total_rows=total_rows,
            valid_rows=pd.DataFrame(columns=df.columns),
            invalid_rows=df.copy(),
            missing_columns=missing_columns,
            errors=[f"Missing required column(s): {', '.join(missing_columns)}"],
        )

    work = df.copy()
    for col in OPTIONAL_COLUMNS:
        if col not in work.columns:
            work[col] = ""
    work = work.fillna("")

    row_errors = [[] for _ in range(len(work))]

    # --- Required field presence -------------------------------------------------
    for col in ["transaction_id", "description", "transaction_type", "amount", "currency", "date"]:
        empty_mask = work[col].astype(str).str.strip().eq("")
        for idx in work.index[empty_mask]:
            row_errors[work.index.get_loc(idx)].append(f"missing {col}")

    # --- Duplicate transaction IDs ------------------------------------------------
    dup_mask = work["transaction_id"].duplicated(keep=False) & work["transaction_id"].astype(str).str.strip().ne("")
    duplicate_ids = sorted(work.loc[dup_mask, "transaction_id"].unique().tolist())
    for idx in work.index[dup_mask]:
        row_errors[work.index.get_loc(idx)].append("duplicate transaction_id")

    # --- Date validity --------------------------------------------------------------
    parsed_dates = pd.to_datetime(work["date"], errors="coerce")
    invalid_date_mask = parsed_dates.isna()
    for idx in work.index[invalid_date_mask]:
        row_errors[work.index.get_loc(idx)].append("invalid date")

    # --- Amount validity ------------------------------------------------------------
    numeric_amount = pd.to_numeric(work["amount"], errors="coerce")
    invalid_amount_mask = numeric_amount.isna() | (numeric_amount == 0)
    for idx in work.index[invalid_amount_mask]:
        row_errors[work.index.get_loc(idx)].append("invalid or zero amount")

    # --- Transaction type validity ---------------------------------------------
    invalid_type_mask = ~work["transaction_type"].astype(str).str.lower().isin(VALID_TRANSACTION_TYPES)
    for idx in work.index[invalid_type_mask]:
        row_errors[work.index.get_loc(idx)].append("invalid transaction_type")

    # --- Currency: unknown (warn, not hard-fail) ---------------------------------
    unknown_currency_mask = ~work["currency"].astype(str).str.upper().isin(KNOWN_CURRENCIES)
    unknown_currencies = sorted(work.loc[unknown_currency_mask, "transaction_id"].astype(str).tolist())

    # --- VAT status missing (warn, not hard-fail) --------------------------------
    missing_vat_mask = work["vat_status"].astype(str).str.strip().eq("")
    missing_vat_status_count = int(missing_vat_mask.sum())

    work["_row_errors"] = row_errors
    # NOTE: .astype(bool) matters -- on an empty DataFrame, .apply() on an
    # empty column returns object dtype, and boolean-indexing with an
    # object-dtype (rather than bool-dtype) empty mask silently drops all
    # columns from the result. Explicit bool cast avoids that pandas quirk.
    work["is_valid"] = work["_row_errors"].apply(lambda e: len(e) == 0).astype(bool)

    valid_rows = work[work["is_valid"]].drop(columns=["_row_errors"]).copy()
    invalid_rows = work[~work["is_valid"]].copy()
    invalid_rows["validation_notes"] = invalid_rows["_row_errors"].apply(lambda e: "; ".join(e))
    invalid_rows = invalid_rows.drop(columns=["_row_errors"])

    # Normalise dtypes on the valid set for downstream modules
    valid_rows["amount"] = pd.to_numeric(valid_rows["amount"], errors="coerce")
    valid_rows["currency"] = valid_rows["currency"].astype(str).str.upper()
    valid_rows["transaction_type"] = valid_rows["transaction_type"].astype(str).str.lower()
    valid_rows["date"] = pd.to_datetime(valid_rows["date"], errors="coerce")

    warnings = []
    if unknown_currencies:
        warnings.append(
            f"{len(unknown_currencies)} valid transactions use a currency outside the supported list "
            f"({', '.join(sorted(KNOWN_CURRENCIES))})"
        )

    return ValidationResult(
        total_rows=total_rows,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        missing_columns=[],
        duplicate_ids=duplicate_ids,
        unknown_currencies=unknown_currencies,
        missing_vat_status_count=missing_vat_status_count,
        warnings=warnings,
    )
