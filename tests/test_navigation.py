import ast
import unittest
from pathlib import Path

from locales.translations import LANGUAGE_CODES, t
from services.auth import (
    PAGES_REQUIRING_ACCOUNTANT_OR_ABOVE, PAGES_REQUIRING_ADMIN, User, can_access_page,
)
from ui.navigation import (
    HOME_LABEL, NAV_SECTIONS, all_items, all_labels, find_item, home_cards, visible_sections,
)

APP_PY = Path(__file__).resolve().parent.parent / "app.py"


def _router_keys() -> set[str]:
    """The page labels app.py's PAGES dict routes, read from the source (app.py
    can't be imported in the test environment because it needs streamlit)."""
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t_, "id", None) == "PAGES" for t_ in node.targets):
            return {k.value for k in node.value.keys}
    raise AssertionError("PAGES dict not found in app.py")


class TestNavigationRegistry(unittest.TestCase):
    def test_labels_are_unique(self):
        labels = all_labels()
        self.assertEqual(len(labels), len(set(labels)))

    def test_home_exists_and_is_first(self):
        self.assertEqual(all_labels()[0], HOME_LABEL)

    def test_every_translation_key_exists_in_every_language(self):
        for item in all_items():
            if item.translation_key is None:
                continue
            for lang in LANGUAGE_CODES:
                self.assertNotEqual(
                    t(item.translation_key, lang), item.translation_key,
                    f"{item.label}: missing '{item.translation_key}' for {lang}",
                )

    def test_every_page_has_a_route_in_app_py(self):
        # Home and User Management are routed explicitly in main() (they need `user`).
        expected = set(all_labels()) - {HOME_LABEL, "User Management"}
        self.assertEqual(_router_keys(), expected)

    def test_permission_sets_only_name_real_pages(self):
        labels = set(all_labels())
        self.assertTrue(PAGES_REQUIRING_ADMIN <= labels)
        self.assertTrue(PAGES_REQUIRING_ACCOUNTANT_OR_ABOVE <= labels)

    def test_find_item(self):
        self.assertEqual(find_item("Upload Data").label, "Upload Data")
        self.assertIsNone(find_item("No Such Page"))

    def test_ai_assistant_does_not_use_the_robot_emoji(self):
        # U+1F916 renders as a tiny, inconsistent glyph on some Windows setups.
        self.assertNotIn("\U0001f916", find_item("AI Financial Assistant").emoji)

    def test_home_cards_all_have_descriptions(self):
        for item in home_cards(lambda _label: True):
            self.assertTrue(item.description, item.label)

    def test_sections_are_non_empty_and_titled(self):
        for title, items in NAV_SECTIONS:
            self.assertTrue(title.strip())
            self.assertTrue(items)


class TestRoleVisibility(unittest.TestCase):
    @staticmethod
    def _labels(role: str) -> list[str]:
        user = User("u", role)
        sections = visible_sections(lambda label: can_access_page(user, label))
        return [item.label for _, items in sections for item in items]

    @staticmethod
    def _titles(role: str) -> list[str]:
        user = User("u", role)
        return [title for title, _ in visible_sections(lambda label: can_access_page(user, label))]

    def test_admin_sees_every_page(self):
        self.assertEqual(self._labels("admin"), all_labels())

    def test_viewer_has_no_admin_section_and_no_upload_or_ai(self):
        labels = self._labels("viewer")
        self.assertNotIn("Administration", self._titles("viewer"))
        for restricted in ("Upload Data", "AI Financial Assistant", "Usage History", "Audit Trail", "User Management"):
            self.assertNotIn(restricted, labels)
        self.assertIn("Dashboard", labels)

    def test_accountant_can_upload_but_has_no_admin_pages(self):
        labels = self._labels("accountant")
        self.assertIn("Upload Data", labels)
        self.assertIn("AI Financial Assistant", labels)
        self.assertNotIn("User Management", labels)
        self.assertNotIn("Administration", self._titles("accountant"))

    def test_home_cards_respect_role(self):
        viewer = User("v", "viewer")
        cards = [c.label for c in home_cards(lambda label: can_access_page(viewer, label))]
        self.assertNotIn("Upload Data", cards)
        self.assertNotIn("AI Financial Assistant", cards)
        self.assertIn("Dashboard", cards)
        admin_cards = [c.label for c in home_cards(lambda label: can_access_page(User("a", "admin"), label))]
        self.assertIn("Upload Data", admin_cards)
        # Administration pages are never advertised as cards.
        self.assertNotIn("User Management", admin_cards)


if __name__ == "__main__":
    unittest.main()
