import unittest

from locales.translations import LANGUAGE_CODES, coverage_report, t


class TestTranslations(unittest.TestCase):
    def test_known_key_translates_in_all_languages(self):
        for lang in LANGUAGE_CODES:
            result = t("nav_dashboard", lang)
            self.assertTrue(result)
            self.assertNotEqual(result, "nav_dashboard")

    def test_unknown_key_falls_back_to_key_itself(self):
        self.assertEqual(t("does_not_exist", "English"), "does_not_exist")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(t("nav_home", "Klingon"), t("nav_home", "English"))

    def test_no_missing_translations(self):
        missing = coverage_report()
        for code, keys in missing.items():
            self.assertEqual(keys, [], f"Missing '{code}' translations for: {keys}")


if __name__ == "__main__":
    unittest.main()
