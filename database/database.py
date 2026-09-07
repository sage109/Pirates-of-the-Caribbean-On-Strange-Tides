"""
database/database.py

Thin SQLite wrapper for NYASHA AI. Deliberately dependency-free (stdlib
sqlite3 only) so it works with zero pip installs.

IMPORTANT (see Section 0A.1 of the master prompt): on Streamlit Community
Cloud the filesystem is ephemeral. This module always resolves the DB path
relative to the project root, and database/seed.py is responsible for
rebuilding the schema + demo data on cold start. Do not assume rows written
in a previous deployment session still exist.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "database" / "nyasha.db"
SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Return a SQLite connection with sane defaults (row factory, FKs on)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str = DB_PATH, schema_path: Path | str = SCHEMA_PATH) -> None:
    """Create all tables (idempotent -- safe to call on every app start)."""
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn = get_connection(db_path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()


def reset_db(db_path: Path | str = DB_PATH) -> None:
    """Drop and recreate the database file entirely. Used by seed.py."""
    path = Path(db_path)
    if path.exists():
        path.unlink()
    init_db(db_path)


@contextmanager
def transaction(db_path: Path | str = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Context manager that commits on success, rolls back on error."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def executemany(sql: str, rows: Iterable[tuple], db_path: Path | str = DB_PATH) -> None:
    rows = list(rows)
    if not rows:
        return
    with transaction(db_path) as conn:
        conn.executemany(sql, rows)


def fetch_all(sql: str, params: tuple = (), db_path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def log_usage(
    user_action: str,
    dataset: str | None = None,
    analysis_type: str | None = None,
    currency: str | None = None,
    language: str | None = None,
    ai_inquiry: str | None = None,
    exchange_rate_request: str | None = None,
    report_generated: bool = False,
    status: str = "success",
    db_path: Path | str = DB_PATH,
) -> None:
    from datetime import datetime, timezone

    with transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO usage_history
                (timestamp, user_action, dataset, analysis_type, currency,
                 language, ai_inquiry, exchange_rate_request, report_generated, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                user_action,
                dataset,
                analysis_type,
                currency,
                language,
                ai_inquiry,
                exchange_rate_request,
                int(report_generated),
                status,
            ),
        )


def log_audit(
    user_action: str,
    transaction_ids: list[str] | None = None,
    analysis_type: str | None = None,
    original_currency: str | None = None,
    reporting_currency: str | None = None,
    exchange_rate: float | None = None,
    exchange_rate_source: str | None = None,
    calculation_results: dict | None = None,
    ai_recommendation: str | None = None,
    risk_level: str | None = None,
    db_path: Path | str = DB_PATH,
) -> None:
    from datetime import datetime, timezone

    with transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO audit_trail
                (timestamp, user_action, transaction_ids, analysis_type,
                 original_currency, reporting_currency, exchange_rate,
                 exchange_rate_source, calculation_results, ai_recommendation, risk_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                user_action,
                json.dumps(transaction_ids or []),
                analysis_type,
                original_currency,
                reporting_currency,
                exchange_rate,
                exchange_rate_source,
                json.dumps(calculation_results or {}),
                ai_recommendation,
                risk_level,
            ),
        )
