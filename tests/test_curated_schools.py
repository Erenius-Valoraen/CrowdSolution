"""Hand-curated Ontario figures give a side-by-side comparison for UWaterloo and UofT. No database."""
import unittest
from datetime import date
from unittest import mock

from legit.checkers import college
from legit.models import Extraction, Item


def check(data, text="Do University of Waterloo grads earn more than University of Toronto grads?"):
    item = Item(1, "school", text, data)
    with mock.patch.object(college, "find_school", return_value=None), \
            mock.patch.object(college, "find_research", return_value=None):
        return college.check(item, Extraction(said_on=date(2026, 9, 13), context="school"))


class CuratedSchoolsTest(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(college.curated_school("UofT")[0], "University of Toronto")
        self.assertEqual(college.curated_school("uwaterloo")[0], "University of Waterloo")
        self.assertIsNone(college.curated_school("Toronto Metropolitan University"))

    def test_earnings_question_gets_side_by_side_answer(self):
        f = check({"school": "University of Waterloo", "compare_to": "University of Toronto", "metric": "median_earnings_6yr",
                   "direction": "higher", "country": "CA"})
        self.assertEqual(f.status, "ok")
        self.assertEqual([s["name"] for s in f.data["schools"]], ["University of Waterloo", "University of Toronto"])
        self.assertEqual((f.data["schools"][0]["earnings_2yr_median"], f.data["schools"][1]["earnings_2yr_median"]), (69690, 61877))
        self.assertTrue(f.data["curated"])
        self.assertIn("$69,690", f.summary)
        self.assertIn("$61,877", f.summary)
        self.assertFalse(f.web_followup)  # official figures answer it, so no web search is spent
        self.assertTrue(all(e.url for e in f.evidence))

    def test_reversed_claim_does_not_hold(self):
        f = check({"school": "UofT", "compare_to": "Waterloo", "metric": "median_earnings_6yr", "direction": "higher"},
                  text="UofT grads earn more than Waterloo grads")
        self.assertEqual(f.status, "caution")
        self.assertEqual(f.data["claim"]["official"], "$61,877 vs $69,690")

    def test_general_comparison_is_informational(self):
        f = check({"school": "University of Waterloo", "compare_to": "University of Toronto", "metric": "general"},
                  text="Waterloo is better than UofT")
        self.assertEqual(f.status, "info")
        self.assertIn("official Ontario data", f.title)
        self.assertTrue(f.data["opinion"])


if __name__ == "__main__":
    unittest.main()
