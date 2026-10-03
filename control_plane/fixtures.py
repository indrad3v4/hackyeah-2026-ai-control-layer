"""Demo fixtures - the only place fixture events exist, and they are opt-in.

The DEMO FEED must not be the production path (contract TASK.6). These rows are returned by
``/api/activity`` **only** when ``TENET_MODE=demo``; every one of them is labelled
``"source": "fixture"`` so a reader can never mistake a fixture for a kernel event. Default mode
is ``live``, where this module is never called.
"""
from __future__ import annotations

from typing import Any

# Deliberately obvious placeholders. They use the demo ids from the Control Room's own script
# and a fixed, non-live timestamp so nothing here can be read as a real kernel event.
FIXTURE_EVENTS: list[dict[str, Any]] = [
    {
        "kind": "fixture", "source": "fixture", "ts": 0.0, "demo": True,
        "label": "DEMO FEED - not a kernel event",
        "receipt": "dm000000", "decision": "allow", "agent": "fin-reconcile",
        "tool": "payments.read", "warrant": "W-4417", "run_id": None, "action_id": None,
        "note": "1,240 rows reconciled (fixture)",
    },
    {
        "kind": "fixture", "source": "fixture", "ts": 0.0, "demo": True,
        "label": "DEMO FEED - not a kernel event",
        "receipt": "dm000001", "decision": "redact", "agent": "support-copilot",
        "tool": "crm.read", "warrant": "W-4419", "run_id": None, "action_id": None,
        "note": "2 personal fields stripped before the call (fixture)",
    },
]


def fixture_events(limit: int = 50) -> list[dict[str, Any]]:
    return [dict(ev) for ev in FIXTURE_EVENTS[: max(0, limit)]]
