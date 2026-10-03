from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

ActionClass = Literal["observe", "read_personal", "draft", "write_reversible", "irreversible", "authorize"]
Decision = Literal["allow", "deny", "redact", "human", "revoked"]
WarrantState = Literal["active", "revoked", "expired"]

class Evidence(BaseModel):
    source: str
    claim: str
    value: str | bool | int | float | None = None
    action_id: str | None = None

class AgentAnswer(BaseModel):
    agent: str
    answer: str
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: str = "grounded"
    next_action: str | None = None

class Action(BaseModel):
    action_id: str
    agent: str
    actor: str | None = None
    tool: str
    parameters: dict = Field(default_factory=dict)
    action_class: ActionClass | None = None
    warrant: str | None = None
    warrant_state: WarrantState | None = None
    policy_result: str | None = None
    decision: Decision | None = None
    reason: str | None = None
    upstream_contacted: bool | None = None
    execution_result: str | None = None
    receipt: str | None = None

class ControlAnswer(BaseModel):
    """One answer from the assistance surface.

    ``next_action`` is the advisory hint the contract names in TASK.4's ``/api/ask`` shape.
    It is a suggestion for a person, never an authorization: the kernel's verdict is the only
    execution boundary. Adding it is additive - no existing consumer loses a field.
    """

    answer: str
    evidence: list[Evidence] = Field(default_factory=list)
    specialists: list[str] = Field(default_factory=list)
    run_id: str | None = None
    next_action: str | None = None
