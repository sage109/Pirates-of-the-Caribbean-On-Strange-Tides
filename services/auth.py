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
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from database.database import fetch_all, log_audit, transaction

ROLES = ("admin", "accountant", "viewer")
MIN_PASSWORD_LENGTH = 8
PAGES_REQUIRING_ADMIN = {"Usage History", "Audit Trail", "User Management"}
PAGES_REQUIRING_ACCOUNTANT_OR_ABOVE = {"Upload Data", "AI Financial Assistant"}

# --- Sign-in protection -------------------------------------------------------
# 5 wrong passwords inside 15 minutes lock that username out for 10 minutes.
# The lock is keyed by the *typed* username (lower-cased), so guessing at names
# that don't exist is throttled exactly like guessing at real ones -- the
# sign-in form can't be used to find out which usernames exist.
MAX_FAILED_ATTEMPTS = 5
FAILURE_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 10 * 60
SETUP_THROTTLE_KEY = "\x00setup"  # can't collide with a username (see validate_username)
DEFAULT_SESSION_TIMEOUT_MINUTES = 30
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username        TEXT PRIMARY KEY,
    password_hash   TEXT NOT NULL,
    salt            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'viewer',
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_throttle (
    key             TEXT PRIMARY KEY,
    failures        INTEGER NOT NULL DEFAULT 0,
    window_start    REAL NOT NULL DEFAULT 0,
    locked_until    REAL NOT NULL DEFAULT 0
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


# Hash of a throw-away password, checked when the username doesn't exist so a
# wrong username and a wrong password take about the same time to reject.
_DUMMY_HASH, _DUMMY_SALT = _hash_password("not-a-real-password", b"\x00" * 16)


def verify_user(username: str, password: str) -> User | None:
    """Checks credentials only (no lockout, no audit log -- see attempt_login
    for the full sign-in flow). The username match ignores case, consistent
    with create_user refusing "Jane" when "jane" exists."""
    ensure_users_table()
    rows = fetch_all("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username.strip(),))
    if not rows:
        _hash_password(password, bytes.fromhex(_DUMMY_SALT))  # equalise timing
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


# --------------------------------------------------------------------------- Validation
def validate_username(username: str) -> str | None:
    """Returns a problem code ("username_length" / "username_chars") or None.
    Applied to the first administrator account; codes (not sentences) so the
    UI can show them in the user's language."""
    name = username.strip()
    if not (USERNAME_MIN_LENGTH <= len(name) <= USERNAME_MAX_LENGTH):
        return "username_length"
    if not _USERNAME_PATTERN.match(name):
        return "username_chars"
    return None


def password_problem(password: str) -> str | None:
    """Same rules as validate_new_password, as a code ("password_short" /
    "password_spaces") for translation."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return "password_short"
    if password.strip() != password:
        return "password_spaces"
    return None


def password_strength(password: str) -> int:
    """0-4 rough strength score for the live meter. Length first, then variety.
    It guides; it never blocks (blocking is password_problem's job)."""
    if not password:
        return 0
    score = 0
    if len(password) >= MIN_PASSWORD_LENGTH:
        score += 1
    if len(password) >= 12:
        score += 1
    kinds = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if kinds >= 3:
        score += 1
    if kinds == 4 and len(password) >= 10:
        score += 1
    return min(score, 4) if len(password) >= MIN_PASSWORD_LENGTH else min(score, 1)


# --------------------------------------------------------------------------- Lockout
def _throttle_key(username: str) -> str:
    return username.strip().lower()[:64]


def next_throttle_state(failures: int, window_start: float, now: float) -> tuple[int, float, float]:
    """Pure rule for recording one more failed attempt at time `now`.
    Returns (failures, window_start, locked_until). Failures older than the
    window are forgotten; reaching MAX_FAILED_ATTEMPTS starts the lockout."""
    if failures == 0 or now - window_start > FAILURE_WINDOW_SECONDS:
        failures, window_start = 0, now
    failures += 1
    locked_until = now + LOCKOUT_SECONDS if failures >= MAX_FAILED_ATTEMPTS else 0.0
    return failures, window_start, locked_until


def lockout_seconds_remaining(username: str, now: float | None = None) -> int:
    """Whole seconds left on this username's lockout (0 = not locked)."""
    ensure_users_table()
    now = time.time() if now is None else now
    rows = fetch_all("SELECT locked_until FROM login_throttle WHERE key = ?", (_throttle_key(username),))
    if not rows:
        return 0
    left = rows[0]["locked_until"] - now
    return math.ceil(left) if left > 0 else 0


def _record_failure(key: str, now: float) -> tuple[int, float]:
    """Persist one failed attempt. Returns (failures_in_window, locked_until)."""
    rows = fetch_all("SELECT failures, window_start FROM login_throttle WHERE key = ?", (key,))
    failures, window_start = (rows[0]["failures"], rows[0]["window_start"]) if rows else (0, 0.0)
    failures, window_start, locked_until = next_throttle_state(failures, window_start, now)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO login_throttle (key, failures, window_start, locked_until) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET failures = excluded.failures, "
            "window_start = excluded.window_start, locked_until = excluded.locked_until",
            (key, failures, window_start, locked_until),
        )
    return failures, locked_until


def _clear_failures(key: str) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM login_throttle WHERE key = ?", (key,))


def _audit(action: str) -> None:
    """Sign-in events go to the same Audit Trail the admin already reviews.
    Never include the password; the typed username is truncated and stripped
    of line breaks so it can't forge log lines."""
    try:
        log_audit(user_action=action, analysis_type="authentication")
    except Exception:  # logging must never block (or crash) a sign-in
        pass


def _safe_name(username: str) -> str:
    return re.sub(r"[\r\n\t]", " ", username.strip())[:40] or "(blank)"


@dataclass
class LoginResult:
    status: str  # "ok" | "invalid" | "locked" | "missing"
    user: User | None = None
    retry_after: int = 0       # seconds, when status == "locked"
    attempts_left: int | None = None  # when status == "invalid"


def attempt_login(username: str, password: str, now: float | None = None) -> LoginResult:
    """The whole sign-in flow: lockout check, credential check, throttle
    bookkeeping and audit logging. The result never says *which* of username
    or password was wrong."""
    now = time.time() if now is None else now
    if not username.strip() or not password:
        return LoginResult("missing")
    key = _throttle_key(username)
    left = lockout_seconds_remaining(username, now)
    if left > 0:
        _audit(f"Sign-in blocked (locked out): {_safe_name(username)}")
        return LoginResult("locked", retry_after=left)
    user = verify_user(username, password)
    if user is not None:
        _clear_failures(key)
        _audit(f"Sign-in: {user.username}")
        return LoginResult("ok", user=user)
    failures, locked_until = _record_failure(key, now)
    if locked_until > now:
        _audit(f"Locked out after {failures} failed sign-ins: {_safe_name(username)}")
        return LoginResult("locked", retry_after=int(LOCKOUT_SECONDS))
    _audit(f"Failed sign-in: {_safe_name(username)}")
    return LoginResult("invalid", attempts_left=MAX_FAILED_ATTEMPTS - failures)


def log_sign_out(user: User) -> None:
    _audit(f"Sign-out: {user.username}")


def log_session_expired(user: User) -> None:
    _audit(f"Signed out after inactivity: {user.username}")


# --------------------------------------------------------------------------- First-run setup key
def configured_setup_key() -> str | None:
    """The owner's setup key, from the NYASHA_SETUP_KEY environment variable
    (on Streamlit Community Cloud: a top-level entry in the app's Secrets).
    None when unset."""
    value = os.environ.get("NYASHA_SETUP_KEY", "").strip()
    return value or None


def setup_key_ok(provided: str, expected: str | None = None) -> bool:
    expected = configured_setup_key() if expected is None else expected
    if not expected:
        return True  # no key configured -> open setup (the UI warns about it)
    return hmac.compare_digest(provided.strip().encode("utf-8"), expected.encode("utf-8"))


@dataclass
class SetupResult:
    ok: bool
    error: str | None = None   # a code the UI translates
    retry_after: int = 0


def attempt_setup(username: str, password: str, confirm: str, setup_key: str = "",
                  now: float | None = None) -> SetupResult:
    """Creates the first administrator. Refuses when accounts already exist
    (so a stale or replayed form can't mint a second admin), when the setup
    key is wrong (throttled like passwords), or when the details are weak."""
    now = time.time() if now is None else now
    if user_count() > 0:
        return SetupResult(False, "setup_closed")
    if not username.strip() or not password:
        return SetupResult(False, "missing")
    if (problem := validate_username(username)) is not None:
        return SetupResult(False, problem)
    if (problem := password_problem(password)) is not None:
        return SetupResult(False, problem)
    if password != confirm:
        return SetupResult(False, "mismatch")
    if configured_setup_key():
        left = lockout_seconds_remaining(SETUP_THROTTLE_KEY, now)
        if left > 0:
            return SetupResult(False, "locked", retry_after=left)
        if not setup_key_ok(setup_key):
            _, locked_until = _record_failure(SETUP_THROTTLE_KEY, now)
            _audit("Failed first-run setup: wrong setup key")
            if locked_until > now:
                return SetupResult(False, "locked", retry_after=int(LOCKOUT_SECONDS))
            return SetupResult(False, "bad_setup_key")
        _clear_failures(SETUP_THROTTLE_KEY)
    try:
        create_user(username, password, role="admin")
    except ValueError:
        return SetupResult(False, "setup_closed")
    _audit(f"First administrator created: {username.strip()}")
    return SetupResult(True)


# --------------------------------------------------------------------------- Idle timeout
def session_timeout_seconds() -> int:
    """Idle limit from NYASHA_SESSION_TIMEOUT_MINUTES (default 30; 0 turns it
    off; junk values fall back to the default)."""
    raw = os.environ.get("NYASHA_SESSION_TIMEOUT_MINUTES", "").strip()
    try:
        minutes = float(raw) if raw else DEFAULT_SESSION_TIMEOUT_MINUTES
    except ValueError:
        minutes = DEFAULT_SESSION_TIMEOUT_MINUTES
    return max(0, int(minutes * 60))


def session_expired(last_active: float | None, now: float, timeout: int) -> bool:
    """True when the user has been idle longer than `timeout` seconds.
    Checked on the next interaction (a browser tab that nobody touches isn't
    polled), which is when it matters: before any data is shown again."""
    if timeout <= 0 or last_active is None:
        return False
    return now - last_active > timeout
