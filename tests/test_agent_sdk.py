"""Runs the agent through the REAL anthropic SDK, but with a fake network layer (no key, no cost).

This catches mistakes the scripted fake client can't: e.g. whether the SDK accepts our tool schemas
and can send its own response objects back to the API in the next request.
"""

import json

import pytest

anthropic = pytest.importorskip("anthropic")

# Newer SDK releases use the `httpx2` package; older ones use `httpx`. Use whichever is installed.
try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    httpx = pytest.importorskip("httpx")

from planner.agent import Agent
from planner.parser import parse_calendar_html
from planner.tools import Catalog
from tests.fixture import FIXTURE_HTML


def api_message(content, stop_reason):
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "test-model",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }


def test_loop_through_real_sdk():
    seen = []
    scripted = [
        api_message([{"type": "tool_use", "id": "toolu_1", "name": "update_completed_courses",
                      "input": {"courses": [{"code": "TEST 1P01", "grade": 80}]}}], "tool_use"),
        api_message([{"type": "tool_use", "id": "toolu_2", "name": "check_prereqs",
                      "input": {"code": "TEST 3P02"}}], "tool_use"),
        api_message([{"type": "text", "text": "You're eligible for TEST 3P02."}], "end_turn"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["x-api-key"] == "test-key"  # the key is attached automatically
        return httpx.Response(200, json=scripted[len(seen) - 1])

    client = anthropic.Anthropic(api_key="test-key",
                                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    agent = Agent(Catalog(parse_calendar_html(FIXTURE_HTML)), client=client, model="test-model")

    assert agent.chat("I finished TEST 1P01 with 80. Can I take TEST 3P02?") == "You're eligible for TEST 3P02."
    assert len(seen) == 3

    # Request 1 carried our system prompt, tools, and the student's message.
    assert seen[0]["model"] == "test-model"
    assert {t["name"] for t in seen[0]["tools"]} >= {"check_prereqs", "update_completed_courses"}
    assert seen[0]["messages"][0] == {"role": "user", "content": "I finished TEST 1P01 with 80. Can I take TEST 3P02?"}

    # Request 3 replays: user, assistant(tool_use), user(tool_result), assistant(tool_use), user(tool_result)
    msgs = seen[2]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert msgs[1]["content"][0]["type"] == "tool_use" and msgs[1]["content"][0]["id"] == "toolu_1"
    assert msgs[4]["content"][0]["tool_use_id"] == "toolu_2"
    assert json.loads(msgs[4]["content"][0]["content"])["status"] == "met"

    assert agent.tokens == {"input": 36, "output": 21}
