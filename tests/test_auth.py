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


if __name__ == "__main__":
    unittest.main()
