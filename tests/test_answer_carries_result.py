"""The answer must carry the consequence (found live on 2026-10-04).

An operator asked the control room for today's EUR/USD rate. The kernel allowed the read,
the read really went upstream (HTTP 200) and the record held the value - but the answer
came back as "the rate value itself wasn't returned to me", because the proposal tool
returned the verdict without the proven result. A user who asks for a number and is told
the gate said yes has been given a receipt for an empty hand.

These tests pin the two halves of the fix: the tool carries the recorded result, and the
run record names the action the answer is actually about (the newest one, not the state
that was read before the call).
"""

from __future__ import annotations

import json

from control_plane.app import _referenced_action
from control_room import agents


class _FakeEvidence:
    def __init__(self, action_id=None, value=None):
        self.action_id = action_id
        self.value = value


class _FakeResult:
    def __init__(self, evidence):
        self.evidence = evidence


class _Allow:
    """Stands in for warrnt.models.Decision - the tool only ever reads ``.value``."""

    value = "allow"


class _FakeAgents:
    def __init__(self, rows):
        self._rows = rows

    def __call__(self, dev=False):  # pragma: no cover - api mirror of Kernel.agents(dev=True)
        return self._rows


class _FakeKernel:
    """Just enough kernel: a warrant for fx-trader and one recorded execution."""

    def __init__(self, value=1.1225, http_status: int | None = 200, executed=True):
        self._value = value
        self._http = http_status
        self._executed = executed
        self.agents = _FakeAgents([{"id": "fx-trader", "token": "tok-live"}])

    def intercept(self, agent_id, token, tool, params, run_id=""):
        return _Allow(), "read-only · live reference rate · in scope · class observe", \
            {"action_id": "A-0009", "resource": "principal Treasury"}, {"id": "e29e1dc6"}, \
            self._executed

    def action(self, action_id):
        return {"action_id": action_id, "receipt": "e29e1dc6",
                "execution_result": {"rows": 1, "outcome": "ok", "http_status": self._http,
                                     "value": self._value, "latency_ms": 48.2,
                                     "endpoint": "https://api.frankfurter.dev/v1/latest",
                                     "response_sha256": "f6" * 32}}


def _with_kernel(kernel):
    previous = agents._KERNEL
    agents.bind_kernel(kernel)
    return previous


def test_proposal_tool_carries_the_recorded_result():
    previous = _with_kernel(_FakeKernel())
    try:
        payload = json.loads(agents._propose_action("fx.read_rate", "EUR", "USD"))
    finally:
        agents.bind_kernel(previous)
    assert payload["decision"] == "allow"
    assert payload["upstream_contacted"] is True
    assert payload["result"]["value"] == 1.1225
    assert payload["result"]["http_status"] == 200
    assert payload["result"]["response_sha256"] == "f6" * 32


def test_a_call_that_never_reached_the_far_side_carries_no_result():
    previous = _with_kernel(_FakeKernel(http_status=None))
    try:
        payload = json.loads(agents._propose_action("fx.read_rate", "EUR", "USD"))
    finally:
        agents.bind_kernel(previous)
    assert payload["upstream_contacted"] is False
    assert payload["result"] == {}


def test_a_denied_proposal_carries_no_result():
    previous = _with_kernel(_FakeKernel())
    try:
        # The fake kernel's token lookup is the only gate here; drop the warrant and the tool
        # reports the refusal with no result block at all.
        agents._KERNEL.agents = _FakeAgents([])
        payload = json.loads(agents._propose_action("fx.read_rate", "EUR", "USD"))
    finally:
        agents.bind_kernel(previous)
    assert payload["submitted"] is False
    assert "result" not in payload


def test_run_record_names_the_newest_action_not_the_state_read_before_it():
    result = _FakeResult([
        _FakeEvidence(value=json.dumps({"action_id": "A-0001", "decision": "allow"})),
        _FakeEvidence(value=json.dumps({"actions": [{"action_id": "A-0001"},
                                                    {"action_id": "A-0007"}]})),
    ])
    assert _referenced_action(result) == "A-0007"


def test_run_record_is_none_when_the_answer_cited_nothing():
    assert _referenced_action(_FakeResult([_FakeEvidence(value="no action in the record")])) is None
