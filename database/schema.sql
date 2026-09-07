-- NYASHA AI database schema
-- SQLite. Note: on Streamlit Community Cloud this file is ephemeral
-- (wiped on redeploy/reboot) -- see database/seed.py, which rebuilds
-- everything below from the sample dataset on cold start.

PRAGMA foreign_keys = ON;

-- Raw + validated transactions -------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id      TEXT PRIMARY KEY,
    date                 TEXT NOT NULL,          -- ISO 8601 date
    description          TEXT NOT NULL,
    account               TEXT,
    customer              TEXT,
    supplier              TEXT,
    transaction_type     TEXT NOT NULL,          -- income | expense | transfer
    category              TEXT,
    amount                REAL NOT NULL,          -- in original currency
    currency               TEXT NOT NULL,
    payment_method       TEXT,
    invoice_number       TEXT,
    vat_status             TEXT,                   -- standard | zero_rated | exempt | unknown
    is_valid                INTEGER DEFAULT 1,
    validation_notes    TEXT
);

-- Exchange rates used anywhere in the app, for traceability --------------
CREATE TABLE IF NOT EXISTS exchange_rates (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    from_currency        TEXT NOT NULL,
    to_currency           TEXT NOT NULL,
    rate                   REAL NOT NULL,
    rate_type              TEXT NOT NULL,          -- live | historical | cached | manual
    source                 TEXT NOT NULL,
    fetched_at             TEXT NOT NULL           -- ISO 8601 timestamp
);

-- Anomaly detection results -------------------------------------------------
CREATE TABLE IF NOT EXISTS anomalies (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id        TEXT NOT NULL REFERENCES transactions(transaction_id),
    risk_score             REAL NOT NULL,
    risk_level              TEXT NOT NULL,          -- LOW | MEDIUM | HIGH
    reasons                 TEXT NOT NULL,           -- JSON-encoded list of strings
    recommended_action  TEXT,
    detected_at            TEXT NOT NULL
);

-- Customer payment risk ------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer_risk (
    customer                TEXT PRIMARY KEY,
    avg_payment_delay_days REAL,
    outstanding_receivables REAL,
    payment_frequency       REAL,
    avg_invoice_value      REAL,
    risk_level                TEXT,                  -- LOW | MEDIUM | HIGH
    recommended_action    TEXT,
    updated_at               TEXT
);

-- Usage history ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_history (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT NOT NULL,
    user_action             TEXT NOT NULL,
    dataset                  TEXT,
    analysis_type          TEXT,
    currency                 TEXT,
    language                  TEXT,
    ai_inquiry               TEXT,
    exchange_rate_request TEXT,
    report_generated      INTEGER DEFAULT 0,
    status                     TEXT DEFAULT 'success'
);

-- Analysis history (snapshots for period comparison) -----------------------
CREATE TABLE IF NOT EXISTS analysis_history (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_date            TEXT NOT NULL,
    dataset                    TEXT,
    revenue                    REAL,
    expenses                    REAL,
    profit                       REAL,
    cash_balance               REAL,
    financial_health_score  REAL,
    risk_level                   TEXT,
    recommendations           TEXT               -- JSON-encoded list
);

-- Audit trail ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_trail (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                 TEXT NOT NULL,
    user_action               TEXT NOT NULL,
    transaction_ids          TEXT,                -- JSON-encoded list
    analysis_type            TEXT,
    original_currency        TEXT,
    reporting_currency      TEXT,
    exchange_rate             REAL,
    exchange_rate_source   TEXT,
    calculation_results     TEXT,                -- JSON-encoded dict
    ai_recommendation        TEXT,
    risk_level                   TEXT
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_currency ON transactions(currency);
CREATE INDEX IF NOT EXISTS idx_anomalies_txn ON anomalies(transaction_id);
