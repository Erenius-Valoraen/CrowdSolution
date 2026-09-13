"""Pure-logic tests for the legit checker. No database or network."""
import unittest
from datetime import date

from legit import llm
from legit.checkers import benchmark, patterns
from legit.checkers.common import domain_of, like_pattern, name_matches, normalize_name, province_name, us_state_name
from legit.models import Extraction, Finding, Item, Location, Report


class CommonTest(unittest.TestCase):
    def test_domain_of(self):
        self.assertEqual(domain_of("https://www.jpmorganchase.com/about"), "jpmorganchase.com")
        self.assertEqual(domain_of("recruiter@careers-amazon.com"), "careers-amazon.com")
        self.assertEqual(domain_of("hr@mail.google.com"), "google.com")
        self.assertEqual(domain_of("www.bbc.co.uk"), "bbc.co.uk")
        self.assertIsNone(domain_of("not a domain"))
        self.assertIsNone(domain_of(None))

    def test_names(self):
        self.assertEqual(normalize_name("Greenview Property Mgmt, LLC"), "greenview property")
        self.assertEqual(like_pattern("JPMorgan Chase & Co."), "%jpmorgan%chase%")
        self.assertTrue(name_matches("Chase", "JPMorgan Chase Bank, N.A."))
        self.assertFalse(name_matches("Amazon", "Deloitte LLP"))

    def test_domain_brand_relation(self):
        from legit.checkers.common import domain_brand_relation
        self.assertEqual(domain_brand_relation("chase.com", "Chase", "JPMorgan Chase Bank, National Association"), "exact")
        self.assertEqual(domain_brand_relation("jpmorganchase.com", "JPMorgan Chase Bank"), "exact")
        self.assertEqual(domain_brand_relation("chase-student-rewards.com", "Chase Bank"), "lookalike")
        self.assertEqual(domain_brand_relation("amazon-careers-hr.com", "Amazon"), "lookalike")
        self.assertEqual(domain_brand_relation("fastloans247.net", "Chase Bank"), "unrelated")
        self.assertEqual(domain_brand_relation("studentbank.com", "Bank"), "unrelated")

    def test_regions(self):
        self.assertEqual(us_state_name("TX"), "Texas")
        self.assertEqual(us_state_name("texas"), "Texas")
        self.assertIsNone(us_state_name("Ontario"))
        self.assertEqual(province_name(None, "Waterloo"), "Ontario")
        self.assertEqual(province_name("BC"), "British Columbia")
        self.assertTrue(Location(city="Waterloo", region="ON").is_canada)
        self.assertFalse(Location(city="Austin", region="TX", country="US").is_canada)


class BenchmarkRulesTest(unittest.TestCase):
    def test_rent(self):
        self.assertEqual(benchmark.classify_rent(650, 1899)[0], "red_flag")
        self.assertEqual(benchmark.classify_rent(1250, 1899)[0], "caution")
        self.assertEqual(benchmark.classify_rent(1800, 1899)[0], "ok")
        self.assertEqual(benchmark.classify_rent(3200, 1899)[0], "caution")

    def test_wage(self):
        self.assertEqual(benchmark.classify_wage(55, 35.16, True)[0], "caution")
        self.assertEqual(benchmark.classify_wage(40, 35.16, False)[0], "info")
        self.assertEqual(benchmark.classify_wage(120, 35.16, None)[0], "caution")

    def test_rates(self):
        self.assertEqual(benchmark.classify_savings(12, 3.63), "red_flag")
        self.assertEqual(benchmark.classify_savings(4.5, 3.63), "caution")
        self.assertEqual(benchmark.classify_savings(4.0, 3.63), "ok")
        self.assertEqual(benchmark.classify_loan(45, 11.86), "red_flag")
        self.assertEqual(benchmark.classify_loan(18, 11.86), "caution")
        self.assertEqual(benchmark.classify_loan(12, 11.86), "ok")


class PatternsTest(unittest.TestCase):
    def test_us_rental_reference(self):
        ext = Extraction(said_on=date(2026, 9, 13), context="housing", location=Location("Austin", "TX", "US"))
        f = patterns.check(Item(1, "pattern", "send the deposit by Zelle", {"pattern": "unusual_payment_method"}), ext)
        self.assertEqual(f.status, "red_flag")
        self.assertIn("rental-listing-scams", f.evidence[0].url)

    def test_canada_reference(self):
        ext = Extraction(said_on=date(2026, 9, 13), context="housing", location=Location("Waterloo", "ON", "CA"))
        f = patterns.check(Item(1, "pattern", "e-transfer the deposit", {"pattern": "upfront_payment"}), ext)
        self.assertIn("antifraudcentre", f.evidence[0].url)

    def test_finance_references(self):
        ext = Extraction(said_on=date(2026, 9, 13), context="finance", location=Location(country="US"))
        f = patterns.check(Item(1, "pattern", "guaranteed 12% APY", {"pattern": "guaranteed_returns"}), ext)
        self.assertIn("investment-scams", f.evidence[0].url)
        f = patterns.check(Item(2, "pattern", "your online banking login", {"pattern": "asks_personal_info"}), ext)
        self.assertIn("phishing", f.evidence[0].url)

    def test_unknown_pattern(self):
        ext = Extraction(said_on=date(2026, 9, 13))
        self.assertIsNone(patterns.check(Item(1, "pattern", "x", {"pattern": "nope"}), ext))


class JsonParsingTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(llm.parse_json('{"a": 1}'), {"a": 1})

    def test_fenced_after_prose(self):
        text = 'I searched.\n```json\n{"results": [{"id": 1, "verdict": "supported"}]}\n```'
        self.assertEqual(llm.parse_json(text)["results"][0]["id"], 1)

    def test_trailing_object_in_prose(self):
        text = 'Answer below {"results": [{"id": 2, "sources": [{"url": "https://x.org"}]}]} thanks'
        self.assertEqual(llm.parse_json(text)["results"][0]["id"], 2)

    def test_none(self):
        self.assertIsNone(llm.parse_json("no json here"))

    def test_retry_after(self):
        self.assertAlmostEqual(llm._retry_after("Please try again in 1m2.5s."), 62.5)
        self.assertAlmostEqual(llm._retry_after("Please try again in 7.25s."), 7.25)


class OfflineExtractTest(unittest.TestCase):
    SEEN = date(2026, 9, 13)

    def kinds(self, ext):
        return {(i.kind, i.data.get("pattern") or i.data.get("category")) for i in ext.items}

    def test_bank_phishing(self):
        from legit.extract import offline_extract
        ext = offline_extract("Chase Bank Student Offer: open a savings account today and earn 12% APY, guaranteed. "
                              "Limited spots! Verify your identity with your online banking login.", self.SEEN)
        k = self.kinds(ext)
        self.assertEqual(ext.context, "finance")
        self.assertIn(("pattern", "guaranteed_returns"), k)
        self.assertIn(("pattern", "asks_personal_info"), k)
        self.assertIn(("pattern", "urgency"), k)
        self.assertIn(("price", "savings_rate"), k)

    def test_waterloo_sublet(self):
        from legit.extract import offline_extract
        ext = offline_extract("Sublet available now! Private room in a 4 bedroom house by the University of Waterloo, "
                              "700 CAD a month. I'm currently in Vancouver so I can't show it, but e-transfer the first "
                              "and last month to lock it in before someone else takes it.", self.SEEN)
        k = self.kinds(ext)
        self.assertTrue(ext.location.is_canada)
        self.assertEqual(ext.location.city, "Waterloo")
        self.assertEqual(ext.context, "housing")
        self.assertIn(("price", "rent"), k)
        self.assertIn(("pattern", "unusual_payment_method"), k)
        self.assertIn(("pattern", "cannot_view_in_person"), k)
        self.assertIn(("pattern", "upfront_payment"), k)

    def test_safety_tip_is_not_a_red_flag(self):
        from legit.extract import offline_extract
        ext = offline_extract("Chase: your statement is ready. Sign in at chase.com. We will never ask for your "
                              "password by text, and never pay anyone with gift cards.", self.SEEN)
        patterns_found = {i.data.get("pattern") for i in ext.items if i.kind == "pattern"}
        self.assertNotIn("asks_personal_info", patterns_found)
        self.assertNotIn("unusual_payment_method", patterns_found)

    def test_fake_check_job(self):
        from legit.extract import offline_extract
        ext = offline_extract("Remote role, no experience needed, $55/hour. We will mail you a check for equipment; "
                              "deposit it and send the remaining balance to our vendor via gift cards.", self.SEEN)
        k = self.kinds(ext)
        self.assertIn(("pattern", "overpayment_check"), k)
        self.assertIn(("price", "hourly_wage"), k)


class AttachDomainsTest(unittest.TestCase):
    def test_links_lookalike_domain_to_bank(self):
        from legit.extract import attach_domains
        text = "Chase Bank offer: verify at chase-student-rewards.com"
        ext = Extraction(said_on=date(2026, 9, 13), items=[
            Item(1, "entity", "Chase Bank", {"name": "Chase Bank", "entity_type": "bank"}),
            Item(2, "entity", "chase-student-rewards.com", {"name": "chase-student-rewards.com", "entity_type": "website"}),
        ])
        attach_domains(ext, text)
        self.assertEqual(len(ext.items), 1)
        self.assertEqual(ext.items[0].data["website"], "chase-student-rewards.com")

    def test_generic_words_do_not_link(self):
        from legit.extract import attach_domains
        text = "University Housing Office, reply to studentbank-offers.net"
        ext = Extraction(said_on=date(2026, 9, 13), items=[
            Item(1, "entity", "University Housing", {"name": "University Housing", "entity_type": "school"}),
        ])
        attach_domains(ext, text)
        self.assertIsNone(ext.items[0].data.get("website"))

    def test_email_domain_from_text(self):
        from legit.extract import attach_domains
        text = "Amazon recruiting: write to recruiting@amazon-careers-hr.com"
        ext = Extraction(said_on=date(2026, 9, 13), items=[
            Item(1, "entity", "Amazon", {"name": "Amazon", "entity_type": "employer"}),
        ])
        attach_domains(ext, text)
        self.assertEqual(ext.items[0].data["website"], "amazon-careers-hr.com")


class ShortenTest(unittest.TestCase):
    def test_word_boundary(self):
        from legit.router import shorten
        self.assertEqual(shorten("short"), "short")
        long = "Chase bank policy states they will never ask for customer passwords via text message at all"
        out = shorten(long)
        self.assertTrue(out.endswith("..."))
        self.assertLessEqual(len(out), 73)
        self.assertFalse(out[:-3].endswith("mes"))


class YouTubeHelpersTest(unittest.TestCase):
    def test_parse_video_id(self):
        from legit.youtube import parse_video_id
        self.assertEqual(parse_video_id("https://www.youtube.com/watch?v=4sH30KUfPpM&t=30"), "4sH30KUfPpM")
        self.assertEqual(parse_video_id("https://youtu.be/4sH30KUfPpM"), "4sH30KUfPpM")
        self.assertEqual(parse_video_id("https://www.youtube.com/shorts/We4WJEVlM7o"), "We4WJEVlM7o")
        self.assertEqual(parse_video_id("4sH30KUfPpM"), "4sH30KUfPpM")
        with self.assertRaises(ValueError):
            parse_video_id("not a video")

    def test_sections_respect_size(self):
        from legit.youtube import Segment, make_sections
        segs = [Segment(i * 2.0, 2.0, "word " * 20) for i in range(100)]
        sections = make_sections(segs, max_chars=500)
        self.assertGreater(len(sections), 1)
        self.assertTrue(all(len(s.text) <= 520 for s in sections))
        self.assertEqual(sections[0].start, 0.0)
        self.assertEqual(sum(len(s.segments) for s in sections), 100)

    def test_locate_quote(self):
        from legit.youtube import Segment, _section, locate
        section = _section([Segment(10.0, 3.0, "good morning everyone"),
                            Segment(13.0, 4.0, "the economy added 172,000 jobs"),
                            Segment(17.0, 4.0, "and unemployment held at 4.3%")])
        self.assertEqual(locate("The economy added 172,000 jobs in May", section), 13.0)
        self.assertEqual(locate("unemployment rate of 4.3%", section), 17.0)
        self.assertEqual(locate("something never said", section), 10.0)

    def test_timestamp(self):
        from legit.youtube import timestamp
        self.assertEqual(timestamp(75), "1:15")
        self.assertEqual(timestamp(3725), "1:02:05")
        self.assertEqual(timestamp(None), "--:--")


class CollegeRulesTest(unittest.TestCase):
    def test_names(self):
        from legit.checkers import college
        self.assertEqual(college.normalize("The University of Texas at Austin"), "the university of texas at austin")
        self.assertEqual(college.search_tokens("The University of Texas at Austin"), ["university", "texas", "austin"])
        self.assertEqual(college.canonical_school("UofT"), "University of Toronto")
        self.assertEqual(college.canonical_school("uWaterloo"), "University of Waterloo")
        self.assertEqual(college.canonical_school("UT Austin"), "UT Austin")
        self.assertEqual(college.program_tokens("CS"), ["computer"])
        self.assertEqual(college.program_tokens("computer science majors"), ["computer", "science"])

    def test_matches(self):
        from legit.checkers import college
        self.assertTrue(college.matches(29, 0.2912, "percent"))
        self.assertFalse(college.matches(50, 0.2912, "percent"))
        self.assertTrue(college.matches(30, 0.2912, "percent"))          # "30%" rounds, allows 25-35
        self.assertTrue(college.matches(100000, 111587, "usd", "over"))   # "six figures"
        self.assertFalse(college.matches(150000, 111587, "usd", "over"))
        self.assertTrue(college.matches(75000, 75121, "usd"))
        self.assertFalse(college.matches(95000, 75121, "usd"))

    def test_compare_direction(self):
        from legit.checkers import college
        self.assertFalse(college.compare_direction(44524, 42778, "lower", "usd"))   # UCLA isn't cheaper out of state
        self.assertTrue(college.compare_direction(42778, 44524, "lower", "usd"))
        self.assertTrue(college.compare_direction(0.9266, 0.8764, "higher", "percent"))
        self.assertFalse(college.compare_direction(0.880, 0.878, "higher", "percent"))  # near tie

    def test_subgroup_statistics_skipped(self):
        from legit.checkers.statistic import SUBGROUP
        self.assertTrue(SUBGROUP.search("unemployment rate for recent grads, over 6%"))
        self.assertTrue(SUBGROUP.search("Construction services has an unemployment rate of 0.69%"))
        self.assertIsNone(SUBGROUP.search("the unemployment rate is 4.3%"))

    def test_dedupe(self):
        from legit.router import dedupe
        ext_item = lambda n, text: Item(n, "school", text, {})  # noqa: E731
        fs = [Finding(ext_item(1, "Waterloo is the best"), "info", "Waterloo: research profile", "same", "college"),
              Finding(ext_item(2, "better for research"), "info", "Waterloo: research profile", "same", "college"),
              Finding(ext_item(3, "other"), "ok", "Different", "x", "college")]
        out = dedupe(fs)
        self.assertEqual(len(out), 2)
        self.assertIn("better for research", out[0].summary)

    def test_graduate_earnings_vs_career_salary(self):
        from legit.checkers.college import is_graduate_earnings_claim
        self.assertTrue(is_graduate_earnings_claim("CS at UT Austin pays six figures right out of school"))
        self.assertTrue(is_graduate_earnings_claim("computer science majors make $90,000 four years after graduating"))
        self.assertFalse(is_graduate_earnings_claim("The average salary for a developer is around $131,000"))
        self.assertFalse(is_graduate_earnings_claim("surgeons are pulling in over $239,000 a year"))

    def test_subgroup_context_window(self):
        from legit.extract import about_subgroup
        text = ("Nursing is a great choice. The unemployment rate is an incredibly low 1.42%. "
                "Meanwhile the national unemployment rate held at 4.3% last month according to the BLS report today.")
        self.assertTrue(about_subgroup(text, "unemployment rate is an incredibly low 1.42%"))
        far = "x " * 200 + "the unemployment rate held at 4.3% last month"
        self.assertFalse(about_subgroup(far, "the unemployment rate held at 4.3%"))

    def test_subgroup_context_with_caption_spacing(self):
        from legit.extract import about_subgroup
        captions = ("which brings us to\nnursing. The salary is still strong at around\n$86,000, but the unemployment\n"
                    "rate is an incredibly low 1.42%. It's a classic case")
        # The model's quote has different spacing and line breaks than the captions.
        self.assertTrue(about_subgroup(captions, "the unemployment rate is an incredibly low 1.42%"))
        self.assertTrue(about_subgroup(captions, "unemployment   rate of 1.42%"))

    def test_video_skips_numberless_claims(self):
        from legit.youtube import _skip_in_video
        self.assertTrue(_skip_in_video(Item(1, "claim", "Choosing a major just for the paycheck is a trap", {})))
        self.assertFalse(_skip_in_video(Item(2, "claim", "Construction has a 0.69% unemployment rate", {})))

    def test_display(self):
        from legit.checkers import college
        self.assertEqual(college.display(0.0873, "percent"), "9%")
        self.assertEqual(college.display(13747, "usd"), "$13,747")
        self.assertEqual(college.display(None, "usd"), "not reported")

    def test_video_filters(self):
        from legit.youtube import _skip_in_video
        self.assertTrue(_skip_in_video(Item(1, "entity", "Yahoo Finance", {"name": "Yahoo Finance"})))
        self.assertFalse(_skip_in_video(Item(2, "entity", "apply at acme-jobs.com", {"name": "Acme", "website": "acme-jobs.com"})))
        self.assertTrue(_skip_in_video(Item(3, "statistic", "consensus estimate of 88,000 jobs", {})))
        self.assertFalse(_skip_in_video(Item(4, "statistic", "the economy added 172,000 jobs", {})))


class ReportTest(unittest.TestCase):
    def report(self, *statuses):
        ext = Extraction(said_on=date(2026, 9, 13))
        item = Item(1, "claim", "x", {})
        return Report(ext, [Finding(item, s, "t", "s", "test") for s in statuses])

    def test_overall(self):
        self.assertEqual(self.report("ok", "red_flag").overall, "HIGH RISK")
        self.assertEqual(self.report("ok", "caution").overall, "BE CAREFUL")
        self.assertEqual(self.report("unverified", "unverified").overall, "COULDN'T VERIFY")
        self.assertEqual(self.report("unverified", "info").overall, "NO RED FLAGS FOUND")
        self.assertEqual(self.report("ok", "info").overall, "NO RED FLAGS FOUND")
        self.assertEqual(self.report().overall, "NOTHING TO CHECK")


if __name__ == "__main__":
    unittest.main()
