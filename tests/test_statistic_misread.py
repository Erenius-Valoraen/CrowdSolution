"""Statistic checks skip claims matched to the wrong measure, so the web checks them instead of calling them wrong."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from legit import extract
from legit.checkers import statistic
from legit.models import Extraction, Item
from legit.stats import verdict as sv

METRIC = SimpleNamespace(id="average_hourly_earnings", label="Average hourly earnings", agency="BLS",
                         state_variable=False, needs_city=False)


def run(text, value, official, verdict=sv.WRONG, measure="yoy_pct"):
    figure = SimpleNamespace(value=official, label="May 2026", published=date(2026, 6, 5))
    res = SimpleNamespace(verdict=verdict, measure=measure, then=figure, revised=None, latest=None, fallback=None,
                          notes=[], where="United States")
    item = Item(1, "statistic", text, {"metric_id": METRIC.id, "measure": measure, "value": value,
                                       "period": {"year": 2026, "month": 5}})
    with mock.patch.object(extract, "stats_catalog", return_value={METRIC.id: METRIC}), \
            mock.patch.object(statistic, "check_claim", return_value=res), \
            mock.patch.object(statistic, "fmt", side_effect=lambda m, meas, v: str(v)):
        return statistic.check(item, Extraction(said_on=date(2026, 6, 5)))


class MisreadTest(unittest.TestCase):
    def test_monthly_raise_checked_against_yearly_change_is_skipped(self):
        self.assertIsNone(run("average hourly earnings coming in at 0.3% for the month", 0.3, 3.45))

    def test_figures_far_apart_are_skipped(self):
        self.assertIsNone(run("wages up 0.3%", 0.3, 3.45))

    def test_close_but_wrong_claim_is_still_flagged(self):
        finding = run("wages up 4.5% from a year ago", 4.5, 3.45)
        self.assertEqual(finding.status, "caution")

    def test_accurate_claims_are_never_skipped(self):
        self.assertEqual(run("wages rose 0.3% for the month", 0.3, 0.3, verdict=sv.ACCURATE).status, "ok")

    def test_claims_about_other_countries_go_to_the_web(self):
        self.assertIsNone(run("Canada's unemployment rate hit 7.1%", 7.1, 4.3))
        self.assertIsNone(run("groceries in Canada went up 11% last year", 11, 2.9))
        self.assertEqual(run("US wages up 4.5% from a year ago", 4.5, 3.45).status, "caution")

    def test_helper(self):
        self.assertFalse(statistic.looks_misread(172000, 172000, "change", "172,000 jobs added last month"))
        self.assertTrue(statistic.looks_misread(172000, 159_001_000, "level", "172,000 jobs"))
        self.assertFalse(statistic.looks_misread(-0.2, 3.1, "yoy_pct", "prices fell 0.2%"))


if __name__ == "__main__":
    unittest.main()
