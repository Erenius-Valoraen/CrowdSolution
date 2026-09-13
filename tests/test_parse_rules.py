import unittest
from datetime import date

from legit.stats.catalog import Catalog
from legit.stats.models import Period
from legit.stats.parse_rules import parse

CAT = Catalog()


class ParseRulesTest(unittest.TestCase):
    def p(self, text, said_on=date(2025, 6, 15)):
        return parse(text, said_on, CAT)

    def test_unemployment_level(self):
        c = self.p("Unemployment is 4.1%")
        self.assertEqual(c.metric_id, "unemployment_rate")
        self.assertEqual(c.measure, "level")
        self.assertAlmostEqual(c.value, 4.1)
        self.assertAlmostEqual(c.precision, 0.05)

    def test_jobs_added_with_month(self):
        c = self.p("The economy added 206,000 jobs in June 2024")
        self.assertEqual(c.metric_id, "nonfarm_jobs")
        self.assertEqual(c.measure, "change")
        self.assertEqual(c.value, 206000)
        self.assertEqual(c.period, Period(2024, 6))

    def test_jobs_lost_last_month(self):
        c = self.p("we lost 50k jobs last month", said_on=date(2025, 3, 10))
        self.assertEqual(c.measure, "change")
        self.assertEqual(c.value, -50000)
        self.assertEqual(c.period, Period(2025, 2))

    def test_inflation_is_yoy(self):
        c = self.p("Inflation is running at 3%")
        self.assertEqual(c.metric_id, "cpi_inflation")
        self.assertEqual(c.measure, "yoy_pct")
        self.assertEqual(c.value, 3)
        self.assertAlmostEqual(c.precision, 0.5)

    def test_core_beats_headline_inflation(self):
        c = self.p("core inflation hit 3.2% in May 2025")
        self.assertEqual(c.metric_id, "core_inflation")
        self.assertEqual(c.period, Period(2025, 5))

    def test_state(self):
        c = self.p("Texas unemployment is 4.0%")
        self.assertEqual(c.state, "Texas")
        self.assertAlmostEqual(c.precision, 0.05)

    def test_city_crime_total(self):
        c = self.p("Chicago had 568 homicides in 2024")
        self.assertEqual(c.metric_id, "city_homicides")
        self.assertEqual(c.city, "Chicago")
        self.assertEqual(c.measure, "annual_total")
        self.assertEqual(c.value, 568)
        self.assertEqual(c.period, Period(2024))

    def test_city_crime_percent_drop(self):
        c = self.p("Homicides in Chicago fell 27% last year", said_on=date(2025, 2, 1))
        self.assertEqual(c.metric_id, "city_homicides")
        self.assertEqual(c.measure, "yoy_pct")
        self.assertEqual(c.value, -27)
        self.assertEqual(c.period, Period(2024))

    def test_national_crime_without_city(self):
        c = self.p("there were 19,252 murders in 2023")
        self.assertEqual(c.metric_id, "us_homicides")
        self.assertEqual(c.value, 19252)

    def test_debt_with_comparator_and_suffix(self):
        c = self.p("The national debt is over $39 trillion")
        self.assertEqual(c.metric_id, "national_debt")
        self.assertEqual(c.comparator, "over")
        self.assertEqual(c.value, 39e12)

    def test_quarter(self):
        c = self.p("GDP grew 2.1% in the first quarter of 2026")
        self.assertEqual(c.metric_id, "gdp_growth")
        self.assertEqual(c.measure, "level")
        self.assertEqual(c.period, Period(2026, quarter=1))

    def test_nearly(self):
        c = self.p("mortgage rates are nearly 7%")
        self.assertEqual(c.metric_id, "mortgage_rate_30yr")
        self.assertEqual(c.comparator, "nearly")

    def test_unsupported(self):
        c = self.p("the sky is 100% blue")
        self.assertIsNone(c.metric_id)


if __name__ == "__main__":
    unittest.main()
