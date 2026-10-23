"""Voice typing: Groq Whisper request building, model fallback, and the /api/transcribe endpoint. No network."""
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

os.environ.setdefault("COMMUNITY_MEMORY", "off")

from fastapi.testclient import TestClient  # noqa: E402

from api import main  # noqa: E402
from legit import llm  # noqa: E402

AUDIO = b"\x1aE\xdf\xa3" + b"\0" * 2000  # webm header plus padding; the endpoint only checks type and size


def ok_response(text):
    return io.BytesIO(json.dumps({"text": text}).encode())


class TranscribeTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_audio_extensions(self):
        self.assertEqual(llm.audio_extension("audio/webm;codecs=opus"), "webm")
        self.assertEqual(llm.audio_extension("audio/mp4"), "m4a")
        self.assertIsNone(llm.audio_extension("text/plain"))

    def test_sends_multipart_with_model_prompt_and_file(self):
        with mock.patch.object(llm.urllib.request, "urlopen", return_value=ok_response("  Is this   legit? ")) as urlopen:
            text, model = llm.transcribe(AUDIO, "audio/webm;codecs=opus", prompt="Zelle")
        self.assertEqual((text, model), ("Is this legit?", "whisper-large-v3-turbo"))
        req = urlopen.call_args.args[0]
        self.assertTrue(req.get_header("Content-type").startswith("multipart/form-data; boundary="))
        for part in (b'name="model"\r\n\r\nwhisper-large-v3-turbo', b'name="prompt"\r\n\r\nZelle',
                     b'filename="speech.webm"\r\nContent-Type: audio/webm\r\n'):
            self.assertIn(part, req.data)

    def test_rate_limited_model_falls_back(self):
        limited = urllib.error.HTTPError(llm.GROQ_TRANSCRIBE_URL, 429, "Too Many Requests", {},
                                         io.BytesIO(b'{"error": {"message": "Please try again in 2s"}}'))
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=[limited, ok_response("hello")]):
            self.assertEqual(llm.transcribe(AUDIO, "audio/webm"), ("hello", "whisper-large-v3"))


class EndpointTest(unittest.TestCase):
    client = TestClient(main.app)

    def post(self, body=AUDIO, content_type="audio/webm;codecs=opus"):
        return self.client.post("/api/transcribe", content=body, headers={"Content-Type": content_type})

    def test_returns_text(self):
        with mock.patch.object(llm, "groq_available", return_value=True), \
                mock.patch.object(llm, "transcribe", return_value=("Is this legit?", "whisper-large-v3-turbo")) as tr:
            res = self.post()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"text": "Is this legit?", "model": "whisper-large-v3-turbo"})
        self.assertEqual(tr.call_args.args[1], "audio/webm;codecs=opus")

    def test_rejects_bad_requests(self):
        with mock.patch.object(llm, "groq_available", return_value=True):
            self.assertEqual(self.post(content_type="text/plain").status_code, 415)
            self.assertEqual(self.post(body=b"tiny").status_code, 400)
            with mock.patch.object(main, "MAX_AUDIO_BYTES", 1500):
                self.assertEqual(self.post().status_code, 413)

    def test_friendly_errors(self):
        with mock.patch.object(llm, "groq_available", return_value=False):
            self.assertEqual(self.post().status_code, 503)
        with mock.patch.object(llm, "groq_available", return_value=True):
            with mock.patch.object(llm, "transcribe", side_effect=llm.RateLimited("busy")):
                self.assertEqual(self.post().status_code, 429)
            with mock.patch.object(llm, "transcribe", return_value=("", "whisper-large-v3-turbo")):
                self.assertEqual(self.post().status_code, 422)


if __name__ == "__main__":
    unittest.main()
