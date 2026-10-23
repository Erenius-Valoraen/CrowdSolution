"""Verdict wording fits the input: safety checks, questions, and claims. No network."""
import os
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("COMMUNITY_MEMORY", "off")

from api import service  # noqa: E402
from legit.models import Extraction, Finding, Item, Report  # noqa: E402


def payload(text, findings, context="school", video=None):
    rep = Report(Extraction(said_on=date(2026, 9, 13), context=context), findings)
    with mock.patch.object(service.storage, "save_scan"):
        return service.build_payload(rep, text, video=video)


OK_SCHOOL = Finding(Item(1, "school", "UWaterloo CS grads earn more"), "ok", "Earnings", "Matches.", "web")
CAUTION_SCHOOL = Finding(Item(1, "school", "UWaterloo CS grads earn more"), "caution", "Earnings", "Doesn't match.", "web")


class FramingTest(unittest.TestCase):
    def test_question_gets_data_wording(self):
        p = payload("do uwaterloo cs grads earn more than uoft grads", [OK_SCHOOL])
        self.assertEqual(p["framing"], "question")
        self.assertEqual(p["overall"], "NO RED FLAGS FOUND")  # the verdict code stays the same for clients
        self.assertEqual((p["overall_badge"]["title"], p["overall_badge"]["color"]), ("Here's what the data says", "blue"))
        self.assertEqual(payload("Which is cheaper, UCLA or UT Austin?", [CAUTION_SCHOOL])["overall_badge"]["title"],
                         "Here's what the data says")

    def test_claims_from_posts_and_videos(self):
        p = payload("UCLA is cheaper than UT Austin.", [CAUTION_SCHOOL])
        self.assertEqual((p["framing"], p["overall_badge"]["title"]), ("claims", "Some claims don't hold up"))
        video = service.video_details(__import__("legit.youtube", fromlist=["VideoInfo"]).VideoInfo("abc"))
        v = payload("https://youtu.be/abc", [OK_SCHOOL], video=video)
        self.assertEqual((v["framing"], v["overall_badge"]["title"]), ("claims", "Claims check out"))

    def test_listings_and_offers_keep_safety_wording(self):
        scam = Finding(Item(1, "pattern", "send the deposit by Zelle"), "red_flag", "Hard-to-reverse payment", "", "patterns")
        p = payload("Is this legit? 2BR for $650, deposit by Zelle", [scam], context="housing")
        self.assertEqual((p["framing"], p["overall_badge"]["title"]), ("safety", "High risk"))
        clean = Finding(Item(1, "price", "$1,095/month"), "ok", "Rent compared with local median", "", "benchmark")
        self.assertEqual(payload("Sublet near Ohio State for $1,095/month", [clean], context="housing")["overall_badge"]["title"],
                         "No red flags found")

    def test_spoken_summary_answers_questions(self):
        p = payload("do uwaterloo cs grads earn more than uoft grads?", [OK_SCHOOL])
        self.assertTrue(service.template_spoken_summary(p).startswith("Here's what the data says."))


if __name__ == "__main__":
    unittest.main()
