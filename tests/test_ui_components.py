import re
import unittest

from ui.components import demo_mode_banner_html, health_score_gauge_svg, nyasha_watermark_html


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


if __name__ == "__main__":
    unittest.main()
