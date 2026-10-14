"""
services/auth.py

Simple, dependency-free login for NYASHA AI. Reuses the same pattern
already used and demo-tested in the sibling investment-dashboard project:
salted PBKDF2-SHA256 password hashes (stdlib `hashlib`, no plaintext ever
stored). There is deliberately NO public "sign up" form: this is a
decision-support tool for a single SME's staff, so only an administrator
can create accounts, from the admin-only "User Management" page.

Roles:
  - "admin"       -- full access to every page, including Usage History,
                      Audit Trail and User Management.
  - "accountant"  -- full analysis access, no Usage History / Audit Trail /
                      User Management (keeps other staff's activity logs
                      private).
  - "viewer"       -- read-only: Dashboard and Financial Analysis only, no
                      Upload Data, AI Assistant, or exports.

No accounts exist until the first admin is provisioned. On a hosted
deployment (Streamlit Community Cloud gives no shell access) the in-app
first-run setup form does that; every later account is then added by an
admin from the User Management page. `scripts/create_user.py` still works
for local/self-hosted use.

Safety rule enforced here (not just in the UI): the system can never be
left without an administrator -- the last remaining admin cannot be
deleted or demoted.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from database.database import fetch_all, transaction

ROLES = ("admin", "accountant", "viewer")
MIN_PASSWORD_LENGTH = 8
PAGES_REQUIRING_ADMIN = {"Usage History", "Audit Trail", "User Management"}
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
    # Usernames are unique ignoring case, so "Jane" and "jane" can't both exist.
    if fetch_all("SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)", (username.strip(),)):
        raise ValueError(f"username {username.strip()!r} already exists")
    password_hash, salt = _hash_password(password)
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (username.strip(), password_hash, salt, role, datetime.now(timezone.utc).isoformat()),
            )
    except sqlite3.IntegrityError as exc:  # lost a race with another create
        raise ValueError(f"username {username.strip()!r} already exists") from exc


def validate_new_password(password: str) -> str | None:
    """Returns a human-readable problem with `password`, or None if it is
    acceptable. Used by the User Management page for every password an
    admin sets (the library-level create_user stays permissive so the CLI
    script and first-run form keep working exactly as before)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.strip() != password:
        return "Password must not start or end with a space."
    return None


def get_user(username: str) -> User | None:
    """Look up an account by exact username (no password check). Returns
    None if it does not exist. Never exposes the hash or salt."""
    ensure_users_table()
    rows = fetch_all("SELECT username, role FROM users WHERE username = ?", (username,))
    return User(username=rows[0]["username"], role=rows[0]["role"]) if rows else None


def list_users() -> list[dict]:
    """All accounts for the admin table: username, role, created_at only --
    password hashes and salts are never returned."""
    ensure_users_table()
    return fetch_all("SELECT username, role, created_at FROM users ORDER BY created_at, username")


def admin_count() -> int:
    ensure_users_table()
    rows = fetch_all("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
    return int(rows[0]["n"]) if rows else 0


def set_role(username: str, new_role: str) -> None:
    """Change an account's role. Raises ValueError for an unknown role, a
    missing user, or an attempt to demote the last remaining admin."""
    if new_role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {new_role!r}")
    user = get_user(username)
    if user is None:
        raise ValueError(f"user {username!r} does not exist")
    if user.role == "admin" and new_role != "admin" and admin_count() <= 1:
        raise ValueError("Cannot demote the last remaining administrator.")
    with transaction() as conn:
        conn.execute("UPDATE users SET role = ? WHERE username = ?", (new_role, username))


def delete_user(username: str) -> None:
    """Remove an account. Raises ValueError for a missing user or an attempt
    to delete the last remaining admin."""
    user = get_user(username)
    if user is None:
        raise ValueError(f"user {username!r} does not exist")
    if user.role == "admin" and admin_count() <= 1:
        raise ValueError("Cannot delete the last remaining administrator.")
    with transaction() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


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
