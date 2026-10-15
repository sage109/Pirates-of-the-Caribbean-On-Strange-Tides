import re
import unittest

from ui.charts import (
    CHART_FRAME_HEIGHT, ForecastPoint as P, chart_page_html, days_until_zero, forecast_chart_svg, forecast_insight,
    nice_ticks, outlook_status,
)


def series(start, end, statuses=("healthy",) * 5):
    days = [0, 7, 14, 30, 60, 90]
    pts = [P(0, start)]
    for d, s in zip(days[1:], statuses):
        pts.append(P(d, start + (end - start) * d / 90, s))
    return pts


DECLINING = series(40828.53, 31910.44)            # the demo dataset's real forecast, roughly
CROSSING = series(12000, -9000, ("healthy", "watch", "watch", "shortage", "shortage"))
RISING = series(8000, 26500, ("watch", "healthy", "healthy", "healthy", "healthy"))
NEGATIVE = series(-6000, -1500, ("shortage",) * 5)


class TestNiceTicks(unittest.TestCase):
    def test_covers_range_with_even_steps(self):
        ticks = nice_ticks(0, 45000)
        self.assertLessEqual(ticks[0], 0)
        self.assertGreaterEqual(ticks[-1], 45000)
        steps = {round(b - a, 6) for a, b in zip(ticks, ticks[1:])}
        self.assertEqual(len(steps), 1)
        self.assertLessEqual(len(ticks), 10)

    def test_range_spanning_zero_includes_zero_tick(self):
        self.assertIn(0, nice_ticks(-9000, 12000))

    def test_degenerate_and_reversed_ranges(self):
        self.assertGreaterEqual(len(nice_ticks(5, 5)), 2)
        self.assertGreaterEqual(len(nice_ticks(0, 0)), 2)
        self.assertEqual(nice_ticks(10, 0), nice_ticks(0, 10))


class TestDaysUntilZero(unittest.TestCase):
    def test_interpolates_the_crossing(self):
        self.assertAlmostEqual(days_until_zero([P(0, 100), P(10, -100)]), 5.0)

    def test_never_crossing_or_starting_negative_is_none(self):
        self.assertIsNone(days_until_zero(DECLINING))
        self.assertIsNone(days_until_zero(RISING))
        self.assertIsNone(days_until_zero(NEGATIVE))

    def test_touching_zero_exactly_then_dropping(self):
        self.assertAlmostEqual(days_until_zero([P(0, 100), P(10, 0), P(20, -50)]), 10.0)

    def test_input_order_does_not_matter(self):
        self.assertAlmostEqual(days_until_zero(list(reversed([P(0, 100), P(10, -100)]))), 5.0)


class TestInsight(unittest.TestCase):
    def test_declining_with_long_runway(self):
        ins = forecast_insight(DECLINING, "USD")
        self.assertIn("falls from USD 40,829", ins.headline)
        self.assertIn("USD 31,910", ins.headline)
        self.assertIn("(-22%)", ins.headline)
        self.assertIn("more than a year", ins.headline)
        self.assertIsNone(ins.runway_days)
        self.assertEqual(ins.level, "ok")

    def test_declining_with_short_runway_gives_days(self):
        ins = forecast_insight(series(10000, 5000), "USD")   # ~55.6/day -> ~180 days
        self.assertIn("about 180 days", ins.headline)

    def test_running_out_inside_the_forecast(self):
        ins = forecast_insight(CROSSING, "USD")
        self.assertIn("runs out in about 51 days", ins.headline)
        self.assertAlmostEqual(ins.runway_days, 51.4, places=1)
        self.assertEqual(ins.level, "risk")

    def test_rising(self):
        ins = forecast_insight(RISING, "USD")
        self.assertIn("grows from USD 8,000", ins.headline)
        self.assertIn("(+231%)", ins.headline)
        self.assertEqual(ins.level, "ok")   # follows the 90-day status, not the worst earlier one

    def test_flat(self):
        self.assertIn("roughly flat", forecast_insight(series(5000, 5000), "USD").headline)

    def test_already_negative(self):
        ins = forecast_insight(NEGATIVE, "USD")
        self.assertIn("already negative", ins.headline)
        self.assertIn("improving", ins.headline)
        self.assertEqual(ins.level, "risk")
        self.assertIn("getting worse", forecast_insight(series(-1000, -4000), "USD").headline)

    def test_level_follows_the_90_day_status(self):
        self.assertEqual(forecast_insight(series(9000, 8000, ("healthy",) * 4 + ("watch",)), "USD").level, "watch")
        self.assertEqual(forecast_insight(series(9000, 8000, ("healthy",) * 4 + ("shortage",)), "USD").level, "risk")
        self.assertEqual(outlook_status(RISING), "healthy")

    def test_too_little_data(self):
        ins = forecast_insight([P(0, 100)], "USD")
        self.assertIn("Not enough data", ins.headline)
        self.assertEqual(ins.level, "watch")

    def test_never_contains_a_dollar_sign(self):
        for pts in (DECLINING, CROSSING, RISING, NEGATIVE):
            self.assertNotIn("$", forecast_insight(pts, "USD").headline)


class TestChartSvg(unittest.TestCase):
    def svg(self, pts=DECLINING, cur="USD"):
        return forecast_chart_svg(pts, cur)

    def test_is_one_svg_inside_a_div(self):
        out = self.svg()
        self.assertTrue(out.startswith('<div class="nyasha-chart"><svg'))
        self.assertTrue(out.endswith("</svg></div>"))
        self.assertEqual(out.count("<svg"), 1)

    def test_safe_for_streamlit_markdown(self):
        for pts in (DECLINING, CROSSING, RISING, NEGATIVE):
            out = self.svg(pts)
            self.assertNotIn("$", out)                                   # would start LaTeX
            self.assertFalse(any(not line.strip() for line in out.split("\n")))   # blank line ends an HTML block

    def test_labels_every_point_and_has_tooltips(self):
        out = self.svg(RISING)
        for p in RISING:
            self.assertIn(f">{p.balance:,.0f}</text>", out)
        self.assertEqual(out.count("<title>"), len(RISING))
        self.assertIn("Today", out)
        self.assertIn("Day 90", out)

    def test_runway_marker_only_when_cash_runs_out(self):
        self.assertIn("Cash runs out in about 51 days", self.svg(CROSSING))
        for pts in (DECLINING, RISING, NEGATIVE):
            self.assertNotIn("Cash runs out", self.svg(pts))

    def test_escapes_the_currency(self):
        out = self.svg(DECLINING, "<b>x</b>")
        self.assertNotIn("<b>", out)
        self.assertIn("&lt;b&gt;", out)

    def test_coordinates_are_finite(self):
        for pts in (DECLINING, CROSSING, RISING, NEGATIVE, series(0, 0), series(1e9, 5e8)):
            out = self.svg(pts).lower()
            self.assertIsNone(re.search(r"(?<![a-z])(nan|inf)(?![a-z])", out))

    def test_every_url_reference_resolves_to_an_id(self):
        out = self.svg(CROSSING)
        ids = set(re.findall(r'id="([^"]+)"', out))
        refs = set(re.findall(r"url\(#([^)]+)\)", out))
        self.assertTrue(refs)
        self.assertTrue(refs <= ids)

    def test_two_different_charts_do_not_share_element_ids(self):
        ids_a = set(re.findall(r'id="([^"]+)"', self.svg(DECLINING)))
        ids_b = set(re.findall(r'id="([^"]+)"', self.svg(CROSSING)))
        self.assertFalse(ids_a & ids_b)
        self.assertEqual(ids_a, set(re.findall(r'id="([^"]+)"', self.svg(DECLINING))))   # but deterministic

    def test_needs_two_points(self):
        self.assertEqual(forecast_chart_svg([], "USD"), "")
        self.assertEqual(forecast_chart_svg([P(0, 1)], "USD"), "")

    def test_page_wrapper_is_standalone_and_self_contained(self):
        doc = chart_page_html(self.svg(CROSSING))
        self.assertTrue(doc.startswith("<!doctype html>"))
        self.assertEqual(doc.count("<svg"), 1)
        self.assertIn("100vh", doc)
        self.assertNotIn("src=", doc)        # nothing external to load inside the iframe
        self.assertNotIn("href=", doc)
        self.assertNotIn("<script", doc)
        self.assertGreater(CHART_FRAME_HEIGHT, 300)

    def test_svg_is_top_aligned_when_scaled(self):
        self.assertIn('preserveAspectRatio="xMidYMin meet"', self.svg())

    def test_marker_colours_follow_status(self):
        out = self.svg(CROSSING)
        for colour in ("#3f7d3f", "#c9a227", "#b3261e"):
            self.assertIn(colour, out)


if __name__ == "__main__":
    unittest.main()
