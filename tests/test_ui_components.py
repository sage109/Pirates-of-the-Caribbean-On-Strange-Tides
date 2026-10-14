import re
import unittest

from ui.components import (
    app_theme_css, demo_mode_banner_html, feature_card_html, health_score_gauge_svg, hero_html,
    nav_section_label_html, nyasha_watermark_html, step_card_html,
)


class TestUiComponents(unittest.TestCase):
    def test_watermark_contains_brand_and_is_click_through(self):
        out = nyasha_watermark_html()
        self.assertIn("NYASHA AI", out)
        self.assertIn("pointer-events: none", out)

    def test_gauge_is_well_formed_svg(self):
        out = health_score_gauge_svg(72.5, "GOOD")
        self.assertTrue(out.strip().startswith("\n<svg") or "<svg" in out)
        self.assertEqual(out.count("<svg"), 1)
        self.assertIn("</svg>", out)
        self.assertIn("72", out)
        self.assertIn("GOOD", out)

    def test_gauge_clamps_out_of_range_scores(self):
        low = health_score_gauge_svg(-15, "POOR")
        high = health_score_gauge_svg(150, "EXCELLENT")
        self.assertIn(">0<", low)
        self.assertIn(">100<", high)

    def test_gauge_escapes_rating_text(self):
        out = health_score_gauge_svg(50, "<b>hacked</b>")
        self.assertNotIn("<b>hacked</b>", out)

    def test_gauge_valid_numeric_coordinates(self):
        out = health_score_gauge_svg(33, "WEAK")
        # every path's numeric tokens should be finite numbers, not NaN/inf
        nums = re.findall(r"-?\d+\.\d+", out)
        self.assertTrue(nums)
        for n in nums:
            self.assertNotIn("nan", n.lower())
            self.assertNotIn("inf", n.lower())

    def test_demo_banner_renders(self):
        out = demo_mode_banner_html()
        self.assertIn("Demo Mode", out)
        self.assertIn("Moyo Retail", out)

    def test_theme_css_is_a_single_balanced_style_block(self):
        css = app_theme_css()
        self.assertEqual(css.count("<style>"), 1)
        self.assertEqual(css.count("</style>"), 1)
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn("stSidebar", css)

    def test_hero_card_and_step_html_escape_user_visible_text(self):
        for out in (
            hero_html("<b>x</b>", "<i>y</i>", "<script>z</script>"),
            step_card_html(1, "<b>t</b>", "<script>d</script>"),
            feature_card_html("<b>e</b>", "<b>t</b>", "<script>d</script>"),
            nav_section_label_html("<b>s</b>"),
        ):
            self.assertNotIn("<b>", out)
            self.assertNotIn("<script>", out)

    def test_hero_contains_brand_tagline_and_body(self):
        out = hero_html("NYASHA AI", "Smarter Decisions.", "Body text here.")
        for piece in ("NYASHA AI", "Smarter Decisions.", "Body text here."):
            self.assertIn(piece, out)

    def test_step_card_done_state(self):
        pending = step_card_html(2, "Explore", "Go look.")
        done = step_card_html(2, "Explore", "Go look.", done=True)
        self.assertIn(">2<", pending)
        self.assertNotIn("done", pending)
        self.assertIn("done", done)
        self.assertIn("✓", done)

    def test_feature_card_contains_all_parts(self):
        out = feature_card_html("\U0001f4ca", "Dashboard", "Key numbers.")
        for piece in ("\U0001f4ca", "Dashboard", "Key numbers."):
            self.assertIn(piece, out)


if __name__ == "__main__":
    unittest.main()
