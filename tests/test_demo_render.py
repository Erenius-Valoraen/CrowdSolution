"""The interactive renderer must handle every kind of finding without crashing. No database or network."""
import io
import unittest
from datetime import date

from rich.console import Console

from legit.demo import main_domains, render
from legit.models import Evidence, Extraction, Finding, Item, Location, Report
from legit.router import split_text


def finding(n, kind, status, checker, title, summary, data, text="quote", evidence=None):
    return Finding(Item(n, kind, text, {"name": "Chase Bank"} if kind == "entity" else {}), status, title, summary,
                   checker, evidence or [], data=data)


class RenderTest(unittest.TestCase):
    def test_renders_every_section_without_technical_noise(self):
        ext = Extraction(said_on=date(2026, 9, 13), context="finance", summary="A test message",
                         location=Location("Austin", "TX", "US"), parser="groq qwen/qwen3.8-27b")
        ucla = {"name": "University of California-Los Angeles", "city": "Los Angeles", "state": "CA", "admission_rate": 0.0873,
                "tuition_out_of_state": 44524.0, "graduation_rate": 0.9266, "research_works": 402368, "h_index": 1605}
        findings = [
            finding(1, "pattern", "red_flag", "patterns", "Hard-to-reverse payment method", "Zelle is hard to reverse.",
                    {"type": "pattern", "explanation": "Payment apps are hard to reverse."}, "send it by Zelle",
                    [Evidence("FTC: Rental listing scams", "guidance", "guidance", "https://consumer.ftc.gov/articles/rental-listing-scams")]),
            finding(2, "entity", "red_flag", "registry", "Chase Bank: bank registration", "Lookalike domain.",
                    {"type": "bank", "registered_name": "JPMorgan Chase Bank, National Association", "entity_type": "National Bank",
                     "active": True, "fdic_cert": "628", "claimed_domain": "chase-student-rewards.com",
                     "official_domains": ["jpmorganchase.com", "jpmorganchina.com.cn"], "domain_result": "lookalike"}),
            finding(2, "entity", "info", "reputation", "Chase Bank: complaint history", "Many complaints.",
                    {"type": "complaints", "company": "JPMORGAN CHASE & CO.", "complaints": 26502, "timely_pct": 100,
                     "top_issue": "Managing an account", "top_product": "Checking", "period_end": "2026-06-14"}),
            finding(3, "price", "red_flag", "benchmark", "Rent compared with local median", "34% of typical.",
                    {"type": "rent", "amount": 650.0, "benchmark": 1899.0, "ratio": 0.34, "unit": "usd_month",
                     "benchmark_label": "Typical 2-bedroom rentals in Austin (2024)"}, "$650/month"),
            finding(4, "school", "caution", "college", "UCLA vs UT Austin: out-of-state tuition", "Not cheaper.",
                    {"type": "college", "schools": [ucla, {"name": "The University of Texas at Austin", "tuition_out_of_state": 42778.0}],
                     "programs": [{"school": "The University of Texas at Austin", "program": "Computer Science", "credential": "Bachelor's Degree",
                                   "graduates": 438, "earnings_1yr": 111587.0, "earnings_4yr": None, "earnings_5yr": 132436.0, "median_debt": 20500.0}],
                     "claim": {"text": "cheaper", "label": "Out-of-state tuition", "unit": "usd", "metric": "tuition_out_of_state",
                               "claimed": "lower than UT Austin", "official": "$44,524 vs $42,778", "result": "caution"},
                     "opinion": False}, "It's even cheaper for out-of-state students"),
            finding(5, "school", "info", "college", "UCLA vs UT Austin", "Opinion.",
                    {"type": "college", "schools": [ucla], "programs": [], "claim": None, "opinion": True}, "UCLA is way better"),
            finding(6, "statistic", "ok", "statistic", "Total nonfarm jobs: United States", "Accurate when said.",
                    {"type": "statistic", "label": "Total nonfarm jobs", "agency": "Bureau of Labor Statistics",
                     "verdict": "ACCURATE WHEN SAID",
                     "figures": {"when_said": {"value": "+172,000 jobs", "period": "May 2026", "published": "2026-06-05"},
                                 "revised": {"value": "+63,000 jobs", "period": "May 2026", "published": "2026-08-07"},
                                 "latest": {"value": "+63,000 jobs", "period": "May 2026", "published": "2026-08-07"}}},
                    "added 172,000 jobs"),
            finding(7, "claim", "caution", "web", "Web check", "Rents are about $1,900.",
                    {"type": "web", "verdict": "contradicted", "sources": [{"title": "Zumper", "url": "https://www.zumper.com"}]}),
            finding(8, "claim", "unverified", "router", "No record found", "Verify it yourself.", {}, "something unverifiable"),
        ]
        buf = io.StringIO()
        render(Report(ext, findings, ["Keyword rules added 1 item(s)", "run without --offline to search the web"]),
               console=Console(file=buf, width=140, force_terminal=False, color_system=None))
        out = buf.getvalue()
        for expected in ("HIGH RISK", "Warning signs", "Who's behind it", "chase-student-rewards.com", "Is the price normal?",
                         "Schools and majors", "Side by side", "What graduates earn", "Official numbers",
                         "+172,000 jobs", "Other claims", "Couldn't confirm"):
            self.assertIn(expected, out)
        for noise in ("Keyword rules", "--offline", "--web", "qwen", "Seen:", "Checked in", "jpmorganchina"):
            self.assertNotIn(noise, out)


class HelpersTest(unittest.TestCase):
    def test_main_domains_prefers_plain(self):
        self.assertEqual(main_domains(["jpmorganchase.com", "jpmorganchina.com.cn"]), ["jpmorganchase.com"])
        self.assertEqual(main_domains(["bbc.co.uk"]), ["bbc.co.uk"])

    def test_split_text(self):
        text = "First sentence here. " * 400
        parts = split_text(text, max_chars=1000)
        self.assertGreater(len(parts), 5)
        self.assertTrue(all(len(p) <= 1000 for p in parts))
        no_punctuation = "word " * 3000
        parts = split_text(no_punctuation, max_chars=1000)
        self.assertTrue(all(len(p) <= 1000 for p in parts))
        self.assertEqual(sum(len(p.split()) for p in parts), 3000)


if __name__ == "__main__":
    unittest.main()
