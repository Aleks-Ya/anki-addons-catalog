import json
from typing import Any

import anthropic
import httpx2
import pytest

from anki_addons_catalog.adapters.claude.llm import FALLBACK_BETA, ClaudeLlm
from anki_addons_catalog.domain.models import ToolSpec

pytestmark = pytest.mark.anyio

TOOLS = [ToolSpec("search_addons", "Search", {"type": "object", "properties": {"query": {"type": "string"}}}),
         ToolSpec("get_addon", "Get one", {"type": "object", "properties": {"addon_id": {"type": "integer"}}})]


def _sse(events: list[dict[str, Any]]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _message_events(blocks: list[dict[str, Any]], stop_reason: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [{"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 1, "cache_read_input_tokens": 900,
                  "cache_creation_input_tokens": 50}}}]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            events.append({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
            for word in block["text"].split(" "):
                events.append({"type": "content_block_delta", "index": i,
                               "delta": {"type": "text_delta", "text": word + " "}})
        else:
            events.append({"type": "content_block_start", "index": i, "content_block": {
                "type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}})
            events.append({"type": "content_block_delta", "index": i,
                           "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}})
        events.append({"type": "content_block_stop", "index": i})
    events.append({"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                   "usage": {"output_tokens": 40}})
    events.append({"type": "message_stop"})
    return events


def _llm(body: bytes, requests: list[httpx2.Request], fallbacks: bool = True) -> ClaudeLlm:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})
    client = anthropic.AsyncAnthropic(api_key="test", max_retries=0,
                                      http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    return ClaudeLlm(client, "claude-sonnet-5-5", "low", 4000, fallbacks)


def test_tool_params_are_sorted_with_one_cache_breakpoint() -> None:
    params = ClaudeLlm.tool_params(TOOLS)
    assert [p["name"] for p in params] == ["get_addon", "search_addons"]
    assert "cache_control" not in params[0]
    assert params[-1]["cache_control"] == {"type": "ephemeral"}


async def test_streams_text_and_parses_tool_calls() -> None:
    requests: list[httpx2.Request] = []
    body = _sse(_message_events([
        {"type": "text", "text": "Let me search."},
        {"type": "tool_use", "id": "tu_1", "name": "search_addons", "input": {"query": "kanji"}},
    ], "tool_use"))
    llm = _llm(body, requests)
    deltas: list[str] = []

    async def on_text(delta: str) -> None:
        deltas.append(delta)

    turn = await llm.turn("system prompt", TOOLS, [{"role": "user", "content": "kanji?"}], on_text)

    assert "".join(deltas).strip() == "Let me search."
    assert turn.stop_reason == "tool_use"
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [("tu_1", "search_addons", {"query": "kanji"})]
    assert turn.usage.cache_read_input_tokens == 900
    assert turn.usage.output_tokens == 40
    assert turn.model == "claude-sonnet-5-5"

    sent = json.loads(requests[0].content)
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["stream"] is True
    assert sent["output_config"] == {"effort": "low"}
    assert sent["fallbacks"] == "default"
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert FALLBACK_BETA in requests[0].headers["anthropic-beta"]


async def test_without_fallbacks_sends_no_beta() -> None:
    requests: list[httpx2.Request] = []
    llm = _llm(_sse(_message_events([{"type": "text", "text": "Done."}], "end_turn")), requests, fallbacks=False)

    async def on_text(delta: str) -> None:
        pass

    turn = await llm.turn("s", TOOLS, [{"role": "user", "content": "q"}], on_text)
    assert turn.stop_reason == "end_turn" and turn.text.strip() == "Done."
    assert "fallbacks" not in json.loads(requests[0].content)
    assert FALLBACK_BETA not in requests[0].headers.get("anthropic-beta", "")
