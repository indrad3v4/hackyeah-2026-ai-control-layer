"""NEW-AC2 — the agent register carries the two gates (brief 2026-10-04).

The brief says this already passes on this HEAD; the test exists so it cannot regress, and fails if
ANY of ``id`` / ``principal`` / ``on_behalf_of`` / ``entitlements`` / ``scope`` is missing from ANY
agent. ``entitlements`` is the actor gate, ``scope`` is the agent gate — NEW-AC1 shows them apart on
the decision card, so they have to be present on the register first.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.app import create_app


# ================================================================== NEW-AC2 — registration: VERIFY
def test_new_ac2_api_agents_carries_the_five_keys_for_every_agent():
    """NEW-AC2 — GET /api/agents returns id · principal · on_behalf_of · entitlements · scope.

    This already passes on this HEAD (the brief says so); the test exists so it cannot regress, and
    fails if ANY of the five keys is missing from ANY agent.
    """
    with TestClient(create_app(seed=True)) as client:
        r = client.get("/api/agents")
    assert r.status_code == 200, "GET /api/agents answered %d" % r.status_code
    agents = r.json()
    assert isinstance(agents, list) and agents, "the agent register must not be empty"
    for agent in agents:
        missing = [k for k in ("id", "principal", "on_behalf_of", "entitlements", "scope")
                   if k not in agent]
        assert not missing, "agent %r is missing %s" % (agent.get("id"), missing)

