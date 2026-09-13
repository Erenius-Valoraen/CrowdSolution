"""YouTube transcripts through Supadata: parsing, long-video jobs, errors, and when to fall back. No network."""
import io
import json
import unittest
import urllib.error
from datetime import date
from unittest import mock

from legit import config, youtube


class FakeResponse(io.BytesIO):
    def __init__(self, body: dict, status: int = 200):
        super().__init__(json.dumps(body).encode())
        self.status = status


def http_error(status: int, body: dict):
    return urllib.error.HTTPError(youtube.SUPADATA_URL, status, "error", {}, io.BytesIO(json.dumps(body).encode()))


class SupadataTranscriptTest(unittest.TestCase):
    def setUp(self):
        for patch in (mock.patch.object(config, "SUPADATA_API_KEY", "sd_test"), mock.patch.object(youtube.time, "sleep")):
            patch.start()
        self.addCleanup(mock.patch.stopall)

    def test_parses_segments_in_seconds(self):
        body = {"lang": "en", "content": [{"text": "Rent is &#39;only&#39;  $650", "offset": 18800, "duration": 1000},
                                          {"text": "  ", "offset": 20000, "duration": 500}]}
        with mock.patch.object(youtube.urllib.request, "urlopen", return_value=FakeResponse(body)) as urlopen:
            segments, lang, auto = youtube.fetch_transcript_supadata("4sH30KUfPpM")
        self.assertEqual([(s.start, s.duration, s.text) for s in segments], [(18.8, 1.0, "Rent is 'only' $650")])
        self.assertEqual((lang, auto), ("en", None))
        req = urlopen.call_args.args[0]
        self.assertIn("mode=native", req.full_url)
        self.assertEqual(req.get_header("X-api-key"), "sd_test")

    def test_long_video_job_is_polled(self):
        responses = [FakeResponse({"jobId": "job-1"}, status=202), FakeResponse({"status": "active"}),
                     FakeResponse({"status": "completed", "lang": "en", "content": [{"text": "hi", "offset": 0, "duration": 900}]})]
        with mock.patch.object(youtube.urllib.request, "urlopen", side_effect=responses) as urlopen:
            segments, _lang, _auto = youtube.fetch_transcript_supadata("4sH30KUfPpM")
        self.assertEqual(segments[0].text, "hi")
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith("/transcript/job-1"))

    def test_errors_become_friendly_messages(self):
        cases = [(http_error(429, {"error": "limit-exceeded"}), "quota is used up"),
                 (http_error(404, {"error": "transcript-unavailable"}), "no captions"),
                 (http_error(401, {"error": "unauthorized"}), "rejected")]
        for error, words in cases:
            with mock.patch.object(youtube.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(youtube.TranscriptUnavailable) as ctx:
                    youtube.fetch_transcript_supadata("4sH30KUfPpM")
            self.assertIn(words, str(ctx.exception))

    def test_failed_job(self):
        responses = [FakeResponse({"jobId": "job-2"}, status=202),
                     FakeResponse({"status": "failed", "error": {"error": "transcript-unavailable"}})]
        with mock.patch.object(youtube.urllib.request, "urlopen", side_effect=responses):
            with self.assertRaisesRegex(youtube.TranscriptUnavailable, "no captions"):
                youtube.fetch_transcript_supadata("4sH30KUfPpM")


class ProviderChoiceTest(unittest.TestCase):
    def test_prefers_supadata_when_key_set(self):
        with mock.patch.object(config, "SUPADATA_API_KEY", "sd"), \
                mock.patch.object(youtube, "fetch_transcript_supadata", return_value=([], "en", None)) as supa, \
                mock.patch.object(youtube, "fetch_transcript_direct") as direct:
            youtube.fetch_transcript("abc")
        supa.assert_called_once()
        direct.assert_not_called()

    def test_falls_back_locally_but_not_on_vercel(self):
        failing = mock.patch.object(youtube, "fetch_transcript_supadata", side_effect=youtube.TranscriptUnavailable("quota"))
        with mock.patch.object(config, "SUPADATA_API_KEY", "sd"), failing:
            with mock.patch.object(config, "ON_VERCEL", False), \
                    mock.patch.object(youtube, "fetch_transcript_direct", return_value=([], "en", True)) as direct:
                youtube.fetch_transcript("abc")
            direct.assert_called_once()
            with mock.patch.object(config, "ON_VERCEL", True), mock.patch.object(youtube, "fetch_transcript_direct") as direct:
                with self.assertRaises(youtube.TranscriptUnavailable):
                    youtube.fetch_transcript("abc")
            direct.assert_not_called()

    def test_no_key_reads_youtube_directly(self):
        with mock.patch.object(config, "SUPADATA_API_KEY", None), \
                mock.patch.object(youtube, "fetch_transcript_direct", return_value=([], "en", True)) as direct:
            youtube.fetch_transcript("abc")
        direct.assert_called_once()


class VideoInfoTest(unittest.TestCase):
    def test_uses_supadata_details_when_watch_page_is_blocked(self):
        details = {"title": "Jobs report", "channel": {"name": "News"}, "uploadDate": "2026-06-05T12:00:00Z"}
        with mock.patch.object(config, "SUPADATA_API_KEY", "sd"), \
                mock.patch.object(youtube, "_scrape_watch_page"), \
                mock.patch.object(youtube.urllib.request, "urlopen", return_value=FakeResponse(details)):
            info = youtube.fetch_info("4sH30KUfPpM")
        self.assertEqual((info.title, info.channel, info.upload_date), ("Jobs report", "News", date(2026, 6, 5)))

    def test_skips_supadata_when_page_worked(self):
        def scrape(info):
            info.upload_date = date(2026, 6, 5)

        with mock.patch.object(config, "SUPADATA_API_KEY", "sd"), \
                mock.patch.object(youtube, "_scrape_watch_page", side_effect=scrape), \
                mock.patch.object(youtube, "_supadata") as supadata:
            youtube.fetch_info("4sH30KUfPpM")
        supadata.assert_not_called()


if __name__ == "__main__":
    unittest.main()
