"""
The assistant without a window: the OpenRouter client, the context rules and
the reply format.

No request leaves the machine: every client is given an
``httpx.MockTransport`` that answers from canned data, and records what it
was sent so the tests can check what *would* have gone out.
"""

from __future__ import annotations

import json
import threading

import httpx
import numpy as np
import pytest

from evans.assistant import client as orc
from evans.assistant import context as ctx
from evans.assistant import protocol
from evans.assistant.client import AssistantError, Client
from evans.assistant.protocol import Command, Edit, History, StaleEdit, Text

KEY = "sk-or-v1-test-0123456789abcdef"


# ── a fake OpenRouter ───────────────────────────────────────────────

MODELS = {"data": [
    {"id": "cohere/north-mini-code:free", "name": "Cohere: North Mini Code (free)",
     "pricing": {"prompt": "0", "completion": "0"}, "context_length": 256000,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
     "supported_parameters": ["tools", "max_tokens"]},
    {"id": "google/gemma-4-31b-it:free", "name": "Google: Gemma 4 31B (free)",
     "pricing": {"prompt": "0", "completion": "0"}, "context_length": 262144,
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
     "supported_parameters": ["tools"]},
    {"id": "openrouter/free", "name": "Free Models Router",
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "google/lyria-3-pro-preview", "name": "Lyria",
     "pricing": {"prompt": "0", "completion": "0"},
     "architecture": {"input_modalities": ["text"], "output_modalities": ["audio"]}},
    {"id": "anthropic/claude-x", "name": "Paid",
     "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
]}


def sse(*events, done=True, comments=True) -> bytes:
    lines = []
    if comments:
        lines += [": OPENROUTER PROCESSING", ""]
    for event in events:
        lines += [f"data: {json.dumps(event)}", ""]
    if done:
        lines += ["data: [DONE]", ""]
    return ("\n".join(lines) + "\n").encode()


def chunk(text=None, finish=None, **extra):
    delta = {"content": text} if text is not None else {}
    return {"model": "cohere/north-mini-code:free",
            "choices": [{"delta": delta, "finish_reason": finish}], **extra}


class Fake:
    """Routes requests to canned responses and remembers them."""

    def __init__(self, **routes):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes[request.url.path.rsplit("/", 1)[-1]]
        return handler(request) if callable(handler) else handler

    def client(self, key=KEY) -> Client:
        return Client(key, transport=httpx.MockTransport(self))


def streamed(body: bytes, status=200, headers=None) -> httpx.Response:
    return httpx.Response(status, content=body, headers={
        "content-type": "text/event-stream", **(headers or {})})


# ── the key ─────────────────────────────────────────────────────────

class TestKey:
    def test_read_from_the_environment_only(self, monkeypatch):
        monkeypatch.setenv(orc.ENV_KEY, f"  {KEY}\n")
        assert orc.api_key() == KEY
        monkeypatch.delenv(orc.ENV_KEY)
        assert orc.api_key() is None
        monkeypatch.setenv(orc.ENV_KEY, "   ")
        assert orc.api_key() is None

    def test_never_in_the_repr(self):
        assert KEY not in repr(Client(KEY))
        assert "set" in repr(Client(KEY))

    def test_sent_as_a_bearer_header_and_nowhere_else(self):
        fake = Fake(completions=streamed(sse(chunk("hi"), chunk(finish="stop"))))
        fake.client().stream("m", [{"role": "user", "content": "q"}])
        request = fake.requests[0]
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in str(request.url)
        assert KEY not in request.content.decode()

    def test_no_key_raises_before_any_request(self):
        fake = Fake()
        with pytest.raises(AssistantError) as err:
            fake.client(key=None).stream("m", [])
        assert err.value.kind == "no_key"
        assert fake.requests == []

    def test_errors_never_carry_the_key(self):
        fake = Fake(completions=httpx.Response(
            401, json={"error": {"code": 401, "message": "No auth credentials found"}}))
        with pytest.raises(AssistantError) as err:
            fake.client().stream("m", [])
        assert err.value.kind == "auth"
        assert KEY not in str(err.value)


# ── the model list ──────────────────────────────────────────────────

class TestModels:
    def test_free_text_models_only(self):
        fake = Fake(models=httpx.Response(200, json=MODELS))
        models = fake.client(key=None).free_models()
        assert [m.id for m in models] == ["cohere/north-mini-code:free",
                                          "google/gemma-4-31b-it:free"]
        assert models[0].tools and models[0].context_length == 256000

    def test_listing_needs_no_key(self):
        fake = Fake(models=httpx.Response(200, json=MODELS))
        fake.client(key=None).free_models()
        assert "authorization" not in fake.requests[0].headers

    def test_pick_keeps_the_choice_while_it_is_offered(self):
        models = Fake(models=httpx.Response(200, json=MODELS)).client().free_models()
        assert orc.pick_model(models, "google/gemma-4-31b-it:free") == \
            "google/gemma-4-31b-it:free"
        assert orc.pick_model(models, "gone/model:free") == orc.DEFAULT_MODEL

    def test_pick_falls_back_when_the_default_is_withdrawn(self):
        models = [orc.ModelInfo("a/chat:free", "A"),
                  orc.ModelInfo("b/tools:free", "B", tools=True),
                  orc.ModelInfo("c/coder:free", "C")]
        assert orc.pick_model(models, None) == "c/coder:free"
        assert orc.pick_model(models[:2], None) == "b/tools:free"
        assert orc.pick_model(models[:1], None) == "a/chat:free"
        assert orc.pick_model([], None) is None

    def test_unreadable_list(self):
        fake = Fake(models=httpx.Response(200, text="<html>"))
        with pytest.raises(AssistantError):
            fake.client().free_models()


# ── a streamed reply ────────────────────────────────────────────────

class TestStream:
    def test_pieces_arrive_in_order_and_join(self):
        pieces = []
        fake = Fake(completions=streamed(sse(
            chunk("Use "), chunk("`feedback`."), chunk(finish="stop"),
            {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 4}})))
        reply = fake.client().stream("m", [], on_text=pieces.append)
        assert pieces == ["Use ", "`feedback`."]
        assert reply.text == "Use `feedback`."
        assert reply.finish_reason == "stop"
        assert reply.usage["prompt_tokens"] == 120
        assert reply.model == "cohere/north-mini-code:free"

    def test_request_is_small_and_capped(self):
        fake = Fake(completions=streamed(sse(chunk("ok"))))
        fake.client().stream("cohere/north-mini-code:free",
                             [{"role": "user", "content": "q"}])
        body = json.loads(fake.requests[0].content)
        assert body["stream"] is True
        assert body["max_tokens"] == orc.MAX_REPLY_TOKENS
        assert body["model"] == "cohere/north-mini-code:free"

    def test_keepalive_comments_and_blank_lines_are_skipped(self):
        body = (b": OPENROUTER PROCESSING\n\n: OPENROUTER PROCESSING\n\n"
                + sse(chunk("x"), comments=False))
        reply = Fake(completions=streamed(body)).client().stream("m", [])
        assert reply.text == "x"

    def test_error_after_the_stream_began_is_a_failure(self):
        body = sse(chunk("par"), {"error": {"code": 502, "message": "upstream died"},
                                  "choices": [{"delta": {}, "finish_reason": "error"}]})
        with pytest.raises(AssistantError, match="upstream died"):
            Fake(completions=streamed(body)).client().stream("m", [])

    def test_finish_reason_error_is_a_failure(self):
        body = sse(chunk("par"), chunk(finish="error"))
        with pytest.raises(AssistantError):
            Fake(completions=streamed(body)).client().stream("m", [])

    def test_empty_reply_is_a_failure(self):
        with pytest.raises(AssistantError) as err:
            Fake(completions=streamed(sse(chunk(finish="stop")))).client().stream("m", [])
        assert err.value.kind == "model"

    def test_cancel_stops_at_the_next_piece(self):
        cancel = threading.Event()
        seen = []

        def on_text(piece):
            seen.append(piece)
            cancel.set()

        body = sse(chunk("one "), chunk("two "), chunk("three"))
        reply = Fake(completions=streamed(body)).client().stream(
            "m", [], on_text=on_text, cancel=cancel)
        assert reply.cancelled and reply.text == "one " and seen == ["one "]

    def test_rate_limit(self):
        response = httpx.Response(429, headers={"Retry-After": "17"}, json={
            "error": {"code": 429, "message": "Rate limit exceeded",
                      "metadata": {"error_type": "rate_limit_exceeded"}}})
        with pytest.raises(AssistantError) as err:
            Fake(completions=response).client().stream("m", [])
        assert err.value.kind == "rate_limit"
        assert err.value.retry_after == 17
        assert "50 a day" in str(err.value) and "17 s" in str(err.value)

    def test_data_policy_refusal_says_where_to_look(self):
        response = httpx.Response(404, json={"error": {
            "code": 404, "message": "No endpoints found matching your data policy"}})
        with pytest.raises(AssistantError) as err:
            Fake(completions=response).client().stream("m", [])
        assert err.value.kind == "data_policy"
        assert "settings/privacy" in str(err.value)

    def test_network_failure(self):
        def boom(request):
            raise httpx.ConnectError("no route", request=request)
        with pytest.raises(AssistantError) as err:
            Fake(completions=boom).client().stream("m", [])
        assert err.value.kind == "network"

    def test_allowance(self):
        fake = Fake(key=httpx.Response(200, json={"data": {
            "free_model_daily_requests": {"used": 12, "limit": 50, "remaining": 38}}}))
        allowance = fake.client().allowance()
        assert (allowance.used, allowance.limit, allowance.remaining) == (12, 50, 38)

    def test_allowance_missing_from_the_answer(self):
        fake = Fake(key=httpx.Response(200, json={"data": {"usage": 0}}))
        assert fake.client().allowance() is None


# ── the context ─────────────────────────────────────────────────────

SCRIPT = """\
G = tf(1, [1, 2, 1])
%% Controller
K = 3
L = K*G
%% Plot
step(feedback(L, 1))"""


class TestContext:
    def test_selection_wins(self):
        start = SCRIPT.index("K = 3")
        origin, region = ctx.code_at(SCRIPT, start, start, start + 5)
        assert origin == "selection" and region.text == "K = 3"

    def test_section_at_the_cursor_without_its_divider(self):
        origin, region = ctx.code_at(SCRIPT, SCRIPT.index("L = K"))
        assert origin == "section"
        assert region.text == "K = 3\nL = K*G"
        assert SCRIPT[region.start:region.end] == region.text

    def test_first_and_last_sections(self):
        _, first = ctx.code_at(SCRIPT, 0)
        assert first.text == "G = tf(1, [1, 2, 1])"
        _, last = ctx.code_at(SCRIPT, len(SCRIPT))
        assert last.text == "step(feedback(L, 1))"

    def test_python_dividers_count_too(self):
        text = "a = 1\n# %% two\nb = 2\nc = 3\n# %%\nd = 4"
        _, region = ctx.code_at(text, text.index("c"))
        assert region.text == "b = 2\nc = 3"

    def test_no_dividers_means_the_line_not_the_script(self):
        text = "a = 1\nb = 2\nc = 3"
        origin, region = ctx.code_at(text, text.index("b"))
        assert origin == "line" and region.text == "b = 2"

    def test_values_never_leave(self):
        import control as ctl
        secret = 271828.18
        variables = {
            "G": ctl.tf([secret], [1, 3, secret]),
            "S": ctl.ss([[-secret]], [[1]], [[1]], [[0]]),
            "data": np.full((3, 4), secret),
            "gain": secret,
            "note": f"calibrated at {secret}",
            "table": {"kp": secret},
            "seq": [secret, secret],
        }
        built = ctx.build("script", variables=variables)
        text = ctx.render(built)
        assert "271828" not in text and "2.718" not in text
        rows = {v.name: (v.type, v.size) for v in built.variables}
        assert rows["G"] == ("tf", "1×1, order 2")
        assert rows["S"] == ("ss", "1×1, 1 states")
        assert rows["data"] == ("array float64", "3×4")
        assert rows["gain"] == ("float", "scalar")
        assert rows["note"][1].endswith("chars")
        assert rows["table"] == ("dict", "1 keys")
        assert rows["seq"] == ("list", "2 items")

    def test_whole_script_is_never_sent(self):
        built = ctx.build("script", text=SCRIPT, cursor=SCRIPT.index("K = 3"))
        rendered = ctx.render(built)
        assert "K = 3" in rendered
        assert "G = tf" not in rendered and "step(" not in rendered

    def test_caps(self):
        huge = "x = 1\n" * 5000
        built = ctx.build("script", text=huge, cursor=0, sel_start=0,
                          sel_end=len(huge),
                          variables={f"v{i}": i for i in range(100)},
                          last_error="Traceback\n" + "frame\n" * 1000 + "NameError: y")
        assert len(built.code) == ctx.MAX_CODE_CHARS and built.truncated
        assert not built.editable
        assert len(built.variables) == ctx.MAX_VARIABLES
        assert built.variable_count == 100
        assert built.last_error.endswith("NameError: y")
        assert len(built.last_error) <= ctx.MAX_ERROR_CHARS + 1
        assert "… and 60 more" in ctx.render(built)
        assert "do not propose an edit" in ctx.render(built)

    def test_console_with_nothing_selected(self):
        built = ctx.build("console", variables={"G": 1}, last_error="oops")
        assert built.code == "" and built.region is None
        assert built.summary() == "1 variable name, last error"


# ── the reply ───────────────────────────────────────────────────────

class TestProtocol:
    def test_parse_text_edit_and_commands(self):
        reply = ("The gain is too high.\n\n```evans-edit\nK = 1.5\nL = K*G\n```\n"
                 "Then check it:\n```evans-run\nstep(feedback(L, 1))\n```\n"
                 "```python\nprint('just an example')\n```")
        parts = protocol.parse(reply)
        assert parts[0] == Text("The gain is too high.")
        assert parts[1] == Edit("K = 1.5\nL = K*G")
        assert parts[2] == Text("Then check it:")
        assert parts[3] == Command("step(feedback(L, 1))")
        assert isinstance(parts[4], Text) and "just an example" in parts[4].text

    def test_unclosed_block_stays_text(self):
        parts = protocol.parse("Here:\n```evans-edit\nK = 1")
        assert all(isinstance(p, Text) for p in parts)

    def test_empty_edit_means_delete_the_code(self):
        assert protocol.parse("```evans-edit\n```") == [Edit("")]

    def test_diff_and_apply(self):
        built = ctx.build("script", text=SCRIPT, cursor=SCRIPT.index("K = 3"))
        edit = Edit("K = 1.5\nL = K*G")
        lines = protocol.diff(built.region.text, edit.code)
        assert "-K = 3" in lines and "+K = 1.5" in lines
        out = protocol.apply_edit(SCRIPT, built, edit)
        assert out == SCRIPT.replace("K = 3", "K = 1.5")

    def test_apply_refuses_when_the_code_changed(self):
        built = ctx.build("script", text=SCRIPT, cursor=SCRIPT.index("K = 3"))
        with pytest.raises(StaleEdit):
            protocol.apply_edit(SCRIPT.replace("K = 3", "K = 4"), built, Edit("x"))

    def test_apply_refuses_without_a_region(self):
        with pytest.raises(StaleEdit):
            protocol.apply_edit("", ctx.build("console"), Edit("x"))

    def test_history_keeps_two_exchanges_with_code_shortened(self):
        history = History()
        long_answer = "Try:\n```evans-edit\n" + "\n".join(f"l{i}" for i in range(20)) + "\n```"
        for i in range(4):
            history.add(f"q{i}", long_answer)
        msgs = history.messages()
        assert [m["content"] for m in msgs if m["role"] == "user"] == ["q2", "q3"]
        answer = msgs[1]["content"]
        assert "l5" in answer and "l6" not in answer and "(14 more lines)" in answer

    def test_messages_carry_context_only_for_the_new_question(self):
        history = History()
        history.add("why does it oscillate?", "Low damping.")
        built = ctx.build("script", text=SCRIPT, cursor=SCRIPT.index("K = 3"),
                          variables={"G": 1})
        msgs = protocol.messages(built, "make it faster", history)
        assert msgs[0]["role"] == "system"
        assert msgs[1] == {"role": "user", "content": "why does it oscillate?"}
        assert msgs[2] == {"role": "assistant", "content": "Low damping."}
        assert msgs[3]["content"].endswith("make it faster")
        assert "K = 3" in msgs[3]["content"]
        assert len(msgs) == 4
