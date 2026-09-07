"""
services/auth.py

Simple, dependency-free login for NYASHA AI. Reuses the same pattern
already used and demo-tested in the sibling investment-dashboard project:
salted PBKDF2-SHA256 password hashes (stdlib `hashlib`, no plaintext ever
stored), accounts provisioned out-of-band via a script rather than an
in-app "sign up" form (this is a course-assessed decision-support tool
for a single SME's staff, not a public product).

Roles:
  - "admin"       -- full access to every page, including Usage History
                      and Audit Trail.
  - "accountant"  -- full analysis access, no Usage History / Audit Trail
                      (keeps other staff's activity logs private).
  - "viewer"       -- read-only: Dashboard and Financial Analysis only, no
                      Upload Data, AI Assistant, or exports.

No accounts exist until the first admin is provisioned via
`scripts/create_user.py` (mirroring the investment dashboard's approach:
create_user.py cannot reach a hosted deployment's ephemeral database, so
this in-app first-run setup form below is what actually provisions the
first account in production, exactly as documented in the investment
dashboard project's fix for the same constraint).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from database.database import fetch_all, transaction

ROLES = ("admin", "accountant", "viewer")
PAGES_REQUIRING_ADMIN = {"Usage History", "Audit Trail"}
PAGES_REQUIRING_ACCOUNTANT_OR_ABOVE = {"Upload Data", "AI Financial Assistant"}

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username        TEXT PRIMARY KEY,
    password_hash   TEXT NOT NULL,
    salt            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'viewer',
    created_at      TEXT NOT NULL
);
"""


@dataclass
class User:
    username: str
    role: str


def ensure_users_table() -> None:
    """Idempotent -- safe to call on every app start alongside init_db()."""
    with transaction() as conn:
        conn.executescript(USERS_SCHEMA)


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return digest.hex(), salt.hex()


def user_count() -> int:
    ensure_users_table()
    rows = fetch_all("SELECT COUNT(*) AS n FROM users")
    return int(rows[0]["n"]) if rows else 0


def create_user(username: str, password: str, role: str = "viewer") -> None:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    if not username.strip() or not password:
        raise ValueError("username and password are both required")
    ensure_users_table()
    password_hash, salt = _hash_password(password)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (username.strip(), password_hash, salt, role, datetime.now(timezone.utc).isoformat()),
        )


def verify_user(username: str, password: str) -> User | None:
    ensure_users_table()
    rows = fetch_all("SELECT * FROM users WHERE username = ?", (username.strip(),))
    if not rows:
        return None
    row = rows[0]
    expected_hash, _ = _hash_password(password, bytes.fromhex(row["salt"]))
    if not hmac.compare_digest(expected_hash, row["password_hash"]):
        return None
    return User(username=row["username"], role=row["role"])


def update_password(username: str, new_password: str) -> bool:
    """Returns False if the user doesn't exist. Invalidates the old
    password entirely (fresh salt), matching the investment dashboard's
    verified behaviour."""
    ensure_users_table()
    if not fetch_all("SELECT 1 FROM users WHERE username = ?", (username.strip(),)):
        return False
    password_hash, salt = _hash_password(new_password)
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
            (password_hash, salt, username.strip()),
        )
    return True


def can_access_page(user: User, page_label: str) -> bool:
    """page_label should be the sidebar label with any leading emoji
    already stripped, e.g. 'Usage History' not '📚 Usage History'."""
    if user.role == "admin":
        return True
    if page_label in PAGES_REQUIRING_ADMIN:
        return False
    if page_label in PAGES_REQUIRING_ACCOUNTANT_OR_ABOVE:
        return user.role == "accountant"
    return True  # Dashboard, Financial Analysis, etc. -- open to all logged-in roles
