"""YouTube links in the API: link detection, transcript errors, and the video fields in the payload. No network."""
import os
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("COMMUNITY_MEMORY", "off")

from api import service  # noqa: E402
from legit import youtube  # noqa: E402
from legit.models import Extraction, Finding, Item, Report  # noqa: E402


class YouTubeLinkTest(unittest.TestCase):
    def test_detects_links(self):
        for text in ("https://www.youtube.com/watch?v=4sH30KUfPpM", "youtu.be/4sH30KUfPpM?t=42",
                     "  https://youtube.com/shorts/4sH30KUfPpM  ", "https://m.youtube.com/watch?feature=share&v=4sH30KUfPpM"):
            self.assertTrue(service.is_youtube_link(text), text)

    def test_ignores_text_that_mentions_a_link(self):
        for text in ("Watch https://youtu.be/4sH30KUfPpM, it says rent is $650", "https://www.youtube.com/@channel",
                     "Cozy 2BR near campus, $650/month"):
            self.assertFalse(service.is_youtube_link(text), text)


class TranscriptErrorTest(unittest.TestCase):
    def test_transcript_errors_become_friendly_input_errors(self):
        TranscriptsDisabled = type("TranscriptsDisabled", (Exception,), {"__module__": "youtube_transcript_api._errors"})
        with mock.patch.object(youtube, "check_video", side_effect=TranscriptsDisabled("off")):
            with self.assertRaises(service.InputError) as ctx:
                service.check_youtube("https://youtu.be/4sH30KUfPpM", None, offline=True)
        self.assertIn("captions turned off", str(ctx.exception))

    def test_other_errors_are_not_hidden(self):
        with mock.patch.object(youtube, "check_video", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                service.check_youtube("https://youtu.be/4sH30KUfPpM", None, offline=True)


class VideoPayloadTest(unittest.TestCase):
    def setUp(self):
        self.info = youtube.VideoInfo("4sH30KUfPpM", title="Jobs report", channel="News", upload_date=date(2026, 6, 5),
                                      language="en", auto_captions=True)
        self.info.segments = [youtube.Segment(0, 3, "hello"), youtube.Segment(3, 3, "the economy added jobs"),
                              youtube.Segment(200, 3, "later part")]
        self.info.duration, self.info.sections_total, self.info.sections_checked, self.info.checked_until = 203, 2, 1, 100

    def test_video_details(self):
        v = service.video_details(self.info)
        self.assertEqual(v["checked_until_label"], "1:40")
        self.assertFalse(v["fully_checked"])
        self.assertEqual([(line["timestamp"], line["checked"]) for line in v["transcript"]], [("0:00", True), ("3:20", False)])
        self.assertEqual(v["transcript"][0]["text"], "hello the economy added jobs")

    def test_findings_carry_timestamps(self):
        finding = Finding(Item(1, "statistic", "added jobs"), "caution", "Jobs", "summary", "statistic")
        rep = Report(Extraction(said_on=date(2026, 6, 5), context="finance"), [finding])
        with mock.patch.object(service.storage, "save_scan") as save:
            payload = service.build_payload(rep, "https://youtu.be/4sH30KUfPpM", video=service.video_details(self.info),
                                            seconds={id(finding): 125.4})
        self.assertEqual((payload["findings"][0]["seconds"], payload["findings"][0]["timestamp"]), (125.4, "2:05"))
        self.assertEqual(payload["video"]["title"], "Jobs report")
        self.assertTrue(payload["action_checklist"][0].startswith("Jump to the flagged timestamps"))
        self.assertEqual(save.call_args.kwargs["text"], "YouTube: Jobs report")

    def test_text_payload_has_no_video(self):
        finding = Finding(Item(1, "claim", "x"), "unverified", "X", "", "router")
        rep = Report(Extraction(said_on=date(2026, 9, 13)), [finding])
        with mock.patch.object(service.storage, "save_scan"):
            payload = service.build_payload(rep, "some text")
        self.assertIsNone(payload["video"])
        self.assertIsNone(payload["findings"][0]["timestamp"])


if __name__ == "__main__":
    unittest.main()
