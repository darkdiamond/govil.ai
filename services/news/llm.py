"""OpenRouter client for the news job — chat (with tools), web search, images.

Spending is capped outside the code (the key's limit in OpenRouter, a GCP
budget alert); a refused key (401/402/403) raises `LLMUnavailable` and the
run stops cleanly. Each response's reported cost is summed for the run log,
for visibility only. Transient failures (429, 5xx, timeouts) retry with
backoff.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time

import httpx

log = logging.getLogger(__name__)

BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
TEXT_MODEL = os.environ.get("NEWS_MODEL", "openai/gpt-6.1-terra")
# OpenRouter's unified `reasoning.effort` (minimal|low|medium|high|xhigh); empty = model default.
REASONING_EFFORT = os.environ.get("NEWS_REASONING_EFFORT", "high").strip()
IMAGE_MODEL = os.environ.get("NEWS_IMAGE_MODEL", "google/gemini-3.1-flash-image")
SEARCH_ENGINE = os.environ.get("NEWS_SEARCH_ENGINE", "exa")
RETRIES = 4


class LLMUnavailable(Exception):
    """The key was refused (limit reached, revoked): stop, don't retry."""


class LLMError(Exception):
    pass


class OpenRouter:
    def __init__(self, api_key: str | None = None, *, client: httpx.Client | None = None,
                 timeout: float = 240.0, sleep=time.sleep):
        key = (api_key or os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if not key and client is None:
            raise LLMUnavailable("OPENROUTER_API_KEY is not set")
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._headers = {"Authorization": f"Bearer {key}", "HTTP-Referer": "https://govil.ai",
                         "X-Title": "govil.ai news"}
        self._sleep = sleep
        self.cost_usd = 0.0
        self.calls = 0

    def _post(self, body: dict) -> dict:
        delay = 2.0
        for attempt in range(RETRIES):
            try:
                r = self._client.post("/chat/completions", json=body, headers=self._headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                err = f"{type(e).__name__}: {e}"
            else:
                if r.status_code in (401, 402, 403):
                    raise LLMUnavailable(f"OpenRouter refused the key: HTTP {r.status_code} {r.text[:200]}")
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except ValueError:  # a 200 with a cut-off or HTML body: retry like a 5xx
                        data = None
                    if not isinstance(data, dict):
                        err = f"HTTP 200 with a non-JSON body: {r.text[:200]}"
                    elif "error" in data and not data.get("choices"):
                        err = json.dumps(data["error"])[:300]
                    else:
                        self.calls += 1
                        self.cost_usd += float((data.get("usage") or {}).get("cost") or 0)
                        return data
                elif r.status_code == 429 or r.status_code >= 500:
                    err = f"HTTP {r.status_code}"
                else:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            if attempt < RETRIES - 1:
                log.warning("openrouter: %s — retry %d in %.0fs", err, attempt + 1, delay)
                self._sleep(delay)
                delay *= 2
        raise LLMError(f"OpenRouter failed after {RETRIES} attempts: {err}")

    def chat(self, messages: list[dict], *, model: str = TEXT_MODEL, tools: list[dict] | None = None,
             json_mode: bool = False, temperature: float | None = None,
             plugins: list[dict] | None = None,
             reasoning_effort: str | None = REASONING_EFFORT) -> dict:
        """The assistant message (with `tool_calls` / `annotations` when present).
        `temperature` is dropped by OpenRouter for models that don't take it
        (OpenAI reasoning models), so callers can pass it regardless."""
        body: dict = {"model": model, "messages": messages, "usage": {"include": True}}
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if temperature is not None:
            body["temperature"] = temperature
        if plugins:
            body["plugins"] = plugins
        data = self._post(body)
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"no message in response: {json.dumps(data)[:300]}") from e

    def chat_json(self, messages: list[dict], **kw) -> dict:
        """A JSON-object reply, parsed (one re-ask when the model wraps it in prose)."""
        msg = self.chat(messages, json_mode=True, **kw)
        try:
            return parse_json(msg.get("content") or "")
        except ValueError:
            msg = self.chat(messages + [msg, {"role": "user", "content":
                            "Reply with the JSON object only — no prose, no code fence."}],
                            json_mode=True, **kw)
            return parse_json(msg.get("content") or "")

    def web_search(self, query: str, *, max_results: int = 8, model: str = TEXT_MODEL) -> list[dict]:
        """Search results [{url, title, snippet}] via OpenRouter's web plugin.
        Results are leads: a writer must `fetch_url` a page before citing it."""
        msg = self.chat(
            [{"role": "user", "content": "Find recent, authoritative sources (news, official "
              f"publications) for this question and list them briefly:\n{query}"}],
            # Exa, not the model's native search: native grounding (Gemini's at
            # least) returns only opaque redirect links with no page text.
            model=model, plugins=[{"id": "web", "engine": SEARCH_ENGINE, "max_results": max_results}],
        )
        out, seen = [], set()
        for a in msg.get("annotations") or []:
            c = a.get("url_citation") or {}
            url = c.get("url")
            if url and url not in seen:
                seen.add(url)
                out.append({"url": url, "title": c.get("title") or "",
                            "snippet": (c.get("content") or "")[:2500]})
        return out

    def image(self, prompt: str, *, model: str = IMAGE_MODEL, aspect_ratio: str = "16:9") -> bytes:
        """One generated image's bytes."""
        data = self._post({"model": model, "messages": [{"role": "user", "content": prompt}],
                           "modalities": ["image", "text"],
                           "image_config": {"aspect_ratio": aspect_ratio},
                           "usage": {"include": True}})
        try:
            url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("no image in response") from e
        if not url.startswith("data:image/"):
            raise LLMError("image is not inline data")
        return base64.b64decode(url.split(",", 1)[1])


def parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in reply")
    obj = json.loads(t[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("reply is not a JSON object")  # noqa: TRY004 — callers catch ValueError
    return obj
