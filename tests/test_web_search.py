"""Web checks: search result parsing, queries, reading results into findings, and the router cleanup. No network."""
import json
import os
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("COMMUNITY_MEMORY", "off")

from legit import router  # noqa: E402
from legit.checkers import web  # noqa: E402
from legit.models import Extraction, Finding, Item  # noqa: E402

PAGE = """
<div class="result results_links result--ad"><h2 class="result__title">
  <a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_domain=x">Buy stuff</a></h2></div>
<div class="result"><h2 class="result__title">
  <a rel="nofollow" class="result__a" href="https://www.cbc.ca/news/jobs">Canada&#x27;s economy lost 84,000 jobs</a></h2>
  <span>&nbsp; 2026-03-13T12:39:00.0000000</span>
  <a class="result__snippet" href="https://www.cbc.ca/news/jobs"><b>Canada</b> shed 84,000 jobs in February.</a></div>
<div class="result"><h2 class="result__title">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww150.statcan.gc.ca%2Flfs&amp;rut=1">Labour Force Survey</a></h2>
  <a class="result__snippet" href="x">Employment fell by 84,000.</a></div>
"""


def reply(results):
    return {"content": json.dumps({"results": results})}, "cortex:claude-haiku-4-5"


class ParseTest(unittest.TestCase):
    def test_parses_organic_results_and_skips_ads(self):
        results = web.parse_results(PAGE)
        self.assertEqual([r.url for r in results], ["https://www.cbc.ca/news/jobs", "https://www150.statcan.gc.ca/lfs"])
        self.assertEqual(results[0].title, "Canada's economy lost 84,000 jobs")
        self.assertEqual(results[0].snippet, "Canada shed 84,000 jobs in February.")
        self.assertEqual(results[0].date, "2026-03-13")

    def test_search_drops_videos_and_social_posts(self):
        results = [web.Result("Video", "https://www.youtube.com/watch?v=abc", ""), web.Result("Post", "https://m.facebook.com/p/1", ""),
                   web.Result("BLS", "https://www.bls.gov/news.release/empsit.htm", ""), web.Result("Box", "https://xbox.com/a", "")]
        with mock.patch.object(web, "provider", return_value="tavily"), mock.patch.object(web, "_tavily", return_value=results):
            self.assertEqual([r.title for r in web.search("jobs")], ["BLS", "Box"])

    def test_queries(self):
        ext = Extraction(said_on=date(2026, 6, 5))
        self.assertEqual(web.search_query(Item(1, "statistic", "unemployment rate held at 4.3%"), ext),
                         "unemployment rate held at 4.3% June 2026")
        self.assertEqual(web.search_query(Item(2, "claim", "x", {"claim": "Canada lost 84,000 jobs in February 2026"}), ext),
                         "Canada lost 84,000 jobs in February 2026")


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.ext = Extraction(said_on=date(2026, 3, 13), summary="A news video")
        self.items = [Item(1, "claim", "Canada lost 84,000 jobs", {"claim": "Canada lost 84,000 jobs in February 2026"}),
                      Item(2, "claim", "savings rate is at an 18-year low", {"claim": "savings rate is at an 18-year low"}),
                      Item(3, "claim", "nothing to find", {"claim": "nothing to find"})]
        results = web.parse_results(PAGE)
        self.patches = [
            mock.patch.object(web.llm, "available", return_value=True),
            mock.patch.object(web.llm, "groq_available", return_value=False),
            mock.patch.object(web, "page_excerpt", return_value=""),
            mock.patch.object(web, "search", side_effect=lambda q, limit=5: [] if "nothing" in q else list(results)),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(mock.patch.stopall)

    def test_findings_carry_figures_and_only_real_sources(self):
        answer = reply([
            {"id": 1, "verdict": "supported", "claimed": "84,000 jobs lost", "found": "84,000 jobs lost in February 2026",
             "claimed_value": 84000, "found_value": "84,000", "unit": "jobs", "as_of": "February 2026",
             "answer": "Statistics Canada reported this.", "sources": [2, 9]},
            {"id": 2, "verdict": "unclear", "found": "3.5% in April 2026", "claimed_value": None, "found_value": 3.5,
             "answer": "Sources give the rate but not an 18-year comparison.", "sources": []},
        ])
        with mock.patch.object(web.llm, "chat_any", return_value=answer) as chat:
            findings, notes = web.verify(self.items, self.ext)
        self.assertEqual(chat.call_count, 1)  # item 3 had no results, so it isn't sent to the model
        by_id = {f.item.id: f for f in findings}
        self.assertEqual(set(by_id), {1, 2})
        self.assertEqual(by_id[1].status, "ok")
        self.assertEqual((by_id[1].data["claimed_value"], by_id[1].data["found_value"]), (84000.0, 84000.0))
        self.assertEqual([e.url for e in by_id[1].evidence], ["https://www150.statcan.gc.ca/lfs"])  # [9] doesn't exist
        self.assertEqual(by_id[2].status, "info")  # a figure was found, so it's context, not unconfirmed
        self.assertIsNone(by_id[2].data["found_value"])  # not comparable without a claimed value
        self.assertEqual(notes, [])

    def test_blocked_search_uses_browser_search(self):
        with mock.patch.object(web, "search", side_effect=web.SearchBlocked("no")), \
                mock.patch.object(web, "browser_verify", return_value=([], ["fallback"])) as fallback:
            _findings, notes = web.verify(self.items, self.ext)
        fallback.assert_called_once()
        self.assertIn("fallback", notes)

    def test_block_midway_keeps_results_already_found(self):
        results = web.parse_results(PAGE)

        def search(query, limit=5):
            if "84,000" in query:
                return list(results)
            raise web.SearchBlocked("no")

        answer = reply([{"id": 1, "verdict": "supported", "found": "84,000 jobs lost", "answer": "ok", "sources": [1]}])
        with mock.patch.object(web, "search", side_effect=search), \
                mock.patch.object(web.llm, "chat_any", return_value=answer), \
                mock.patch.object(web, "browser_verify", return_value=([], [])) as fallback:
            findings, _notes = web.verify(self.items, self.ext)
        self.assertEqual([f.item.id for f in findings], [1])
        self.assertNotIn(1, [it.id for it in fallback.call_args.args[0]])

    def test_provider_prefers_api_keys(self):
        with mock.patch.object(web.config, "TAVILY_API_KEY", None), mock.patch.object(web.config, "BRAVE_SEARCH_API_KEY", "k"):
            self.assertEqual(web.provider(), "brave")
        with mock.patch.object(web.config, "TAVILY_API_KEY", None), mock.patch.object(web.config, "BRAVE_SEARCH_API_KEY", None):
            self.assertEqual(web.provider(), "duckduckgo")


class RouterCleanupTest(unittest.TestCase):
    def test_web_answer_replaces_official_unconfirmed(self):
        item = Item(1, "statistic", "unemployment held at 4.3%")
        ext = Extraction(said_on=date(2026, 6, 5), items=[item])
        official = Finding(item, "unverified", "Unemployment rate", "Not yet published when said.", "statistic")
        online = Finding(item, "ok", "Web check: unemployment", "BLS reported 4.3%.", "web")
        with mock.patch.object(router.web, "verify", return_value=([online], [])):
            report = router.finish(ext, [official], [item], [], offline=False, progress=lambda _m: None)
        self.assertEqual([f.checker for f in report.findings], ["web"])


if __name__ == "__main__":
    unittest.main()
