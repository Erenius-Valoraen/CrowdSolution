import unittest
from datetime import date

from legit.stats import verdict
from legit.stats.catalog import Catalog
from legit.stats.models import Claim, Figure, Period, half_step

CAT = Catalog()
UNEMP = CAT.get("unemployment_rate")
JOBS = CAT.get("nonfarm_jobs")
DEBT = CAT.get("national_debt")
END = date(2026, 6, 14)


def fig(value, y, m, pub=None):
    return Figure(value, date(y, m, 28), pub, f"{y}-{m:02d}")


def claim(value, precision=None, said_on=date(2025, 1, 15), comparator="about", period=None):
    return Claim(text="", said_on=said_on, value=value, precision=precision, comparator=comparator, period=period)


class HalfStepTest(unittest.TestCase):
    def test_examples(self):
        self.assertAlmostEqual(half_step(4.1), 0.05)
        self.assertAlmostEqual(half_step(4), 0.5)
        self.assertAlmostEqual(half_step(200000), 50000)
        self.assertAlmostEqual(half_step(227000), 500)


class ToleranceTest(unittest.TestCase):
    def test_percent_rounding(self):
        self.assertAlmostEqual(verdict.tolerance(UNEMP, "level", claim(4.1, 0.05)), 0.1)
        self.assertAlmostEqual(verdict.tolerance(UNEMP, "level", claim(4, 0.5)), 0.5)

    def test_count_rounding(self):
        self.assertAlmostEqual(verdict.tolerance(JOBS, "change", claim(206000, 500)), 4120)
        self.assertAlmostEqual(verdict.tolerance(JOBS, "change", claim(200000, 50000)), 20000)

    def test_over_is_strict(self):
        self.assertTrue(verdict.within(DEBT, "level", claim(39e12, comparator="over"), 39.2e12))
        self.assertFalse(verdict.within(DEBT, "level", claim(40e12, comparator="over"), 39.2e12))

    def test_float_noise_at_tolerance_edge(self):
        # 4.2 - 4.1 is 0.10000000000000053 in floating point; it must still count as within 0.1.
        self.assertTrue(verdict.within(UNEMP, "level", claim(4.1, 0.05), 4.2))


class DecideTest(unittest.TestCase):
    def run_decide(self, c, **kw):
        base = dict(then=None, revised=None, latest=None, known_before=[], fallback=None,
                    history_from=date(2024, 3, 12), data_end=END)
        base.update(kw)
        return verdict.decide(c, UNEMP, "level", **base)

    def test_accurate_but_outdated_now(self):
        v, notes = self.run_decide(claim(4.1, 0.05), then=fig(4.1, 2024, 12), revised=fig(4.1, 2024, 12),
                                   latest=fig(4.3, 2026, 5))
        self.assertEqual(v, verdict.ACCURATE)
        self.assertTrue(any("Outdated now" in n for n in notes))

    def test_outdated_when_said(self):
        v, _ = self.run_decide(claim(3.7, 0.05), then=fig(4.1, 2024, 12),
                               known_before=[fig(3.7, 2024, 1), fig(4.0, 2024, 6), fig(4.2, 2024, 11)])
        self.assertEqual(v, verdict.OUTDATED_WHEN_SAID)

    def test_wrong(self):
        v, _ = self.run_decide(claim(6.0, 0.05), then=fig(4.1, 2024, 12), known_before=[fig(4.2, 2024, 11)])
        self.assertEqual(v, verdict.WRONG)

    def test_stale_match_too_old_is_wrong(self):
        v, _ = self.run_decide(claim(3.5, 0.05), then=fig(4.1, 2024, 12), known_before=[fig(3.5, 2023, 6)])
        self.assertEqual(v, verdict.WRONG)

    def test_wrong_then_but_matches_revision(self):
        v, notes = self.run_decide(claim(2.1, 0.05), then=fig(1.6, 2026, 3), revised=fig(2.1, 2026, 3))
        self.assertEqual(v, verdict.WRONG)
        self.assertTrue(any("revised" in n for n in notes))

    def test_before_history_uses_today(self):
        v, notes = self.run_decide(claim(3.6, 0.05, said_on=date(2023, 6, 1)), fallback=fig(3.6, 2023, 5))
        self.assertEqual(v, verdict.MATCHES_TODAY)
        self.assertTrue(any("No record" in n for n in notes))

    def test_not_yet_published(self):
        v, _ = self.run_decide(claim(4.3, 0.05, said_on=date(2026, 5, 20), period=Period(2026, 5)))
        self.assertEqual(v, verdict.NOT_YET_PUBLISHED)


if __name__ == "__main__":
    unittest.main()
