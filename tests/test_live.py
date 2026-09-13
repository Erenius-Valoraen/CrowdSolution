"""End-to-end checks against Snowflake. Skipped when no connection is configured."""
import unittest
from datetime import date

from factcheck import verdict
from factcheck.catalog import Catalog
from factcheck.engine import check
from factcheck.parse_rules import parse

try:
    from factcheck import db

    db.connection()
    LIVE = True
except Exception:  # noqa: BLE001
    LIVE = False

CAT = Catalog()


@unittest.skipUnless(LIVE, "no Snowflake connection configured")
class LiveTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        db.close()

    def run_claim(self, text, said_on):
        c = parse(text, said_on, CAT)
        return check(c, CAT)

    def test_unemployment_accurate_when_said(self):
        res = self.run_claim("unemployment is 4.1%", date(2025, 1, 15))
        self.assertEqual(res.then.label, "December 2024")
        self.assertEqual(res.verdict, verdict.ACCURATE)

    def test_unemployment_older_figure(self):
        res = self.run_claim("unemployment is 4.3%", date(2025, 1, 15))
        self.assertEqual(res.verdict, verdict.OUTDATED_WHEN_SAID)

    def test_inflation_matches_older_figure(self):
        # May 2025 CPI inflation was 2.38%; "3%" (rounded, so 2.5-3.5) matches February 2025 at 2.81%.
        res = self.run_claim("inflation is 3%", date(2025, 6, 15))
        self.assertEqual(res.then.label, "May 2025")
        self.assertAlmostEqual(res.then.value, 2.38, places=1)
        self.assertEqual(res.verdict, verdict.OUTDATED_WHEN_SAID)

    def test_inflation_wrong(self):
        res = self.run_claim("inflation is 5%", date(2025, 6, 15))
        self.assertEqual(res.verdict, verdict.WRONG)

    def test_state_unemployment_edge_of_tolerance(self):
        res = self.run_claim("Texas unemployment is 4.1%", date(2025, 3, 1))
        self.assertEqual(res.where, "Texas")
        self.assertEqual(res.verdict, verdict.ACCURATE)

    def test_gdp_wrong_then_matches_revision(self):
        res = self.run_claim("GDP grew 2.1% in the first quarter of 2026", date(2026, 6, 1))
        self.assertEqual(res.verdict, verdict.WRONG)
        self.assertTrue(any("revised" in n for n in res.notes))

    def test_jobs_level_with_revision(self):
        res = self.run_claim("total nonfarm jobs were 158.6 million in June 2024", date(2024, 8, 20))
        self.assertIsNotNone(res.then)
        self.assertIsNotNone(res.revised)
        self.assertLess(res.revised.value, res.then.value)

    def test_city_homicides(self):
        res = self.run_claim("Chicago had 568 homicides in 2024", date(2025, 6, 1))
        self.assertEqual(res.then.label, "2024")
        self.assertIn(res.verdict, (verdict.ACCURATE, verdict.WRONG))


if __name__ == "__main__":
    unittest.main()
