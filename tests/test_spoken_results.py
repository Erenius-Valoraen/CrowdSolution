"""Spoken results: summary text, speech chunking and WAV joining, and the two endpoints. No network."""
import io
import os
import unittest
import urllib.error
import wave
from unittest import mock

os.environ.setdefault("COMMUNITY_MEMORY", "off")

from fastapi.testclient import TestClient  # noqa: E402

from api import main, service  # noqa: E402
from legit import llm  # noqa: E402

PAYLOAD = {
    "id": "chk_test", "overall": "HIGH RISK", "summary": "A rental listing near campus.",
    "counts": {"red_flag": 2, "caution": 1, "ok": 0, "info": 0, "unverified": 0, "total": 3},
    "findings": [
        {"status": "red_flag", "status_label": "RED FLAG", "title": "Rent compared with local median", "quote": "$650/month",
         "summary": "$650/month is 34% of the median for Austin. Rent far below normal is a common scam sign. See https://x.gov",
         "data": {}},
        {"status": "caution", "status_label": "CAUTION", "title": "Web check: Deposit by Zelle", "quote": "Zelle",
         "summary": "Hard to reverse.", "data": {"claimed": "Zelle deposit", "found": "Zelle payments can't be reversed"}},
    ],
    "action_checklist": ["Never send a deposit by Zelle.", "Ask for a walkthrough.", "Check the address."],
}


def wav_bytes(frames: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x01\x00" * frames)
    return out.getvalue()


class SummaryTextTest(unittest.TestCase):
    def test_template_reads_well_and_has_no_links(self):
        text = service.template_spoken_summary(PAYLOAD)
        self.assertTrue(text.startswith("This looks high risk. I checked 3 things and found 2 red flags, and 1 thing to be careful about."))
        self.assertIn("Deposit by Zelle: The sources say Zelle payments can't be reversed.", text)
        self.assertIn("Before you act: Never send a deposit by Zelle. Ask for a walkthrough.", text)
        self.assertNotIn("http", text)

    def test_ai_summary_is_cleaned(self):
        reply = ({"content": "<think>plan</think>**High risk.** Don't pay the deposit by Zelle, see https://ftc.gov before you do."}, "cortex:x")
        with mock.patch.object(llm, "available", return_value=True), mock.patch.object(llm, "chat_any", return_value=reply):
            self.assertEqual(service.spoken_summary(PAYLOAD), ("High risk. Don't pay the deposit by Zelle, see before you do.", "ai"))

    def test_template_skips_repeats_and_uses_official_figures(self):
        stat = {"status": "caution", "title": "Total nonfarm jobs: United States", "checker": "statistic", "summary": "Wrong when said.",
                "data": {"claimed": "172,000 jobs added", "figures": {"when_said": {"value": "140,000 jobs", "period": "May 2026"}}}}
        payload = dict(PAYLOAD, overall="BE CAREFUL", findings=[stat, dict(stat)], action_checklist=[])
        text = service.template_spoken_summary(payload)
        self.assertIn("Total nonfarm jobs: It said 172,000 jobs added, but official data showed 140,000 jobs for May 2026.", text)
        self.assertEqual(text.count("Total nonfarm jobs"), 1)

    def test_falls_back_to_template(self):
        with mock.patch.object(llm, "available", return_value=True), \
                mock.patch.object(llm, "chat_any", side_effect=llm.RateLimited("busy")):
            text, source = service.spoken_summary(PAYLOAD)
        self.assertEqual(source, "template")
        self.assertTrue(text.startswith("This looks high risk."))

    def test_long_text_is_cut_at_a_sentence(self):
        text = service.clean_spoken("First sentence here. " * 100, limit=50)
        self.assertEqual(text, "First sentence here. First sentence here.")


class SpeechTest(unittest.TestCase):
    def test_chunks_respect_limit_and_keep_decimals(self):
        text = "Unemployment was 4.3 percent in May. " + "word " * 60 + "End."
        chunks = llm.speech_chunks(text, limit=80)
        self.assertTrue(all(len(c) <= 80 for c in chunks))
        self.assertEqual(chunks[0], "Unemployment was 4.3 percent in May.")
        self.assertEqual(" ".join(chunks), " ".join(text.split()))

    def test_merge_wav(self):
        merged = llm.merge_wav([wav_bytes(100), wav_bytes(250)])
        with wave.open(io.BytesIO(merged)) as w:
            self.assertEqual((w.getnframes(), w.getframerate()), (350, 8000))

    def test_terms_not_accepted_is_unavailable(self):
        error = urllib.error.HTTPError(llm.GROQ_SPEECH_URL, 400, "Bad Request", {},
                                       io.BytesIO(b'{"error": {"code": "model_terms_required", "message": "requires terms acceptance"}}'))
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}), \
                mock.patch.object(llm.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(llm.SpeechUnavailable):
                llm.speak("Hello there.")


class EndpointTest(unittest.TestCase):
    client = TestClient(main.app)

    def setUp(self):
        main._speech.cache_clear()

    def test_spoken_summary_is_generated_once_and_saved(self):
        with mock.patch.object(main.storage, "get_scan", return_value=dict(PAYLOAD)), \
                mock.patch.object(main.storage, "update_payload") as save, \
                mock.patch.object(service, "spoken_summary", return_value=("High risk.", "ai")):
            res = self.client.post("/api/scans/chk_test/spoken-summary")
        self.assertEqual(res.json(), {"text": "High risk.", "source": "ai"})
        self.assertEqual(save.call_args.args[1]["spoken_summary"], {"text": "High risk.", "source": "ai"})
        cached = dict(PAYLOAD, spoken_summary={"text": "Saved.", "source": "ai"})
        with mock.patch.object(main.storage, "get_scan", return_value=cached), \
                mock.patch.object(service, "spoken_summary") as generate:
            self.assertEqual(self.client.post("/api/scans/chk_test/spoken-summary").json()["text"], "Saved.")
        generate.assert_not_called()

    def test_spoken_summary_unknown_scan(self):
        with mock.patch.object(main.storage, "get_scan", return_value=None):
            self.assertEqual(self.client.post("/api/scans/nope/spoken-summary").status_code, 404)

    def test_speak_returns_audio_or_503(self):
        with mock.patch.object(llm, "groq_available", return_value=True):
            with mock.patch.object(llm, "speak", return_value=wav_bytes(10)):
                res = self.client.post("/api/speak", json={"text": "Hello  there."})
            self.assertEqual((res.status_code, res.headers["content-type"]), (200, "audio/wav"))
            main._speech.cache_clear()
            with mock.patch.object(llm, "speak", side_effect=llm.SpeechUnavailable("terms")):
                self.assertEqual(self.client.post("/api/speak", json={"text": "Hi."}).status_code, 503)
            self.assertEqual(self.client.post("/api/speak", json={"text": ""}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
