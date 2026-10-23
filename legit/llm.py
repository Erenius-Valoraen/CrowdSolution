"""LLM client: Snowflake Cortex or Groq for JSON extraction, and Groq browser search for web checks.

Both expose OpenAI-compatible chat completions. Model names starting with "cortex:" go to Snowflake Cortex;
everything else goes to Groq. Keys come from the environment or the gitignored .env file."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import config

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_SPEECH_URL = "https://api.groq.com/openai/v1/audio/speech"
SPEECH_CHARS = 200  # text per speech request; longer text is split at sentence breaks and the audio joined
# Audio formats Whisper accepts, by the MIME type browsers record in.
AUDIO_EXTENSIONS = {"audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
                    "audio/aac": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
                    "audio/flac": "flac"}
API_URL = GROQ_URL  # kept for older imports
CORTEX_PATH = "/api/v2/cortex/v1/chat/completions"


class LLMError(RuntimeError):
    pass


class RateLimited(LLMError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class SpeechUnavailable(LLMError):
    """Text-to-speech isn't enabled for this account, e.g. the model's terms haven't been accepted."""


def groq_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def cortex_available() -> bool:
    return config.cortex_configured()


def available() -> bool:
    """True when any extraction model is usable."""
    return groq_available() or cortex_available()


def is_cortex(model: str) -> bool:
    return model.startswith(config.CORTEX_PREFIX)


def cortex_url(account: str) -> str:
    """Account identifier or URL -> REST endpoint. Underscores aren't allowed in hostnames, so they become hyphens."""
    host = account.strip().lower()
    host = re.sub(r"^https?://", "", host).split("/")[0]
    host = host.removesuffix(".snowflakecomputing.com").replace("_", "-")
    return f"https://{host}.snowflakecomputing.com{CORTEX_PATH}"


def endpoint(model: str) -> tuple[str, str | None, str]:
    """(url, bearer token, model name the provider expects)."""
    if is_cortex(model):
        url = cortex_url(config.CORTEX_ACCOUNT) if config.CORTEX_ACCOUNT else ""
        return url, config.CORTEX_TOKEN, model[len(config.CORTEX_PREFIX):]
    return GROQ_URL, os.environ.get("GROQ_API_KEY"), model


def _retry_after(message: str) -> float | None:
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", message)
    if not m:
        return None
    return float(m.group(1) or 0) * 60 + float(m.group(2))


def _post(body: dict, timeout: float) -> dict:
    url, key, api_model = endpoint(body["model"])
    provider = "Snowflake Cortex" if is_cortex(body["model"]) else "Groq"
    if not key or not url:
        raise LLMError(f"{provider} is not configured")
    payload = dict(body, model=api_model)
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "crowdsolution-legit/0.3",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").replace(key, "***")
        try:
            parsed = json.loads(detail)
            message = parsed["error"]["message"] if isinstance(parsed.get("error"), dict) else parsed.get("message", detail)
        except (ValueError, KeyError, TypeError, AttributeError):
            message = detail[:300]
        if e.code == 429:
            raise RateLimited(f"{provider}: {message}", _retry_after(str(message))) from None
        raise LLMError(f"HTTP {e.code} from {provider}: {str(message)[:300]}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"network error reaching {provider}: {e}") from None


def chat(messages: list[dict], *, model: str | None = None, json_mode: bool = False, tools: list | None = None,
         reasoning_effort: str | None = "low", timeout: float = 60, max_wait: float = 20.0) -> dict:
    """Send a chat request and return the assistant message dict.

    Retries short rate-limit waits and transient server errors."""
    model = model or config.GROQ_MODEL
    body: dict = {"model": model, "messages": messages}
    if is_cortex(model):
        if tools:
            raise LLMError("tools not supported on Snowflake Cortex chat completions")
        # OpenAI reasoning models on Cortex only accept the default temperature.
        if json_mode and not model[len(config.CORTEX_PREFIX):].startswith("openai-"):
            body["temperature"] = 0  # parse_json pulls the object out of the reply
    else:
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
            message = data["choices"][0]["message"]
            if isinstance(message.get("content"), list):  # some providers return content blocks
                message["content"] = "".join(p.get("text", "") for p in message["content"] if isinstance(p, dict))
            return message
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


SKIPPABLE = ("HTTP 400", "HTTP 401", "HTTP 403", "HTTP 404", "HTTP 413", "decommissioned", "does not exist",
             "not supported", "not available", "not configured", "Failed to validate JSON", "gave up after retries",
             "network error")


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
            if any(s in text for s in SKIPPABLE):
                problems.append(f"{model}: {text[:80]}")
                continue
            raise
    raise RateLimited("no model available (" + "; ".join(problems) + ")", last_wait)


def audio_extension(content_type: str | None) -> str | None:
    """File extension Whisper needs for a recording's MIME type (codec parameters ignored), or None if unsupported."""
    return AUDIO_EXTENSIONS.get((content_type or "").split(";")[0].strip().lower())


def _multipart(fields: dict[str, str], filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(audio: bytes, content_type: str, *, prompt: str | None = None, timeout: float = 60) -> tuple[str, str]:
    """Speech to text with Groq Whisper. Returns (text, model). Moves to the next model when one is rate limited."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMError("Groq is not configured")
    ext = audio_extension(content_type)
    if ext is None:
        raise LLMError(f"unsupported audio type: {content_type}")
    mime = content_type.split(";")[0].strip()
    last_wait: float | None = None
    for model in config.TRANSCRIBE_MODELS:
        fields = {"model": model, "response_format": "json", "temperature": "0"}
        if prompt:
            fields["prompt"] = prompt  # vocabulary hint, so names like "Zelle" or "UT Austin" are spelled right
        body, form_type = _multipart(fields, f"speech.{ext}", audio, mime)
        req = urllib.request.Request(GROQ_TRANSCRIBE_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": form_type, "Accept": "application/json",
            "User-Agent": "crowdsolution-legit/0.3",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return " ".join(str(json.load(resp).get("text") or "").split()), model
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace").replace(key, "***")[:300]
            if e.code == 429:
                last_wait = _retry_after(detail)
                continue
            raise LLMError(f"HTTP {e.code} from Groq speech-to-text: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"network error reaching Groq: {e}") from None
    raise RateLimited("speech-to-text is rate limited", last_wait)


def speech_chunks(text: str, limit: int = SPEECH_CHARS) -> list[str]:
    """Split text into pieces of at most `limit` characters, at sentence breaks, then commas or spaces."""
    chunks: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", " ".join(text.split())):
        while len(sentence) > limit:
            cut = max(sentence.rfind(", ", 0, limit), sentence.rfind(" ", 0, limit))
            cut = cut if cut > 0 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut + 1].strip())
            sentence = sentence[cut + 1:].strip()
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def _wav_parts(blob: bytes) -> tuple[bytes, bytes]:
    """(fmt chunk, audio data) of a WAV file. Tolerates streamed headers whose sizes are unknown."""
    if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise LLMError("speech audio wasn't a WAV file")
    pos, fmt = 12, None
    while pos + 8 <= len(blob):
        chunk_id, size = blob[pos:pos + 4], int.from_bytes(blob[pos + 4:pos + 8], "little")
        start = pos + 8
        if chunk_id == b"data":
            end = start + size if 0 < size <= len(blob) - start else len(blob)
            if fmt is None:
                break
            return fmt, blob[start:end]
        if chunk_id == b"fmt ":
            fmt = blob[start:start + size]
        pos = start + size + (size & 1)
    raise LLMError("speech audio was missing its format or data")


def merge_wav(parts: list[bytes]) -> bytes:
    """Join WAV clips with the same format into one file."""
    if len(parts) == 1:
        return parts[0]
    fmt, first = _wav_parts(parts[0])
    audio = first + b"".join(_wav_parts(p)[1] for p in parts[1:])
    return (b"RIFF" + (4 + 8 + len(fmt) + 8 + len(audio)).to_bytes(4, "little") + b"WAVE"
            + b"fmt " + len(fmt).to_bytes(4, "little") + fmt + b"data" + len(audio).to_bytes(4, "little") + audio)


def speak(text: str, *, voice: str | None = None, timeout: float = 60) -> bytes:
    """Text to speech with Groq. Returns WAV audio. Raises SpeechUnavailable when the account can't use the model."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise SpeechUnavailable("Groq is not configured")
    chunks = speech_chunks(text)
    if not chunks:
        raise LLMError("nothing to say")

    def one(chunk: str) -> bytes:
        body = json.dumps({"model": config.TTS_MODEL, "voice": voice or config.TTS_VOICE, "input": chunk,
                           "response_format": "wav"}).encode("utf-8")
        req = urllib.request.Request(GROQ_SPEECH_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "audio/wav",
            "User-Agent": "crowdsolution-legit/0.3",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace").replace(key, "***")[:300]
            if e.code == 429:
                raise RateLimited(f"Groq text-to-speech: {detail}", _retry_after(detail)) from None
            if e.code in (401, 403, 404) or any(s in detail for s in ("terms", "does not exist", "decommissioned")):
                raise SpeechUnavailable(f"Groq text-to-speech unavailable: {detail}") from None
            raise LLMError(f"HTTP {e.code} from Groq text-to-speech: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"network error reaching Groq: {e}") from None

    with ThreadPoolExecutor(3) as pool:
        return merge_wav(list(pool.map(one, chunks)))


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
