"""
OpenRouter over HTTP: the free models, a streamed reply, today's allowance.

The key is read from ``OPENROUTER_API_KEY`` at the moment it is needed and
passed straight into a header. It is never stored in settings, never put in
an exception message and never logged, so nothing Evans writes to disk or
shows on screen can leak it. :class:`Client` keeps it in a private attribute
and leaves it out of its ``repr``.

Free models are rate limited per account: 20 requests a minute, and 50 a day
(1000 once the account has bought 10 credits). A 429 is therefore an
ordinary outcome, not a fault, and gets a message that says which limit.

Streaming is Server-Sent Events. Lines starting with ``:`` are OpenRouter's
keep-alive comments; ``data: [DONE]`` ends the stream; and an error that
happens after the reply has started arrives as a ``data:`` event with an
``error`` field under an HTTP 200, so a 200 is not proof of success.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

API_BASE = "https://openrouter.ai/api/v1"
ENV_KEY = "OPENROUTER_API_KEY"

#: Cohere's coding model: small and quick, and its host says it does not
#: train on prompts. Free models come and go (some carry an expiry date), so
#: :func:`pick_model` falls back when this one is gone.
DEFAULT_MODEL = "cohere/north-mini-code:free"

#: A cap on each reply. The answers wanted here are short — a rewritten
#: section, a command or two — and a free model left unbounded can ramble
#: through thousands of tokens of reasoning.
MAX_REPLY_TOKENS = 1500

#: Seconds. Connecting is quick or broken; a free model can sit in a queue
#: for a while before its first token, and OpenRouter's keep-alive comments
#: arrive well inside this between tokens.
TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=20.0, pool=10.0)

#: Shows up as the app's name on OpenRouter's side; it carries nothing about
#: the user.
APP_HEADERS = {"X-Title": "Evans"}


def api_key() -> str | None:
    """The key from the environment, or ``None`` when it is not set."""
    key = os.environ.get(ENV_KEY, "").strip()
    return key or None


class AssistantError(Exception):
    """
    A request that did not produce a reply, said in the user's terms.

    ``kind`` lets the panel react without parsing text: ``"no_key"``,
    ``"auth"``, ``"rate_limit"``, ``"credits"``, ``"data_policy"``,
    ``"model"``, ``"network"``, ``"provider"``.
    """

    def __init__(self, message: str, kind: str = "provider", *,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    context_length: int = 0
    #: The model takes ``tools``; a hint that it follows instructions about
    #: output format, which the reply protocol relies on.
    tools: bool = False


@dataclass
class Reply:
    """What a finished stream produced."""
    text: str = ""
    finish_reason: str | None = None
    #: Token counts from the final chunk, when the provider sends them.
    usage: dict[str, Any] = field(default_factory=dict)
    #: The model that actually answered (a router may pick another).
    model: str = ""
    cancelled: bool = False


@dataclass(frozen=True)
class Allowance:
    """Free-model requests left today (UTC), from ``GET /key``."""
    used: int
    limit: int
    remaining: int


class Client:
    """
    One OpenRouter account, by its key.

    ``transport`` is for tests: an :class:`httpx.MockTransport` answers in
    place of the network.
    """

    def __init__(self, key: str | None = None, *,
                 transport: httpx.BaseTransport | None = None,
                 base_url: str = API_BASE) -> None:
        self._key = key
        self._transport = transport
        self._base = base_url.rstrip("/")

    def __repr__(self) -> str:
        return f"Client(base_url={self._base!r}, key={'set' if self._key else 'unset'})"

    # ── plumbing ──────────────────────────────────────────────

    def _http(self) -> httpx.Client:
        return httpx.Client(timeout=TIMEOUT, transport=self._transport,
                            headers=APP_HEADERS)

    def _auth(self) -> dict[str, str]:
        if not self._key:
            raise AssistantError(
                f"No OpenRouter key: set {ENV_KEY} and restart Evans.", "no_key")
        return {"Authorization": f"Bearer {self._key}"}

    # ── the free models ───────────────────────────────────────

    def free_models(self) -> list[ModelInfo]:
        """
        The free text models OpenRouter offers right now, best known first.

        The list needs no key. Image and audio models are left out, and so is
        the ``openrouter/free`` router: it sends each request to a random
        model, so neither quality nor the host's privacy terms would hold
        from one question to the next.
        """
        try:
            with self._http() as http:
                response = http.get(f"{self._base}/models")
        except httpx.HTTPError as exc:
            raise _network_error(exc) from None
        if response.status_code != 200:
            raise _http_error(response)
        try:
            data = response.json()["data"]
        except (ValueError, KeyError, TypeError):
            raise AssistantError("OpenRouter sent a model list Evans could "
                                 "not read.") from None
        return [m for m in (_model_info(entry) for entry in data) if m]

    # ── today's allowance ─────────────────────────────────────

    def allowance(self) -> Allowance | None:
        """Free requests left today, or ``None`` if OpenRouter does not say."""
        try:
            with self._http() as http:
                response = http.get(f"{self._base}/key", headers=self._auth())
        except httpx.HTTPError as exc:
            raise _network_error(exc) from None
        if response.status_code != 200:
            raise _http_error(response)
        try:
            daily = response.json()["data"]["free_model_daily_requests"]
            return Allowance(int(daily["used"]), int(daily["limit"]),
                             int(daily["remaining"]))
        except (ValueError, KeyError, TypeError):
            return None

    # ── a reply ───────────────────────────────────────────────

    def stream(self, model: str, messages: list[dict[str, str]], *,
               on_text: Callable[[str], None] | None = None,
               cancel: threading.Event | None = None) -> Reply:
        """
        Ask ``model`` and stream the answer, calling ``on_text`` per piece.

        Runs on the caller's thread (the panel calls it from a worker).
        Setting ``cancel`` stops at the next piece and closes the
        connection, which on most hosts stops the model too.
        """
        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": MAX_REPLY_TOKENS,
            "temperature": 0.2,
        }
        reply = Reply(model=model)
        pieces: list[str] = []
        try:
            with self._http() as http, http.stream(
                    "POST", f"{self._base}/chat/completions",
                    headers=self._auth(), json=body) as response:
                if response.status_code != 200:
                    response.read()
                    raise _http_error(response)
                for event in _events(response.iter_lines()):
                    if cancel is not None and cancel.is_set():
                        reply.cancelled = True
                        break
                    if "error" in event:
                        raise _error_from(event["error"], 200)
                    reply.model = event.get("model") or reply.model
                    if event.get("usage"):
                        reply.usage = event["usage"]
                    for choice in event.get("choices") or ():
                        text = (choice.get("delta") or {}).get("content")
                        if text:
                            pieces.append(text)
                            if on_text is not None:
                                on_text(text)
                        if choice.get("finish_reason"):
                            reply.finish_reason = choice["finish_reason"]
        except httpx.HTTPError as exc:
            raise _network_error(exc) from None
        reply.text = "".join(pieces)
        if reply.finish_reason == "error":
            raise AssistantError("The model stopped with an error part-way "
                                 "through its reply.")
        if not reply.text and not reply.cancelled:
            raise AssistantError("The model sent an empty reply. Try again, "
                                 "or pick another model.", "model")
        return reply


def pick_model(models: list[ModelInfo], wanted: str | None) -> str | None:
    """
    The model to use: ``wanted`` if it is still offered, else a fallback.

    The fallback prefers a coding model, then one that takes tools (it is
    more likely to keep to the reply format), then whatever is first.
    """
    ids = [m.id for m in models]
    for choice in (wanted, DEFAULT_MODEL):
        if choice and choice in ids:
            return choice
    for test in (lambda m: "code" in m.id or "coder" in m.id,
                 lambda m: m.tools,
                 lambda m: True):
        for m in models:
            if test(m):
                return m.id
    return None


# ── parsing ───────────────────────────────────────────────────────

def _model_info(entry: dict[str, Any]) -> ModelInfo | None:
    """A free text-in, text-out model from one list entry; else ``None``."""
    try:
        model_id = str(entry["id"])
        pricing = entry.get("pricing") or {}
        free = model_id.endswith(":free") or (
            _zero(pricing.get("prompt")) and _zero(pricing.get("completion")))
        arch = entry.get("architecture") or {}
        text_io = ("text" in (arch.get("input_modalities") or ["text"])
                   and (arch.get("output_modalities") or ["text"]) == ["text"])
    except (KeyError, TypeError):
        return None
    if not free or not text_io or model_id == "openrouter/free":
        return None
    return ModelInfo(
        id=model_id,
        name=str(entry.get("name") or model_id),
        context_length=int(entry.get("context_length") or 0),
        tools="tools" in (entry.get("supported_parameters") or ()),
    )


def _zero(price: Any) -> bool:
    try:
        return price is not None and float(price) == 0.0
    except (TypeError, ValueError):
        return False


def _events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """
    The JSON events of a Server-Sent Events stream.

    Comment lines (``: OPENROUTER PROCESSING``), blank separators and any
    other field are skipped; ``[DONE]`` ends it. An event split across
    several ``data:`` lines is joined, as the format allows.
    """
    data: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
            continue
        if line.strip() or not data:
            continue                         # a comment, another field
        payload, data = "\n".join(data), []
        if payload.strip() == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except ValueError:
            continue
    if data and "\n".join(data).strip() != "[DONE]":
        try:
            yield json.loads("\n".join(data))
        except ValueError:
            pass


def _http_error(response: httpx.Response) -> AssistantError:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    retry = response.headers.get("Retry-After")
    return _error_from(error, response.status_code,
                       retry_after=_seconds(retry))


def _error_from(error: dict[str, Any] | Any, status: int, *,
                retry_after: float | None = None) -> AssistantError:
    """An OpenRouter error object as a message a user can act on."""
    if not isinstance(error, dict):
        error = {"message": str(error)}
    code = error.get("code", status)
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = status
    raw = str(error.get("message") or "").strip()
    if code == 401:
        return AssistantError(f"OpenRouter did not accept the key in {ENV_KEY}. "
                              "Check it, then restart Evans.", "auth")
    if code == 402:
        return AssistantError("OpenRouter says the account has no credit left "
                              "for this model.", "credits")
    if code == 429:
        wait = f" Try again in {retry_after:.0f} s." if retry_after else ""
        return AssistantError(
            "Free-model limit reached: 20 requests a minute, and 50 a day "
            "(1000 a day once the account has bought 10 credits)." + wait,
            "rate_limit", retry_after=retry_after)
    if code == 404 and "data policy" in raw.lower():
        return AssistantError(
            "No host of this model meets your OpenRouter privacy settings "
            "(it may train on prompts). Pick another model, or change the "
            "setting at openrouter.ai/settings/privacy.", "data_policy")
    if code in (400, 404):
        return AssistantError(f"OpenRouter refused the request: {raw or code}. "
                              "The model may have been withdrawn — pick "
                              "another.", "model")
    return AssistantError(f"The model's host failed ({code}): "
                          f"{raw or 'no details'}. Try again shortly.")


def _network_error(exc: httpx.HTTPError) -> AssistantError:
    if isinstance(exc, httpx.TimeoutException):
        return AssistantError("OpenRouter took too long to answer.", "network")
    return AssistantError("Could not reach OpenRouter — check the internet "
                          "connection.", "network")


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None
