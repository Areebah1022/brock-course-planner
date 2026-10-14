"""Tests for the agent loop using a scripted fake client (no API key, no network, no cost)."""

import json
from types import SimpleNamespace as NS

import pytest

from planner.agent import MAX_TOOL_ROUNDS, TOOLS, Agent, execute_tool
from planner.parser import parse_calendar_html
from planner.tools import Catalog
from tests.fixture import FIXTURE_HTML


@pytest.fixture
def catalog():
    return Catalog(parse_calendar_html(FIXTURE_HTML))


# ---- helpers to script what "Claude" says ---------------------------------------------

def text(msg):
    return NS(type="text", text=msg)


def tool_call(call_id, name, **args):
    return NS(type="tool_use", id=call_id, name=name, input=args)


def reply(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5))


class FakeClient:
    """Returns scripted responses in order and records every request it receives."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = self  # so client.messages.create(...) works

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot
        return self._responses.pop(0)


# ---- tool schemas ----------------------------------------------------------------------

def test_every_tool_has_a_valid_schema():
    for tool in TOOLS:
        assert tool["name"] and tool["description"]
        assert tool["input_schema"]["type"] == "object"


# ---- execute_tool ----------------------------------------------------------------------

def test_update_then_check(catalog):
    done = {}
    out = execute_tool("update_completed_courses",
                       {"courses": [{"code": "test1p01", "grade": 75}, {"code": "MATH 1P66"}]},
                       catalog, done)
    assert out["completed_courses"] == {"TEST 1P01": 75.0, "MATH 1P66": None}
    assert execute_tool("check_prereqs", {"code": "TEST 3P02"}, catalog, done)["status"] == "met"


def test_bad_grade_rejected(catalog):
    with pytest.raises(ValueError):
        execute_tool("update_completed_courses", {"courses": [{"code": "TEST 1P01", "grade": 150}]}, catalog, {})


def test_get_course_unknown_and_known(catalog):
    assert "error" in execute_tool("get_course", {"code": "NOPE 1P01"}, catalog, {})
    c = execute_tool("get_course", {"code": "TEST 2P01"}, catalog, {})
    assert c["title"] == "Advanced Widgets" and "TEST 1P01" in c["prerequisites"]


def test_available_courses_compact(catalog):
    out = execute_tool("available_courses", {}, catalog, {"TEST 1P01": 70.0})
    assert out["count"] == len(out["courses"]) > 0


def test_unknown_tool_raises(catalog):
    with pytest.raises(ValueError):
        execute_tool("delete_everything", {}, catalog, {})


# ---- the loop --------------------------------------------------------------------------

def test_plain_answer_needs_no_tools(catalog):
    client = FakeClient(reply(text("Hi! Tell me what you've completed.")))
    agent = Agent(catalog, client=client)
    assert agent.chat("hello") == "Hi! Tell me what you've completed."
    assert client.requests[0]["tools"] == TOOLS
    assert "2099-2100" in client.requests[0]["system"]


def test_full_tool_round_trip(catalog):
    client = FakeClient(
        reply(tool_call("t1", "update_completed_courses", courses=[{"code": "TEST 1P01", "grade": 80}]),
              stop="tool_use"),
        reply(tool_call("t2", "check_prereqs", code="TEST 3P02"), stop="tool_use"),
        reply(text("Yes, you can take TEST 3P02.")),
    )
    agent = Agent(catalog, client=client)
    assert agent.chat("I finished TEST 1P01 with 80. Can I take TEST 3P02?") == "Yes, you can take TEST 3P02."

    # Exactly three trips to the API.
    assert len(client.requests) == 3
    # State is held in Python, not in Claude's memory.
    assert agent.completed == {"TEST 1P01": 80.0}

    # The 2nd request must contain the tool_result for t1, in a user message, with matching id.
    second = client.requests[1]["messages"]
    result_msg = second[-1]
    assert result_msg["role"] == "user"
    assert [b["tool_use_id"] for b in result_msg["content"]] == ["t1"]
    assert all(b["type"] == "tool_result" for b in result_msg["content"])  # no stray text blocks

    # The 3rd request carries the check_prereqs result (valid JSON saying status: met).
    third_result = client.requests[2]["messages"][-1]["content"][0]
    assert third_result["tool_use_id"] == "t2"
    assert json.loads(third_result["content"])["status"] == "met"


def test_parallel_tool_calls_all_answered(catalog):
    client = FakeClient(
        reply(tool_call("a", "get_course", code="TEST 1P01"),
              tool_call("b", "get_course", code="TEST 2P01"), stop="tool_use"),
        reply(text("Done.")),
    )
    Agent(catalog, client=client).chat("compare them")
    ids = [b["tool_use_id"] for b in client.requests[1]["messages"][-1]["content"]]
    assert ids == ["a", "b"]  # every tool_use gets a tool_result


def test_tool_error_is_reported_to_claude_not_raised(catalog):
    client = FakeClient(
        reply(tool_call("x", "nonexistent_tool"), stop="tool_use"),
        reply(text("Sorry, something went wrong.")),
    )
    agent = Agent(catalog, client=client)
    assert agent.chat("do something") == "Sorry, something went wrong."
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "Unknown tool" in result["content"]


def test_runaway_loop_is_stopped(catalog):
    looping = [reply(tool_call(f"t{i}", "get_course", code="TEST 1P01"), stop="tool_use")
               for i in range(MAX_TOOL_ROUNDS + 5)]
    client = FakeClient(*looping)
    out = Agent(catalog, client=client).chat("loop forever")
    assert "stuck" in out
    assert len(client.requests) == MAX_TOOL_ROUNDS


def test_conversation_history_carries_over(catalog):
    client = FakeClient(reply(text("one")), reply(text("two")))
    agent = Agent(catalog, client=client)
    agent.chat("first")
    agent.chat("second")
    roles = [m["role"] for m in client.requests[1]["messages"]]
    assert roles == ["user", "assistant", "user"]


def test_failed_turn_is_rolled_back(catalog):
    class Boom(FakeClient):
        def create(self, **kwargs):
            raise RuntimeError("network down")

    agent = Agent(catalog, client=Boom())
    with pytest.raises(RuntimeError):
        agent.chat("hello")
    assert agent.messages == []  # no dangling half-turn that would break the next request


def test_token_usage_is_tracked(catalog):
    agent = Agent(catalog, client=FakeClient(reply(text("ok"))))
    agent.chat("hi")
    assert agent.tokens == {"input": 10, "output": 5}


def test_truncated_answer_is_flagged(catalog):
    agent = Agent(catalog, client=FakeClient(reply(text("partial"), stop="max_tokens")))
    assert "cut off" in agent.chat("long question")
