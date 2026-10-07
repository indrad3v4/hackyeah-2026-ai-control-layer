"""Issue #38: a run's proof must resolve from the persistent store, not the last-200 window.

``proof_for_run`` used to scan ``k.actions(limit=200)``. The in-memory action ledger is bounded
(MAX_ACTIONS=200), so once a run was older than that window its proof came back empty - evidence
that exists in the ledger on disk, silently shown as none. The endpoint now resolves via
``k.actions_for_run`` against the ledger and reports ``evidence_source`` so "no proof exists"
("none") is distinguishable from "older than the window" ("store").
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app

WINDOW = 200


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A live instance whose store is a throwaway dir, so tests never share state."""
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app(seed=True)
    with TestClient(app) as c:
        c.app = app
        yield c


def _tokens(client) -> dict[str, str]:
    rows = client.get("/api/agents").json()
    return {r["id"]: r.get("token", "") for r in rows if r.get("token")}


def _mcp_with_run(client, agent, token, tool, args, run_id):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool, "arguments": args}},
        headers={"x-warrnt-agent": agent, "x-warrnt-token": token, "x-warrnt-run": run_id},
    )


def test_proof_of_a_run_older_than_the_window_is_not_silently_empty(client):
    tok = _tokens(client)["fin-reconcile"]
    n = WINDOW + 5  # comfortably past the in-memory window

    run_ids = []
    action_ids = {}
    for i in range(n):
        run_id = f"old-run-{i:04d}"
        run_ids.append(run_id)
        r = _mcp_with_run(client, "fin-reconcile", tok, "payments.read",
                          {"table": "payments", "limit": 2}, run_id)
        assert r.status_code == 200, r.text
        action_ids[run_id] = r.json()["result"]["action_id"]
        assert action_ids[run_id].startswith("A-")

    oldest = run_ids[0]
    kernel = client.app.state.kernel

    # Precondition: the oldest run really is outside the last-200 window - otherwise this test
    # would pass for the wrong reason.
    window_run_ids = {str(a.get("run_id") or "") for a in kernel.actions(limit=WINDOW)}
    assert oldest not in window_run_ids, "the oldest run is still inside the window"

    body = client.get(f"/api/proof/{oldest}").json()
    assert body["evidence_source"] == "store", body
    assert body["actions"], "the oldest run's proof was silently empty"
    assert body["actions"][0]["action_id"] == action_ids[oldest]


def test_unknown_run_is_distinguishable_from_a_run_beyond_the_window(client):
    """'no proof exists' must not look the same as 'not in the last 200'."""
    body = client.get("/api/proof/run-that-never-existed").json()
    assert body["evidence_source"] == "none"
    assert body["actions"] == []
    assert "action" in body["missing"]


def test_a_run_inside_the_window_still_resolves_as_window(client):
    tok = _tokens(client)["fin-reconcile"]
    r = _mcp_with_run(client, "fin-reconcile", tok, "payments.read",
                      {"table": "payments", "limit": 2}, "fresh-run-0001")
    assert r.status_code == 200, r.text
    action_id = r.json()["result"]["action_id"]
    body = client.get("/api/proof/fresh-run-0001").json()
    assert body["evidence_source"] == "window"
    assert body["actions"] and body["actions"][0]["action_id"] == action_id
