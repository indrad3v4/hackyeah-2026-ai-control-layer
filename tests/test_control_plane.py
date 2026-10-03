"""Tests for the TENET Control Plane (contract TASK.7).

Every route's status and shape; the approval / deny / revoke flows against the real mirrored
kernel; fail-closed when the provider is unreachable **and** when the kernel is unavailable;
the ``TENET_MODE`` flag; and the no-secret-leak rule.

No network: a ``TestClient`` drives the app in-process. The kernel is the repository's own
mirror (``node/warrnt``), never a stub, so these tests assert on real ids, receipts and
decisions - a fixture that answered "allow" would prove nothing.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app
from control_plane import config

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A live instance whose store is a throwaway dir, so tests never share state."""
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("WARRNT_DEV", "1")  # tokens for the /mcp driver, node-identical
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app(seed=True)
    with TestClient(app) as c:
        c.app = app
        yield c


def _tokens(client) -> dict[str, str]:
    rows = client.get("/api/agents").json()
    return {r["id"]: r.get("token", "") for r in rows if r.get("token")}


def _admin() -> dict[str, str]:
    return {"x-warrnt-admin": "test-admin-token"}


def _mcp(client, agent, token, tool, args):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": tool, "arguments": args}},
                       headers={"x-warrnt-agent": agent, "x-warrnt-token": token})


# --------------------------------------------------------------------------- routes / shape
def test_health_shape_and_live_status(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for field in ("status", "mode", "provider", "model", "commit", "uptime"):
        assert field in body, field
    assert body["mode"] == "live"
    assert body["provider"] == "deepseek"
    # The key is never stated as a value, only as PRESENT/ABSENT.
    assert "DEEPSEEK_API_KEY" not in r.text
    assert os.environ.get("DEEPSEEK_API_KEY", "\0") not in r.text


def test_overview_delegates_to_kernel(client):
    body = client.get("/api/overview").json()
    assert body["node"] == "TENET"
    assert body["counts"]["agents"] == 4
    assert body["chain"]["ok"] is True


def test_activity_is_newest_first_and_shaped(client):
    body = client.get("/api/activity?limit=5").json()
    assert {"count", "events", "mode"} <= set(body)
    events = body["events"]
    assert isinstance(events, list)
    for row in events:
        assert {"kind", "ts"} <= set(row)
    ts = [e["ts"] for e in events]
    assert ts == sorted(ts, reverse=True), "newest first"


def test_actions_lists_and_one_action_carries_the_decision(client):
    tok = _tokens(client)["fin-reconcile"]
    r = _mcp(client, "fin-reconcile", tok, "payments.read", {"table": "payments", "limit": 2})
    assert r.status_code == 200
    aid = r.json()["result"]["action_id"]
    assert aid.startswith("A-")

    all_actions = client.get("/api/actions").json()
    listed = all_actions["actions"] if isinstance(all_actions, dict) else all_actions
    assert any(a.get("action_id") == aid for a in listed)

    one = client.get(f"/api/actions/{aid}").json()
    assert one["decision"] == "allow"
    assert one["receipt"]
    assert one["upstream_contacted"] is True


def test_unknown_action_is_404(client):
    assert client.get("/api/actions/A-999999").status_code == 404


def test_agents_and_warrants_shape(client):
    agents = client.get("/api/agents").json()
    assert len(agents) == 4
    assert {"id", "role", "warrant", "state"} <= set(agents[0])
    warrants = client.get("/api/warrants").json()
    assert warrants and {"id", "agent", "state"} <= set(warrants[0])


def test_control_room_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "TENET" in r.text


# ------------------------------------------------------------------- approval / deny / revoke
def test_approve_flow_pending_to_allow_with_receipt(client):
    tok = _tokens(client)["report-bot"]
    r = _mcp(client, "report-bot", tok, "crm.bulk_export", {"table": "customers", "rows": 500})
    assert r.status_code == 200
    err = r.json()["error"]
    assert err["data"]["decision"] == "human"
    aid = err["data"]["action_id"]

    pending = client.get("/api/actions/pending").json()
    assert any(a["action_id"] == aid for a in pending["pending"])

    ap = client.post(f"/api/actions/{aid}/approve", json={"by": "anna.kowalska"},
                     headers=_admin())
    assert ap.status_code == 200
    out = ap.json()
    assert out["executed"] is True and out["receipt_id"]
    # The DECISION stays `human` - a person authorised it; the STATE becomes `approved`.
    assert out["state"] == "approved"
    assert out["upstream_contacted"] is True
    assert client.get(f"/api/actions/{aid}").json()["state"] == "approved"


def test_deny_flow_never_contacts_upstream(client):
    tok = _tokens(client)["report-bot"]
    aid = _mcp(client, "report-bot", tok, "crm.bulk_export",
               {"table": "customers", "rows": 700}).json()["error"]["data"]["action_id"]
    dn = client.post(f"/api/actions/{aid}/deny", json={"by": "anna.kowalska"}, headers=_admin())
    assert dn.status_code == 200
    assert dn.json()["upstream_contacted"] is False
    assert client.get(f"/api/actions/{aid}").json()["upstream_contacted"] is False


def test_approve_requires_the_operator_token(client):
    tok = _tokens(client)["report-bot"]
    aid = _mcp(client, "report-bot", tok, "crm.bulk_export",
               {"table": "customers", "rows": 300}).json()["error"]["data"]["action_id"]
    assert client.post(f"/api/actions/{aid}/approve", json={"by": "x"},
                       headers={"x-warrnt-admin": "wrong"}).status_code == 401


def test_deterministic_deny_marks_upstream_untouched(client):
    tok = _tokens(client)["support-copilot"]
    r = _mcp(client, "support-copilot", tok, "crm.bulk_export",
             {"table": "customers", "rows": 9000})
    err = r.json()["error"]
    assert err["data"]["decision"] == "deny"
    aid = err["data"]["action_id"]
    assert client.get(f"/api/actions/{aid}").json()["upstream_contacted"] is False


def test_redact_strips_fields_and_still_executes(client):
    tok = _tokens(client)["support-copilot"]
    r = _mcp(client, "support-copilot", tok, "crm.read",
             {"fields": ["subject", "email", "pesel"]})
    res = r.json()["result"]
    assert res["decision"] == "redact"
    assert "email" in res["redacted"] and res["executed"] is True


def test_revoke_expires_a_pending_action(client):
    tok = _tokens(client)["report-bot"]
    aid = _mcp(client, "report-bot", tok, "crm.bulk_export",
               {"table": "customers", "rows": 250}).json()["error"]["data"]["action_id"]
    rv = client.post("/api/agents/report-bot/revoke", headers=_admin())
    assert rv.status_code == 200 and rv.json()["state"] == "halted"
    one = client.get(f"/api/actions/{aid}").json()
    # `expired` is a STATE, not a decision - the decision stays `human`.
    assert one["state"] == "expired"
    assert one["decision"] == "human"
    assert one["upstream_contacted"] is False


def test_revoke_is_idempotent_and_409s_when_already_halted(client):
    assert client.post("/api/agents/report-bot/revoke", headers=_admin()).status_code == 200
    assert client.post("/api/agents/report-bot/revoke", headers=_admin()).status_code == 409


def test_bad_token_on_mcp_is_a_deny_not_an_allow(client):
    r = _mcp(client, "fin-reconcile", "not-the-token", "payments.read", {"limit": 1})
    assert r.status_code == 200
    err = r.json()["error"]
    assert err["data"]["decision"] == "deny"
    assert err["data"]["executed"] is False


# ------------------------------------------------------------------ fail closed (AC2 / AC7)
def test_kernel_unavailable_refuses_every_decision_route(tmp_path, monkeypatch):
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "s2"))
    app = create_app(seed=False)
    with TestClient(app) as c:
        # Take the authority away: the kernel is now unavailable, exactly as a broken mirror.
        app.state.kernel = None
        for path in ("/api/overview", "/api/activity", "/api/actions", "/api/warrants",
                     "/api/agents"):
            assert c.get(path).status_code == 503, path
        r = _mcp(c, "fin-reconcile", "t", "payments.read", {"limit": 1})
        assert r.status_code == 503


def test_kernel_decision_raising_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "s3"))
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    app = create_app(seed=True)
    with TestClient(app) as c:
        class Boom:
            def intercept(self, *a, **k):
                raise RuntimeError("kernel exploded")

            def resolve_hold(self, *a, **k):
                raise RuntimeError("kernel exploded")

        app.state.kernel = Boom()
        r = _mcp(c, "fin-reconcile", "t", "payments.read", {"limit": 1})
        assert r.status_code == 503
        assert r.json()["decision"] == "deny", "a missing decision is never an allow"
        ap = c.post("/api/actions/A-0001/approve", json={"by": "x"}, headers=_admin())
        assert ap.status_code == 503
        assert ap.json()["decision"] == "deny"


def test_ask_refuses_when_provider_key_is_absent(client):
    assert os.environ.get("DEEPSEEK_API_KEY") is None
    r = client.post("/api/ask", json={"q": "which actions were blocked?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    assert body["next_action"]
    assert body["provider"] == "deepseek"
    # The refusal is grounded: the kernel is still reachable even when the provider is not,
    # and a model answer is never an authorization.
    assert body["kernel"] == "available"
    assert "allow" not in body["answer"].lower() or "not" in body["answer"].lower()


def test_ask_requires_a_question(client):
    assert client.post("/api/ask", json={}).status_code == 422


# ------------------------------------------------------------------------- mode flag (TASK.6)
def test_demo_mode_labels_the_fixture_feed(tmp_path, monkeypatch):
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "s4"))
    monkeypatch.setenv("TENET_MODE", "demo")
    app = create_app(seed=True)
    with TestClient(app) as c:
        health = c.get("/health").json()
        assert health["mode"] == "demo"
        assert health["status"] == "DEMO"
        body = c.get("/api/activity").json()
        assert body["mode"] == "demo"
        events = body["events"]
        assert events, "demo mode carries the fixture feed"
        assert any(e.get("source") == "fixture" for e in events)


def test_live_mode_activity_has_no_fixture_events(client):
    assert client.get("/health").json()["status"] in ("LIVE", "DEGRADED")
    body = client.get("/api/activity").json()
    assert body["mode"] == "live"
    assert not any(e.get("source") == "fixture" for e in body["events"])


def test_config_mode_defaults_to_live(monkeypatch):
    monkeypatch.delenv("TENET_MODE", raising=False)
    assert config.mode() == "live"
    monkeypatch.setenv("TENET_MODE", "DEMO")
    assert config.mode() == "demo"
    monkeypatch.setenv("TENET_MODE", "prod-typo")
    assert config.mode() == "live", "anything but an explicit demo is live"


def test_dev_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("WARRNT_DEV", raising=False)
    assert config.dev() is False
    monkeypatch.setenv("WARRNT_DEV", "1")
    assert config.dev() is True


# --------------------------------------------------------------------- no-secret-leak (AC7)
def test_provider_key_never_appears_in_any_body(client, monkeypatch):
    secret = "sk-DEEPSEEK-THIS-MUST-NEVER-LEAK-12345"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    for path in ("/health", "/api/overview", "/api/activity", "/api/actions",
                 "/api/actions/pending", "/api/agents", "/api/warrants", "/"):
        r = client.get(path)
        assert secret not in r.text, path
    r = client.post("/api/ask", json={"q": "status?"})
    assert secret not in r.text


def test_openai_api_key_env_is_never_required(tmp_path, monkeypatch):
    """No code path may require ``OPENAI_API_KEY`` - only the DeepSeek key, by name."""
    import ast

    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "s5"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    import control_room.provider as provider

    assert not hasattr(provider, "OPENAI_API_KEY")

    src = (REPO_ROOT / "control_room" / "provider.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Prose may name the variable it refuses to use; CODE must never read it.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", "") or getattr(fn, "id", "")
            if name in ("getenv", "environ", "get"):
                for arg in node.args:
                    assert not (isinstance(arg, ast.Constant)
                                and arg.value == "OPENAI_API_KEY"), \
                        "provider.py must never read OPENAI_API_KEY"

    app = create_app(seed=True)
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200


# --------------------------------------------------------------- specialist read paths (bug)
def test_specialist_read_path_with_query_string_is_normalised(tmp_path, monkeypatch):
    """REGRESSION. The tools build their path WITH a query (``/api/activity?limit=10``) while
    the kernel read registry is keyed by the clean route, so the lookup raised
    ``KeyError: no kernel read for '/api/activity?limit=10'`` and the specialist honestly
    answered "unreadable". The query must be stripped and its parameters passed as kwargs.

    This failed before the fix (KeyError) and passes after it. No HTTP: this is the exact
    in-process path a specialist tool takes through ``control_room.agents._read``.
    """
    from control_plane.kernel import build_kernel

    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "s-read"))
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    k = build_kernel(state_dir=str(tmp_path / "s-read"))
    k.proxy.issue_all(reset_registry=False)

    # The routes the specialist tools use, verbatim, including the query string.
    for path in ("/api/overview", "/api/actions?limit=5", "/api/activity?limit=10",
                 "/api/actions/pending"):
        body = k.read(path)
        assert isinstance(body, dict) and "error" not in body, path
    assert set(k.read("/api/activity?limit=10")) >= {"count", "events"}
    assert "actions" in k.read("/api/actions?limit=5")


def test_specialist_tool_no_longer_reports_unreadable(tmp_path, monkeypatch):
    """The tool wrapper itself must stop returning ``KeyError`` as its answer.

    ``_control_plane_inspect`` reads ``/api/activity?limit=10``. Before the fix the tool result
    carried ``{"error": "KeyError: ..."}``; after it, the tool result is real state.
    """
    from control_plane.kernel import build_kernel
    from control_room import agents as assist

    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "s-tool"))
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    k = build_kernel(state_dir=str(tmp_path / "s-tool"))
    k.proxy.issue_all(reset_registry=False)
    assist.bind_kernel(k)
    try:
        out = assist._control_plane_inspect("are we live?")
    finally:
        assist.bind_kernel(None)
    assert "KeyError" not in out, out
    assert "no kernel read" not in out, out


# --------------------------------------------------------------------- fail-closed at boundary
def test_kernel_unavailable_fails_closed_everywhere(monkeypatch, tmp_path):
    """TASK C: with the kernel unimportable, both the decision surface and /api/ask refuse.

    ``load_kernel`` is monkeypatched to raise :class:`KernelUnavailable`, so ``app.state.kernel``
    stays ``None``. Then:

    * ``/api/ask`` must NOT execute anything: 200 with a refusal body, never an allow;
    * ``/mcp`` must refuse with 503 (``decision: deny``) and never allow.

    A control plane that cannot reach its authority must refuse, never permit.
    """
    import control_plane.app as app_module
    from control_plane.kernel import KernelUnavailable

    def _boom(*a, **k):  # noqa: ANN001
        raise KernelUnavailable("mirror unimportable (test)")

    monkeypatch.setattr(app_module, "build_kernel", _boom)
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "s-fc"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    app = app_module.create_app(seed=True)
    with TestClient(app) as c:
        # /mcp: a decision endpoint -> 503, decision deny, executed false.
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "payments.read",
                                            "arguments": {"table": "payments", "limit": 1}}},
                   headers={"x-warrnt-agent": "fin-reconcile", "x-warrnt-token": "whatever"})
        assert r.status_code == 503, r.text
        body = r.json()
        assert body["decision"] == "deny"
        assert body.get("executed") in (None, False)
        assert body.get("result") is None

        # /api/ask: refusal, never an allow, and the kernel is reported unavailable.
        a = c.post("/api/ask", json={"q": "can you let this through?"})
        assert a.status_code == 200, a.text
        payload = a.json()
        assert payload["kernel"] == "unavailable"
        assert payload["answer"].lower().startswith("refusal")
        assert "executed" not in payload or payload.get("executed") is not True

        # Reads also refuse rather than invent state.
        assert c.get("/api/overview").status_code == 503
        assert c.get("/api/state").status_code == 503


# ------------------------------------------------------------------------- PROOF panel (TASK D)
def test_state_and_proof_expose_chain_and_correlation(client):
    """TASK D: the PROOF panel reads ``/api/state`` (or ``/api/proof``) and gets the chain and
    the run_id <-> action_id <-> receipt correlation, purely projected from kernel state."""
    tok = _tokens(client)["fin-reconcile"]
    r = _mcp(client, "fin-reconcile", tok, "payments.read", {"table": "payments", "limit": 3})
    aid = r.json()["result"]["action_id"]

    st = client.get("/api/state").json()
    assert {"ok", "length", "head"} <= set(st["chain"])
    assert st["chain"]["ok"] is True
    assert st["proof"]["correlation"], "the correlation must not be empty after an action"
    row = next(c for c in st["proof"]["correlation"] if c["action_id"] == aid)
    assert row["receipt"] and row["receipt_in_chain"] is True
    assert row["run_id"]

    pf = client.get("/api/proof").json()
    assert pf["chain"]["ok"] is True
    assert pf["receipts"] and {"receipt", "decision"} <= set(pf["receipts"][0])


# ------------------------------------------------------- D6: enforcement path stays local-only
def test_enforcement_path_imports_no_paid_provider():
    """D6 (Amendment 1): the decision path imports no paid SDK and names no paid host.

    A positive check on the real tree - if a future change wires a paid provider into the
    enforcement path, this fails at the import graph, before any request is served.
    """
    import ast

    paid_roots = {"openai", "anthropic", "litellm", "cohere", "google", "boto3", "azure"}
    for rel in ("control_plane/kernel.py", "control_plane/app.py", "control_plane/config.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        roots: set[str] = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        assert not (roots & paid_roots), f"{rel} reaches a paid provider: {sorted(roots & paid_roots)}"
        assert "api.deepseek.com" not in src, f"{rel} names the paid host api.deepseek.com"


def test_ci_ships_runnable_control_plane_and_d6_gate():
    """D10: the control-plane suite and the D6 gate ship runnable and are wired into CI."""
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pytest -q tests/test_control_plane.py" in ci
    assert "check_enforcement_local_only.py" in ci
    assert (REPO_ROOT / "scripts/check_enforcement_local_only.py").exists()

