import os
import unittest

from database.database import DB_PATH, reset_db


class TestAuth(unittest.TestCase):
    """`services.auth` binds its DB helpers' default db_path at import time,
    so (like the rest of the app) it always targets database/DB_PATH. We
    reset that DB fully before/after every test rather than pointing at a
    separate file, keeping this consistent with how the app itself runs
    and leaving no test data behind afterwards."""

    def setUp(self):
        reset_db()

    def tearDown(self):
        reset_db()
        if DB_PATH.exists():
            DB_PATH.unlink()

    def test_create_and_verify_correct_password(self):
        from services.auth import create_user, verify_user
        create_user("jane", "correct-horse-battery-staple", role="accountant")
        user = verify_user("jane", "correct-horse-battery-staple")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "jane")
        self.assertEqual(user.role, "accountant")

    def test_verify_wrong_password_fails(self):
        from services.auth import create_user, verify_user
        create_user("jane", "correct-password")
        self.assertIsNone(verify_user("jane", "wrong-password"))

    def test_verify_nonexistent_user_fails(self):
        from services.auth import verify_user
        self.assertIsNone(verify_user("ghost", "anything"))

    def test_password_never_stored_in_plaintext(self):
        from database.database import fetch_all
        from services.auth import create_user
        create_user("jane", "super-secret-password")
        row = fetch_all("SELECT * FROM users WHERE username = ?", ("jane",))[0]
        self.assertNotEqual(row["password_hash"], "super-secret-password")
        self.assertNotIn("super-secret-password", row["password_hash"])

    def test_update_password_invalidates_old_password(self):
        from services.auth import create_user, update_password, verify_user
        create_user("jane", "old-password")
        self.assertTrue(update_password("jane", "new-password"))
        self.assertIsNone(verify_user("jane", "old-password"))
        self.assertIsNotNone(verify_user("jane", "new-password"))

    def test_update_password_for_missing_user_returns_false(self):
        from services.auth import update_password
        self.assertFalse(update_password("ghost", "whatever"))

    def test_invalid_role_rejected(self):
        from services.auth import create_user
        with self.assertRaises(ValueError):
            create_user("jane", "password", role="superuser")

    def test_admin_can_access_every_page(self):
        from services.auth import User, can_access_page
        admin = User(username="a", role="admin")
        for page in ("Usage History", "Audit Trail", "Upload Data", "Dashboard"):
            self.assertTrue(can_access_page(admin, page))

    def test_viewer_cannot_access_restricted_pages(self):
        from services.auth import User, can_access_page
        viewer = User(username="v", role="viewer")
        self.assertFalse(can_access_page(viewer, "Usage History"))
        self.assertFalse(can_access_page(viewer, "Upload Data"))
        self.assertTrue(can_access_page(viewer, "Dashboard"))

    def test_accountant_can_upload_but_not_see_audit_trail(self):
        from services.auth import User, can_access_page
        accountant = User(username="c", role="accountant")
        self.assertTrue(can_access_page(accountant, "Upload Data"))
        self.assertFalse(can_access_page(accountant, "Audit Trail"))

    def test_user_count_reflects_created_users(self):
        from services.auth import create_user, user_count
        self.assertEqual(user_count(), 0)
        create_user("first-admin", "password", role="admin")
        self.assertEqual(user_count(), 1)

    # ------------------------------------------------------------------
    # User management (admin-only page) -- account helpers
    # ------------------------------------------------------------------
    def test_duplicate_username_rejected(self):
        from services.auth import create_user, user_count
        create_user("jane", "password-one")
        with self.assertRaises(ValueError):
            create_user("jane", "password-two")
        self.assertEqual(user_count(), 1)

    def test_duplicate_username_rejected_ignoring_case(self):
        from services.auth import create_user
        create_user("Jane", "password-one")
        with self.assertRaises(ValueError):
            create_user("jane", "password-two")

    def test_get_user_returns_user_or_none(self):
        from services.auth import create_user, get_user
        create_user("jane", "password-one", role="accountant")
        user = get_user("jane")
        self.assertEqual((user.username, user.role), ("jane", "accountant"))
        self.assertIsNone(get_user("ghost"))

    def test_list_users_never_exposes_credentials(self):
        from services.auth import create_user, list_users
        create_user("admin1", "password-one", role="admin")
        create_user("jane", "password-two", role="viewer")
        rows = list_users()
        self.assertEqual({r["username"] for r in rows}, {"admin1", "jane"})
        for row in rows:
            self.assertEqual(set(row), {"username", "role", "created_at"})

    def test_set_role_changes_role(self):
        from services.auth import create_user, get_user, set_role
        create_user("admin1", "password-one", role="admin")
        create_user("jane", "password-two", role="viewer")
        set_role("jane", "accountant")
        self.assertEqual(get_user("jane").role, "accountant")

    def test_set_role_rejects_bad_role_and_missing_user(self):
        from services.auth import create_user, set_role
        create_user("jane", "password-one", role="admin")
        with self.assertRaises(ValueError):
            set_role("jane", "superuser")
        with self.assertRaises(ValueError):
            set_role("ghost", "viewer")

    def test_cannot_demote_last_admin(self):
        from services.auth import create_user, get_user, set_role
        create_user("only-admin", "password-one", role="admin")
        with self.assertRaises(ValueError):
            set_role("only-admin", "viewer")
        self.assertEqual(get_user("only-admin").role, "admin")

    def test_can_demote_an_admin_when_another_admin_exists(self):
        from services.auth import admin_count, create_user, get_user, set_role
        create_user("admin1", "password-one", role="admin")
        create_user("admin2", "password-two", role="admin")
        set_role("admin2", "viewer")
        self.assertEqual(get_user("admin2").role, "viewer")
        self.assertEqual(admin_count(), 1)

    def test_delete_user_removes_account_and_blocks_login(self):
        from services.auth import create_user, delete_user, get_user, verify_user
        create_user("admin1", "password-one", role="admin")
        create_user("jane", "password-two")
        delete_user("jane")
        self.assertIsNone(get_user("jane"))
        self.assertIsNone(verify_user("jane", "password-two"))

    def test_cannot_delete_last_admin(self):
        from services.auth import create_user, delete_user, get_user
        create_user("only-admin", "password-one", role="admin")
        create_user("jane", "password-two")
        with self.assertRaises(ValueError):
            delete_user("only-admin")
        self.assertIsNotNone(get_user("only-admin"))

    def test_can_delete_an_admin_when_another_admin_exists(self):
        from services.auth import create_user, delete_user, get_user
        create_user("admin1", "password-one", role="admin")
        create_user("admin2", "password-two", role="admin")
        delete_user("admin2")
        self.assertIsNone(get_user("admin2"))

    def test_delete_missing_user_raises(self):
        from services.auth import delete_user
        with self.assertRaises(ValueError):
            delete_user("ghost")

    def test_validate_new_password(self):
        from services.auth import MIN_PASSWORD_LENGTH, validate_new_password
        self.assertIsNotNone(validate_new_password("short"))
        self.assertIsNotNone(validate_new_password(" " + "x" * MIN_PASSWORD_LENGTH))
        self.assertIsNone(validate_new_password("x" * MIN_PASSWORD_LENGTH))

    def test_user_management_page_is_admin_only(self):
        from services.auth import User, can_access_page
        self.assertTrue(can_access_page(User("a", "admin"), "User Management"))
        self.assertFalse(can_access_page(User("c", "accountant"), "User Management"))
        self.assertFalse(can_access_page(User("v", "viewer"), "User Management"))


if __name__ == "__main__":
    unittest.main()


class TestSignInProtection(unittest.TestCase):
    def setUp(self):
        reset_db()
        for var in ("NYASHA_SETUP_KEY", "NYASHA_SESSION_TIMEOUT_MINUTES"):
            os.environ.pop(var, None)

    def tearDown(self):
        reset_db()
        if DB_PATH.exists():
            DB_PATH.unlink()
        for var in ("NYASHA_SETUP_KEY", "NYASHA_SESSION_TIMEOUT_MINUTES"):
            os.environ.pop(var, None)

    def _audit_actions(self):
        from database.database import fetch_all
        return [r["user_action"] for r in fetch_all("SELECT user_action FROM audit_trail ORDER BY id")]

    def test_login_ignores_username_case_and_keeps_stored_spelling(self):
        from services.auth import attempt_login, create_user
        create_user("Jane", "good-password")
        result = attempt_login("  jANE ", "good-password")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.user.username, "Jane")

    def test_blank_fields_are_missing_not_a_failed_attempt(self):
        from services.auth import attempt_login, lockout_seconds_remaining
        self.assertEqual(attempt_login("", "x").status, "missing")
        self.assertEqual(attempt_login("jane", "").status, "missing")
        self.assertEqual(lockout_seconds_remaining("jane"), 0)

    def test_wrong_password_and_unknown_user_look_identical(self):
        from services.auth import attempt_login, create_user
        create_user("jane", "good-password")
        a = attempt_login("jane", "wrong", now=1000)
        b = attempt_login("ghost", "wrong", now=1000)
        self.assertEqual((a.status, a.attempts_left), (b.status, b.attempts_left))
        self.assertEqual(a.status, "invalid")

    def test_lockout_after_max_failures_even_for_correct_password(self):
        from services.auth import MAX_FAILED_ATTEMPTS, LOCKOUT_SECONDS, attempt_login, create_user
        create_user("jane", "good-password")
        for i in range(MAX_FAILED_ATTEMPTS - 1):
            r = attempt_login("jane", "wrong", now=1000 + i)
            self.assertEqual(r.status, "invalid")
            self.assertEqual(r.attempts_left, MAX_FAILED_ATTEMPTS - 1 - i)
        last = attempt_login("jane", "wrong", now=1010)
        self.assertEqual(last.status, "locked")
        self.assertEqual(last.retry_after, LOCKOUT_SECONDS)
        blocked = attempt_login("jane", "good-password", now=1011)
        self.assertEqual(blocked.status, "locked")
        self.assertIsNone(blocked.user)

    def test_lockout_applies_to_unknown_usernames_and_ignores_case(self):
        from services.auth import MAX_FAILED_ATTEMPTS, attempt_login
        for i in range(MAX_FAILED_ATTEMPTS):
            attempt_login("Ghost" if i % 2 else "ghost", "x" * 9, now=1000 + i)
        self.assertEqual(attempt_login("GHOST", "x" * 9, now=1020).status, "locked")

    def test_lockout_expires(self):
        from services.auth import LOCKOUT_SECONDS, MAX_FAILED_ATTEMPTS, attempt_login, create_user, lockout_seconds_remaining
        create_user("jane", "good-password")
        for i in range(MAX_FAILED_ATTEMPTS):
            attempt_login("jane", "wrong", now=1000 + i)
        end = 1000 + MAX_FAILED_ATTEMPTS - 1 + LOCKOUT_SECONDS
        self.assertGreater(lockout_seconds_remaining("jane", now=end - 5), 0)
        self.assertEqual(lockout_seconds_remaining("jane", now=end + 1), 0)
        self.assertEqual(attempt_login("jane", "good-password", now=end + 1).status, "ok")

    def test_old_failures_fall_out_of_the_window(self):
        from services.auth import FAILURE_WINDOW_SECONDS, MAX_FAILED_ATTEMPTS, attempt_login, create_user
        create_user("jane", "good-password")
        for i in range(MAX_FAILED_ATTEMPTS - 1):
            attempt_login("jane", "wrong", now=1000 + i)
        later = 1000 + FAILURE_WINDOW_SECONDS + 60
        r = attempt_login("jane", "wrong", now=later)
        self.assertEqual(r.status, "invalid")
        self.assertEqual(r.attempts_left, MAX_FAILED_ATTEMPTS - 1)

    def test_success_resets_the_failure_count(self):
        from services.auth import MAX_FAILED_ATTEMPTS, attempt_login, create_user
        create_user("jane", "good-password")
        for i in range(MAX_FAILED_ATTEMPTS - 1):
            attempt_login("jane", "wrong", now=1000 + i)
        self.assertEqual(attempt_login("jane", "good-password", now=1100).status, "ok")
        self.assertEqual(attempt_login("jane", "wrong", now=1101).attempts_left, MAX_FAILED_ATTEMPTS - 1)

    def test_next_throttle_state_is_pure_and_correct(self):
        from services.auth import FAILURE_WINDOW_SECONDS, LOCKOUT_SECONDS, MAX_FAILED_ATTEMPTS, next_throttle_state
        self.assertEqual(next_throttle_state(0, 0, 500), (1, 500, 0.0))
        f, w, lock = next_throttle_state(MAX_FAILED_ATTEMPTS - 1, 500, 600)
        self.assertEqual((f, w, lock), (MAX_FAILED_ATTEMPTS, 500, 600 + LOCKOUT_SECONDS))
        self.assertEqual(next_throttle_state(3, 500, 500 + FAILURE_WINDOW_SECONDS + 1)[0], 1)

    def test_events_are_audited_without_passwords(self):
        from services.auth import attempt_login, create_user
        create_user("jane", "good-password")
        attempt_login("jane", "SECRET-WRONG-PW", now=1000)
        attempt_login("jane", "good-password", now=1001)
        actions = self._audit_actions()
        self.assertTrue(any(a.startswith("Failed sign-in: jane") for a in actions))
        self.assertTrue(any(a.startswith("Sign-in: jane") for a in actions))
        self.assertFalse(any("SECRET-WRONG-PW" in a or "good-password" in a for a in actions))

    def test_audited_username_cannot_forge_log_lines(self):
        from services.auth import attempt_login
        attempt_login("evil\nSign-in: admin" + "x" * 100, "pw-pw-pw-pw", now=1000)
        for action in self._audit_actions():
            self.assertNotIn("\n", action)
            self.assertLess(len(action), 90)

    def test_validate_username(self):
        from services.auth import validate_username
        self.assertEqual(validate_username("ab"), "username_length")
        self.assertEqual(validate_username("x" * 33), "username_length")
        self.assertEqual(validate_username("has space"), "username_chars")
        self.assertEqual(validate_username("-leading"), "username_chars")
        self.assertIsNone(validate_username("moyo.nyasha_1"))

    def test_password_problem_codes_match_validate_new_password(self):
        from services.auth import MIN_PASSWORD_LENGTH, password_problem
        self.assertEqual(password_problem("short"), "password_short")
        self.assertEqual(password_problem(" " + "x" * MIN_PASSWORD_LENGTH), "password_spaces")
        self.assertIsNone(password_problem("x" * MIN_PASSWORD_LENGTH))

    def test_password_strength_is_monotonic_guidance(self):
        from services.auth import password_strength
        self.assertEqual(password_strength(""), 0)
        self.assertLessEqual(password_strength("abc"), 1)
        self.assertLess(password_strength("abcdefgh"), password_strength("Abcdefgh12!x"))
        self.assertEqual(password_strength("Tr0ub4dor&3-horse"), 4)

    def test_setup_creates_admin_and_audits(self):
        from services.auth import attempt_setup, get_user
        r = attempt_setup("nyasha", "a-strong-pass", "a-strong-pass")
        self.assertTrue(r.ok)
        self.assertEqual(get_user("nyasha").role, "admin")
        self.assertTrue(any(a.startswith("First administrator created") for a in self._audit_actions()))

    def test_setup_validation_codes(self):
        from services.auth import attempt_setup
        self.assertEqual(attempt_setup("", "x", "x").error, "missing")
        self.assertEqual(attempt_setup("a b", "a-strong-pass", "a-strong-pass").error, "username_chars")
        self.assertEqual(attempt_setup("nyasha", "short", "short").error, "password_short")
        self.assertEqual(attempt_setup("nyasha", "a-strong-pass", "different-pass").error, "mismatch")

    def test_setup_refused_once_an_account_exists(self):
        from services.auth import attempt_setup, create_user
        create_user("first", "a-strong-pass", role="admin")
        self.assertEqual(attempt_setup("second", "a-strong-pass", "a-strong-pass").error, "setup_closed")

    def test_setup_key_required_when_configured(self):
        from services.auth import attempt_setup, user_count
        os.environ["NYASHA_SETUP_KEY"] = "owner-secret"
        self.assertEqual(attempt_setup("nyasha", "a-strong-pass", "a-strong-pass", "").error, "bad_setup_key")
        self.assertEqual(attempt_setup("nyasha", "a-strong-pass", "a-strong-pass", "wrong").error, "bad_setup_key")
        self.assertEqual(user_count(), 0)
        self.assertTrue(attempt_setup("nyasha", "a-strong-pass", "a-strong-pass", " owner-secret ").ok)
        self.assertEqual(user_count(), 1)

    def test_setup_key_guessing_is_locked_out(self):
        from services.auth import MAX_FAILED_ATTEMPTS, attempt_setup, user_count
        os.environ["NYASHA_SETUP_KEY"] = "owner-secret"
        results = [attempt_setup("nyasha", "a-strong-pass", "a-strong-pass", f"guess{i}", now=1000 + i)
                   for i in range(MAX_FAILED_ATTEMPTS)]
        self.assertEqual(results[-1].error, "locked")
        right = attempt_setup("nyasha", "a-strong-pass", "a-strong-pass", "owner-secret", now=1100)
        self.assertEqual(right.error, "locked")
        self.assertEqual(user_count(), 0)

    def test_setup_key_ok_without_configured_key(self):
        from services.auth import setup_key_ok
        self.assertTrue(setup_key_ok("anything", expected=None))
        self.assertFalse(setup_key_ok("nope", expected="yes"))
        self.assertTrue(setup_key_ok("yes", expected="yes"))

    def test_session_timeout_settings(self):
        from services.auth import DEFAULT_SESSION_TIMEOUT_MINUTES, session_expired, session_timeout_seconds
        self.assertEqual(session_timeout_seconds(), DEFAULT_SESSION_TIMEOUT_MINUTES * 60)
        os.environ["NYASHA_SESSION_TIMEOUT_MINUTES"] = "5"
        self.assertEqual(session_timeout_seconds(), 300)
        os.environ["NYASHA_SESSION_TIMEOUT_MINUTES"] = "0"
        self.assertEqual(session_timeout_seconds(), 0)
        os.environ["NYASHA_SESSION_TIMEOUT_MINUTES"] = "junk"
        self.assertEqual(session_timeout_seconds(), DEFAULT_SESSION_TIMEOUT_MINUTES * 60)
        self.assertFalse(session_expired(100, 10_000, 0))
        self.assertFalse(session_expired(None, 10_000, 60))
        self.assertFalse(session_expired(100, 150, 60))
        self.assertTrue(session_expired(100, 200, 60))
