import unittest

from locales.translations import LANGUAGE_CODES
from ui.login import (
    brand_panel_html, form_heading_html, help_text_html, login_css, login_error_message, minutes_for_display,
    notice_html, setup_error_message, strength_level_text, strength_meter_html,
)

LANGS = list(LANGUAGE_CODES)


class TestLoginHtml(unittest.TestCase):
    def test_brand_panel_escapes_everything(self):
        out = brand_panel_html("A<b>", "tag&line", ["<script>x</script>"], "foot<i>")
        self.assertNotIn("<script>", out)
        self.assertNotIn("<b>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("tag&amp;line", out)

    def test_brand_panel_lists_every_point(self):
        out = brand_panel_html("NYASHA AI", "t", ["one", "two", "three"], "f")
        self.assertEqual(out.count("<li>"), 3)

    def test_no_blank_lines_or_indentation_that_break_markdown(self):
        # Streamlit's markdown ends an HTML block at a blank line and treats
        # 4-space-indented lines as code.
        pieces = [
            brand_panel_html("a", "b", ["c"], "d"), form_heading_html("t", "s"), notice_html("error", "e"),
            strength_meter_html(2, "l", "Fair"), help_text_html("h"),
        ]
        for piece in pieces:
            self.assertNotIn("\n\n", piece)
            self.assertFalse(any(line.startswith("    ") for line in piece.splitlines()))

    def test_notice_kinds_and_roles(self):
        self.assertIn('role="alert"', notice_html("error", "x"))
        self.assertIn('role="status"', notice_html("success", "x"))
        with self.assertRaises(ValueError):
            notice_html("fatal", "x")

    def test_notice_escapes_text(self):
        self.assertIn("&lt;img", notice_html("info", "<img src=x onerror=1>"))

    def test_strength_meter_segments(self):
        for score in range(5):
            out = strength_meter_html(score, "Password strength", "Good")
            self.assertEqual(out.count('class="bar"'), 4)
        self.assertEqual(strength_meter_html(0, "L", "").count("background:#e5e7eb"), 4)
        self.assertEqual(strength_meter_html(3, "L", "Good").count("background:#c9a227"), 3)
        self.assertEqual(strength_meter_html(99, "L", "Strong").count("background:#1f6f4a"), 4)  # clamped

    def test_css_has_no_dollar_signs_or_blank_lines_inside_style(self):
        css = login_css()
        self.assertNotIn("$", css)
        self.assertTrue(css.strip().startswith("<style>") and css.strip().endswith("</style>"))


class TestLoginMessages(unittest.TestCase):
    def test_minutes_rounds_up_never_zero(self):
        self.assertEqual(minutes_for_display(1), 1)
        self.assertEqual(minutes_for_display(60), 1)
        self.assertEqual(minutes_for_display(61), 2)
        self.assertEqual(minutes_for_display(600), 10)

    def test_login_messages_in_every_language(self):
        for lang in LANGS:
            for status in ("missing", "invalid", "locked"):
                msg = login_error_message(status, lang, retry_after=600, attempts_left=1)
                self.assertTrue(msg)
                self.assertNotIn("{", msg)  # all placeholders were filled
        self.assertIn("10", login_error_message("locked", "English", retry_after=600))

    def test_attempts_hint_only_when_few_left(self):
        self.assertNotIn("attempt", login_error_message("invalid", "English", attempts_left=4))
        self.assertIn("1 attempt", login_error_message("invalid", "English", attempts_left=1))

    def test_invalid_message_never_names_which_field_was_wrong(self):
        msg = login_error_message("invalid", "English", attempts_left=3).lower()
        self.assertIn("username or password", msg)

    def test_every_setup_error_code_is_translated(self):
        codes = ["missing", "username_length", "username_chars", "password_short", "password_spaces",
                 "mismatch", "bad_setup_key", "setup_closed", "locked"]
        for lang in LANGS:
            for code in codes:
                msg = setup_error_message(code, lang, retry_after=300)
                self.assertTrue(msg)
                self.assertFalse(msg.startswith("setup_err_"), f"{code}/{lang} untranslated")
                self.assertNotIn("{", msg)

    def test_strength_level_text(self):
        self.assertEqual(strength_level_text(0, "English"), "")
        self.assertEqual(strength_level_text(1, "English"), "Weak")
        self.assertEqual(strength_level_text(4, "English"), "Strong")
        self.assertNotEqual(strength_level_text(4, "Shona"), "Strong")


if __name__ == "__main__":
    unittest.main()
