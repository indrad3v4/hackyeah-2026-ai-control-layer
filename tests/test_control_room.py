from typing import get_args
from control_room.models import ActionClass, AgentAnswer, ControlAnswer, Evidence

def test_canonical_action_classes():
    assert set(get_args(ActionClass)) == {"observe", "read_personal", "draft", "write_reversible", "irreversible", "authorize"}

def test_evidence_first_shapes():
    e = Evidence(source="/api/state", claim="decision", value="deny")
    a = AgentAnswer(agent="Kernel Agent", answer="blocked", evidence=[e])
    c = ControlAnswer(answer="blocked", evidence=a.evidence, specialists=["kernel_agent"], run_id="r1")
    assert c.evidence[0].value == "deny"
    assert c.specialists == ["kernel_agent"]
