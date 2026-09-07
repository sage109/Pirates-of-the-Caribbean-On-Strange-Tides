"""
database/seed.py

Rebuilds the database from scratch and loads the demo dataset + a small
illustrative usage/analysis history so a fresh deploy (or a Streamlit
Community Cloud cold start, which wipes local files -- see Section 0A.1
of the master prompt) always demos correctly.

Call seed_if_needed() from app.py on startup. It is idempotent: if the DB
already has transactions loaded, it does nothing (so a user's uploaded
data during a live session isn't wiped by an accidental re-run).

Run directly to force a full reset: `python3 database/seed.py --force`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from database.database import DB_PATH, fetch_all, init_db, reset_db, transaction

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CSV = PROJECT_ROOT / "data" / "sample_transactions.csv"


def _load_sample_transactions() -> pd.DataFrame:
    if not SAMPLE_CSV.exists():
        # Fall back to generating it fresh if the CSV wasn't shipped.
        sys.path.insert(0, str(PROJECT_ROOT / "data"))
        from generate_sample_data import build_transactions, inject_anomalies_and_quality_issues, write_csv
        rows = inject_anomalies_and_quality_issues(build_transactions())
        write_csv(rows, SAMPLE_CSV)
    return pd.read_csv(SAMPLE_CSV)


def _insert_transactions(df: pd.DataFrame) -> None:
    with transaction() as conn:
        for _, row in df.iterrows():
            conn.execute(
                """
                INSERT OR REPLACE INTO transactions
                    (transaction_id, date, description, account, customer, supplier,
                     transaction_type, category, amount, currency, payment_method,
                     invoice_number, vat_status, is_valid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    row["transaction_id"], str(row["date"]), row["description"],
                    row.get("account", ""), row.get("customer", ""), row.get("supplier", ""),
                    row["transaction_type"], row.get("category", ""), float(row["amount"]),
                    row["currency"], row.get("payment_method", ""),
                    row.get("invoice_number", ""), row.get("vat_status", ""),
                ),
            )


def seed_if_needed(force: bool = False) -> None:
    if force:
        reset_db()
    else:
        init_db()

    existing = fetch_all("SELECT COUNT(*) as n FROM transactions")
    if existing and existing[0]["n"] > 0 and not force:
        return  # already seeded -- don't clobber a live session's uploaded data

    df = _load_sample_transactions()
    _insert_transactions(df)

    from database.database import log_usage
    log_usage(user_action="Uploaded transactions", dataset="Moyo Retail & Services (demo)",
               analysis_type="seed", status="success")
    log_usage(user_action="Financial analysis", dataset="Moyo Retail & Services (demo)",
               analysis_type="full", currency="USD", language="en", status="success")

    print(f"Seeded {len(df)} demo transactions into {DB_PATH}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    seed_if_needed(force=force)
