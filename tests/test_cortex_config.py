"""Cortex routing without network access."""
import unittest
from unittest import mock

from legit import config, llm


class CortexRoutingTest(unittest.TestCase):
    def test_cortex_url_normalizes_identifiers(self):
        expected = "https://myorg-my-account.snowflakecomputing.com/api/v2/cortex/v1/chat/completions"
        self.assertEqual(llm.cortex_url("MYORG-MY_ACCOUNT"), expected)
        self.assertEqual(llm.cortex_url("https://myorg-my_account.snowflakecomputing.com/"), expected)
        self.assertEqual(llm.cortex_url("myorg-my-account.snowflakecomputing.com"), expected)

    def test_endpoint_routes_by_prefix(self):
        with mock.patch.object(config, "CORTEX_ACCOUNT", "ORG-ACCT"), mock.patch.object(config, "CORTEX_TOKEN", "t"):
            url, key, name = llm.endpoint("cortex:claude-haiku-4-5")
            self.assertIn("org-acct.snowflakecomputing.com", url)
            self.assertEqual((key, name), ("t", "claude-haiku-4-5"))
            url, _, name = llm.endpoint("qwen/qwen3.8-27b")
            self.assertEqual((url, name), (llm.GROQ_URL, "qwen/qwen3.8-27b"))

    def test_cortex_request_has_no_groq_only_fields(self):
        sent = {}

        def fake_post(body, timeout):
            sent.update(body)
            return {"choices": [{"message": {"content": [{"type": "text", "text": '{"ok": true}'}]}}]}

        with mock.patch.object(llm, "_post", fake_post):
            reply = llm.chat([{"role": "user", "content": "x"}], model="cortex:claude-haiku-4-5", json_mode=True)
        self.assertNotIn("response_format", sent)
        self.assertNotIn("reasoning_effort", sent)
        self.assertEqual(llm.parse_json(reply["content"]), {"ok": True})

    def test_cortex_rejects_tools(self):
        with self.assertRaises(llm.LLMError):
            llm.chat([{"role": "user", "content": "x"}], model="cortex:claude-haiku-4-5", tools=[{"type": "browser_search"}])

    def test_chat_any_falls_back_when_cortex_unconfigured(self):
        calls = []

        def fake_chat(messages, model=None, **kw):
            calls.append(model)
            if llm.is_cortex(model):
                raise llm.LLMError("Snowflake Cortex is not configured")
            return {"content": "{}"}

        with mock.patch.object(llm, "chat", fake_chat):
            _, used = llm.chat_any(["cortex:claude-haiku-4-5", "qwen/qwen3.8-27b"], [])
        self.assertEqual(used, "qwen/qwen3.8-27b")
        self.assertEqual(calls, ["cortex:claude-haiku-4-5", "qwen/qwen3.8-27b"])


if __name__ == "__main__":
    unittest.main()
