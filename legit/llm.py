"""Groq API client: JSON chat for extraction, and browser search for web checks.

Groq's API is OpenAI-compatible. The key comes from GROQ_API_KEY (environment or the gitignored .env)."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import config

API_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(RuntimeError):
    pass


class RateLimited(LLMError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def _retry_after(message: str) -> float | None:
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", message)
    if not m:
        return None
    return float(m.group(1) or 0) * 60 + float(m.group(2))


def _post(body: dict, timeout: float) -> dict:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMError("GROQ_API_KEY is not set")
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "crowdsolution-legit/0.2",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            message = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = detail[:300]
        if e.code == 429:
            raise RateLimited(message, _retry_after(message)) from None
        raise LLMError(f"HTTP {e.code}: {message[:300]}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"network error: {e}") from None


def chat(messages: list[dict], *, model: str | None = None, json_mode: bool = False, tools: list | None = None,
         reasoning_effort: str | None = "low", timeout: float = 60, max_wait: float = 20.0) -> dict:
    """Send a chat request and return the assistant message dict.

    Retries short rate-limit waits and transient server errors."""
    model = model or config.GROQ_MODEL
    body: dict = {"model": model, "messages": messages}
    qwen = model.startswith("qwen/")
    if json_mode:
        body["temperature"] = 0
        if not qwen:  # Qwen fails Groq's strict JSON validation; parse_json handles its plain output
            body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
    if qwen:
        body["reasoning_effort"] = "none"  # with thinking on, Qwen spends its whole output budget reasoning
    elif reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    last: Exception | None = None
    for attempt in range(3):
        try:
            data = _post(body, timeout)
            return data["choices"][0]["message"]
        except RateLimited as e:
            last = e
            if attempt < 2 and e.retry_after is not None and e.retry_after <= max_wait:
                time.sleep(e.retry_after + 0.5)
                continue
            raise
        except LLMError as e:
            last = e
            text = str(e)
            if "reasoning_effort" in text and "reasoning_effort" in body:
                body.pop("reasoning_effort")
                continue
            if "Failed to validate JSON" in text and "response_format" in body:
                # Strict JSON mode rejected the output; retry free-form and let parse_json find the object.
                body.pop("response_format")
                continue
            if text.startswith("HTTP 5") and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected response shape: {e}") from None
    raise LLMError(f"gave up after retries: {last}")


def chat_any(models: list[str], messages: list[dict], **kwargs) -> tuple[dict, str]:
    """Try each model in order, moving on when one is rate limited or unavailable. Returns (message, model)."""
    problems: list[str] = []
    last_wait: float | None = None
    for model in models:
        try:
            return chat(messages, model=model, **kwargs), model
        except RateLimited as e:
            problems.append(f"{model} rate limited")
            last_wait = e.retry_after
        except LLMError as e:
            text = str(e)
            if any(s in text for s in ("HTTP 404", "HTTP 413", "decommissioned", "does not exist", "not supported",
                                       "Failed to validate JSON", "gave up after retries")):
                problems.append(f"{model}: {text[:80]}")
                continue
            raise
    raise RateLimited("no model available (" + "; ".join(problems) + ")", last_wait)


def parse_json(text: str | None) -> dict | None:
    """Pull a JSON object out of model output that may include prose or code fences."""
    if not text:
        return None
    text = text.strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    for chunk in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)):
        try:
            value = json.loads(chunk)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    found, i = [], 0
    while True:
        j = text.find("{", i)
        if j < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, j)
            if isinstance(obj, dict):
                found.append(obj)
            i = end
        except json.JSONDecodeError:
            i = j + 1
    return found[-1] if found else None
