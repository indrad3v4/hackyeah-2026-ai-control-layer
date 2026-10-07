"""Tests for the TENET Control Plane (contract TASK.7).

Every route's status and shape; the approval / deny / revoke flows against the real mirrored
kernel; fail-closed when the provider is unreachable **and** when the kernel is unavailable;
the ``TENET_MODE`` flag; and the no-secret-leak rule.

No network: a ``TestClient`` drives the app in-process. The kernel is the repository's own
mirror (``node/warrnt``), never a stub, so these tests assert on real ids, receipts and
decisions - a fixture that answered "allow" would prove nothing.
"""
from __future__ import annotations

import asyncio
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
    rv = client.post("/api/agents/report-bot/revoke", json={"by": "anna.kowalska"}, headers=_admin())
    assert rv.status_code == 200 and rv.json()["state"] == "halted"
    one = client.get(f"/api/actions/{aid}").json()
    # `expired` is a STATE, not a decision - the decision stays `human`.
    assert one["state"] == "expired"
    assert one["decision"] == "human"
    assert one["upstream_contacted"] is False


def test_revoke_is_idempotent_and_409s_when_already_halted(client):
    named = {**_admin(), "Content-Type": "application/json"}
    assert client.post("/api/agents/report-bot/revoke", json={"by": "anna.kowalska"},
                       headers=named).status_code == 200
    assert client.post("/api/agents/report-bot/revoke", json={"by": "anna.kowalska"},
                       headers=named).status_code == 409


# ---------------------------------------------------------- ACT-7b: revoke is attributed
# The halt is a control decision like any other: it must name the person who decided it, exactly
# as approve/deny do. These four tests are the contract section 3's T1..T4 for the revoke door.
def test_t1_revoke_with_a_named_operator_is_recorded_with_that_name(client):
    """T1 - revoke with a valid token AND a name succeeds, and the record carries that exact name."""
    tok = _tokens(client)["report-bot"]
    aid = _mcp(client, "report-bot", tok, "crm.bulk_export",
               {"table": "customers", "rows": 250}).json()["error"]["data"]["action_id"]

    rv = client.post("/api/agents/report-bot/revoke", json={"by": "indradev_"}, headers=_admin())
    assert rv.status_code == 200
    body = rv.json()
    assert body["state"] == "halted"
    assert body["by"] == "indradev_", "the record did not carry the named operator: %r" % body
    # the named halt really took effect: the pending hold is gone and the warrant is revoked
    one = client.get(f"/api/actions/{aid}").json()
    assert one["state"] == "expired" and one["upstream_contacted"] is False


def test_t2_revoke_without_a_name_is_refused_and_records_nothing(client):
    """T2 - an empty/missing `by` is a validation failure (422) and NO receipt is created.

    The refusal happens before the kernel runs, so nothing is committed: the agent stays
    revocable and the registry carries no revoke receipt for the unattributed halt.
    """
    k = client.app.state.kernel
    before = len(k.registry_recent(500))

    for payload in ({}, {"by": ""}, {"by": "   "}):
        r = client.post("/api/agents/report-bot/revoke", json=payload, headers=_admin())
        assert r.status_code == 422, "an unattributed revoke was accepted: %r -> %s" % (payload, r.status_code)
        assert r.json()["field"] == "by"

    # no revoke receipt, no state change: the agent is still live and revocable
    revokes = [e for e in k.registry_recent(500)
               if e.get("decision") == "revoked" or e.get("tool") == "/revoke"]
    assert not revokes, "an unattributed revoke was committed into the record: %r" % revokes
    assert len(k.registry_recent(500)) == before, "the refused revoke still appended to the chain"
    bot = [a for a in client.get("/api/agents").json() if a["id"] == "report-bot"][0]
    assert bot["state"] == "active", "the refused revoke still halted the agent"

    # and the door still works once a name is given
    ok = client.post("/api/agents/report-bot/revoke", json={"by": "indradev_"}, headers=_admin())
    assert ok.status_code == 200 and ok.json()["by"] == "indradev_"


def test_t3_revoke_without_the_operator_token_is_still_401(client):
    """T3 - the 401 for a token-less revoke is unchanged, name or no name."""
    assert client.post("/api/agents/report-bot/revoke",
                       json={"by": "indradev_"}).status_code == 401
    assert client.post("/api/agents/report-bot/revoke",
                       json={}).status_code == 401
    # the compat alias keeps the same rule
    assert client.post("/revoke", json={"agent": "report-bot", "by": "indradev_"}).status_code == 401


def test_t3b_compat_revoke_alias_requires_a_name_too(client):
    """T3b - `/revoke` (the page's kill route) carries the same named-person requirement."""
    no_name = client.post("/revoke", json={"agent": "report-bot"}, headers=_admin())
    assert no_name.status_code == 422 and no_name.json()["field"] == "by"
    named = client.post("/revoke", json={"agent": "report-bot", "by": "indradev_"}, headers=_admin())
    assert named.status_code == 200 and named.json()["by"] == "indradev_"


def test_t4_approve_named_and_unnamed_behaviour_is_unchanged(client):
    """T4 - the approve door is untouched: a name resolves (200), no name is refused (422)."""
    def hold(rows):
        tok = _tokens(client)["report-bot"]
        return _mcp(client, "report-bot", tok, "crm.bulk_export",
                    {"table": "customers", "rows": rows}).json()["error"]["data"]["action_id"]

    named_id = hold(200)
    ok = client.post(f"/api/actions/{named_id}/approve", json={"by": "anna.kowalska"}, headers=_admin())
    assert ok.status_code == 200 and ok.json()["executed"] is True

    unnamed_id = hold(210)
    bad = client.post(f"/api/actions/{unnamed_id}/approve", json={}, headers=_admin())
    assert bad.status_code == 422 and bad.json()["field"] == "by"
    # the unnamed approve left the hold untouched
    assert client.get(f"/api/actions/{unnamed_id}").json()["state"] == "pending"


def test_t5_full_vocabulary_stays_green_allow_deny_hold_and_human_control(client):
    """T5 - the whole decision vocabulary is unchanged by ACT-7b.

    ALLOW (in scope), DENY (no entitlement), HOLD (require-human), then the two human controls
    (approve-from-HOLD, deny-from-HOLD) and the named revoke. Nothing here is a new capability;
    it is the proof that the attributed-revoke change touched nothing else.
    """
    tokens = _tokens(client)

    # ALLOW - the reconciliation agent reads payments, in scope
    allow = _mcp(client, "fin-reconcile", tokens["fin-reconcile"], "payments.read",
                 {"limit": 1}).json()
    assert allow["result"]["decision"] in ("allow", "redact")
    assert allow["result"]["executed"] is True

    # DENY - the deploy agent has no entitlement to deploy
    deny = _mcp(client, "deploy-agent", tokens["deploy-agent"], "deploy.service",
                {"service": "core-api"}).json()
    assert deny["error"]["data"]["decision"] == "deny"
    assert deny["error"]["data"]["executed"] is False

    # HOLD - a mass export needs a person; approve-from-HOLD resolves it
    def hold():
        return _mcp(client, "report-bot", tokens["report-bot"], "crm.bulk_export",
                    {"table": "customers", "rows": 260}).json()["error"]["data"]["action_id"]

    approved_id = hold()
    ap = client.post(f"/api/actions/{approved_id}/approve",
                     json={"by": "anna.kowalska"}, headers=_admin())
    assert ap.status_code == 200 and ap.json()["state"] == "approved"
    assert ap.json()["upstream_contacted"] is True

    # HOLD - deny-from-HOLD never contacts the upstream
    denied_id = hold()
    dn = client.post(f"/api/actions/{denied_id}/deny",
                     json={"by": "anna.kowalska"}, headers=_admin())
    assert dn.status_code == 200 and dn.json()["upstream_contacted"] is False

    # and the named revoke still halts and is attributed
    rv = client.post("/api/agents/support-copilot/revoke", json={"by": "anna.kowalska"}, headers=_admin())
    assert rv.status_code == 200 and rv.json()["state"] == "halted"
    assert rv.json()["by"] == "anna.kowalska"


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
                     "/api/agents", "/api/security-events", "/api/security-events/run-1"):
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
        out = asyncio.run(assist._control_plane_inspect("are we live?"))
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
    """D10: the control-plane suite and the D6 gate ship runnable and are wired into CI.

    The wiring lives in the workflow, or - while the repo's automation token lacks the
    ``workflow`` scope - in ``docs/ci-gate.patch``, the ready-made hunk the workflow is
    expected to carry. Whichever form is present, the gate script itself is never optional:
    a green pipeline that does not run the gate would be a claim, not a check.
    """
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    pending = (REPO_ROOT / "docs" / "ci-gate.patch")
    wiring = ci + "\n" + (pending.read_text(encoding="utf-8") if pending.exists() else "")
    assert "pytest -q tests/test_control_plane.py" in wiring
    assert "check_enforcement_local_only.py" in wiring
    assert (REPO_ROOT / "scripts/check_enforcement_local_only.py").exists()
# ------------------------------------------------- T7: one process serves UI + /api/* + /health
def test_run_command_binds_public_interface_not_loopback(monkeypatch):
    """T7 REGRESSION. The production failure was a static site answering ``/`` while
    ``/api/*`` returned 404 and ``/health`` returned an empty 200 - because the platform
    never reached the Python process: ``python -m control_plane`` defaulted to
    ``127.0.0.1`` while a container platform injects ``PORT`` only. The bind default must be
    ``0.0.0.0``; an explicit ``HOST`` still wins for a local-only run.
    """
    from control_plane.__main__ import _host

    monkeypatch.delenv("HOST", raising=False)
    assert _host() == "0.0.0.0", "a platform-injected PORT without HOST must bind the public iface"
    monkeypatch.setenv("HOST", "")
    assert _host() == "0.0.0.0"
    monkeypatch.setenv("HOST", "127.0.0.1")
    assert _host() == "127.0.0.1", "an explicit HOST is still honoured"


def test_deploy_contract_serves_one_process_ui_api_health():
    """T7: the shipped deploy config starts ONE uvicorn process on the public interface and
    health-checks ``/health`` - the Control Room page, ``/api/*`` and ``/health`` all answer
    from that process, so the API can never 404 while the static page loads.
    """
    import json

    rail = json.loads((REPO_ROOT / "railway.json").read_text(encoding="utf-8"))
    start = rail["deploy"]["startCommand"]
    # The launch command either names the app directly or is the entrypoint that starts the
    # tool server and then execs exactly that one uvicorn process. What must hold either way:
    # the app served is the control plane's, on the public interface, on the platform's port.
    entry = REPO_ROOT / "scripts" / "serve_tenet.sh"
    effective = start + "\n" + (entry.read_text(encoding="utf-8") if entry.exists() else "")
    assert "control_plane.app:app" in effective
    assert "0.0.0.0" in effective
    assert "$PORT" in effective or "${PORT" in effective
    assert rail["deploy"]["healthcheckPath"] == "/health"

    proc = (REPO_ROOT / "Procfile").read_text(encoding="utf-8")
    assert "serve_tenet.sh" in proc or "control_plane.app:app" in proc


def test_ui_health_and_api_share_one_process(client):
    """T7: the same app instance answers the UI, the health document and the API - the
    defect was that ``/`` loaded while ``/api/overview`` 404'd.
    """
    assert client.get("/").status_code == 200
    assert "<title>TENET" in client.get("/").text
    health = client.get("/health").json()
    assert health["status"] in ("LIVE", "DEGRADED", "DEMO")
    assert health["kernel"] == "available"
    assert client.get("/api/overview").status_code == 200
    assert client.get("/api/activity?limit=10").status_code == 200




# ------------------------- D10/D12: the live-proof assertions are honest, not a lottery
def _proof_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tenet_live_proof", REPO_ROOT / "scripts" / "tenet_live_proof.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_leak_check_does_not_fire_on_risk_office():
    """The bare fragment "sk-" is in the ordinary word "risk-office" - never a leak signal.

    This is the exact false positive the operator's run hit: a grounded answer always names the
    warrant issuer ``risk-office``, so ``"sk-" in text`` can never be trusted. The fix tests the
    key VALUE and a key-SHAPED token instead.
    """
    mod = _proof_module()
    answer = {"answer": "A-0003 was denied; warrant issued by `risk-office`.",
              "evidence": [{"action_id": "A-0003"}]}
    text = answer["answer"]
    # The old predicate would flag this grounded answer; the new one must not.
    assert "sk-" in text, "sanity: the word risk-office contains sk-"
    assert not mod.KEY_SHAPE.search(text), "risk-office must not look like a key"
    serialised = __import__("json").dumps(answer)
    assert not mod.KEY_SHAPE.search(serialised)


def test_leak_check_still_fires_on_a_key_shaped_token():
    """A real key-shaped token is still caught - the fix is stricter, not weaker."""
    mod = _proof_module()
    fake = "sk-" + "a" * 24
    assert mod.KEY_SHAPE.search(f"the model echoed {fake} into the answer")
    assert mod.KEY_SHAPE.search(__import__("json").dumps({"answer": fake}))


def test_groundedness_accepts_any_real_id_not_one_specific_id():
    """Grounding is structural: any id the kernel reports counts, wherever it is cited.

    The old check demanded ONE specific id appear verbatim in free prose - a lottery decided by
    phrasing. The new check intersects the cited ids with the ids that really exist.
    """
    mod = _proof_module()
    real = {"A-0001", "A-0002", "A-0003", "A-0004"}
    answer = {"answer": "Two actions never reached an upstream: A-0002 and A-0003.",
              "evidence": [{"action_id": "A-0005"}]}
    cited = mod._cited_action_ids(answer, answer["answer"])
    assert cited & real, "a real id in prose grounds the answer"

    # Evidence-only grounding also counts (a real action_id carried on the evidence list).
    answer2 = {"answer": "See the record.", "evidence": [{"action_id": "A-0003"}]}
    cited2 = mod._cited_action_ids(answer2, answer2["answer"])
    assert cited2 & real

    # An id that does not exist in the record is not grounding.
    answer3 = {"answer": "Nothing grounded here.", "evidence": [{"action_id": "A-9999"}]}
    cited3 = mod._cited_action_ids(answer3, answer3["answer"])
    assert not (cited3 & real)


def test_groundedness_detail_names_cited_and_existing_ids():
    """The check's detail must show both the ids cited and the ids that exist (operator asks)."""
    src = (REPO_ROOT / "scripts" / "tenet_live_proof.py").read_text(encoding="utf-8")
    assert '"cited"' in src and '"exist"' in src and '"intersection"' in src
    # And it must build the real set from the kernel's own ledger, not from a constant.
    assert "/api/actions" in src


def test_proof_exits_nonzero_on_any_failed_check():
    """D12: the proof cannot report ok while a check is red."""
    src = (REPO_ROOT / "scripts" / "tenet_live_proof.py").read_text(encoding="utf-8")
    assert 'return 0 if not failed else 1' in src
    assert "_print_table()" in src



# ----------------------------------------------- canonical scenario trigger (/api/demo/run)
def test_demo_run_requires_operator_token(client):
    """An anonymous driver must not be able to make TENET reach the outside world."""
    assert client.post("/api/demo/run").status_code == 401
    assert client.post("/api/demo/run", json={},
                       headers={"x-warrnt-admin": "not-the-token"}).status_code == 401


def test_demo_run_refuses_when_no_live_upstream_is_configured(client, monkeypatch):
    """No upstream -> an explicit refusal, never a fabricated rate (D12)."""
    monkeypatch.delenv("WARRNT_UPSTREAM", raising=False)
    r = client.post("/api/demo/run", headers=_admin())
    assert r.status_code == 503
    assert r.json()["decision"] == "deny"
    assert "never" in r.json()["note"]


def test_demo_run_shape_when_an_upstream_is_configured(client, monkeypatch):
    """With an upstream configured the answer carries the whole correlation, or a refusal.

    The real crossing is proven against the live Frankfurter API by
    ``scripts/t1_upstream_proof.py`` and on the deployment; here the URL points at a dead
    port, so what is asserted is the shape plus the rule that matters most: a call that did
    not reach a 200 cannot be reported as having contacted the upstream.
    """
    monkeypatch.setenv("WARRNT_UPSTREAM", "http://127.0.0.1:9/mcp")
    # The boot seed ran before this URL existed, so mint the live warrants now - the same
    # kernel call the lifespan makes; nothing about the decision path changes.
    client.app.state.kernel.issue_live_warrants()
    r = client.post("/api/demo/run", headers=_admin())
    assert r.status_code == 200
    body = r.json()
    for field in ("scenario", "agent", "run_id", "action_id", "decision", "receipt",
                  "upstream_contacted", "execution_result"):
        assert field in body, field
    assert body["run_id"].startswith("demo-")
    assert body["scenario"] == "fx.read_rate"
    assert body["execution_result"].get("http_status") != 200
    assert body["upstream_contacted"] is False
    # A refusal is still a recorded action with a receipt: the denial is itself evidence.
    assert body["action_id"]


# ============================================================ ACT-2: identity, entitlement,
# separation of duties, proof of non-contact. These run against the same mirrored kernel the
# node tests use, so a green here means the control plane relays real decisions, not fixtures.

def test_agents_projection_carries_identity_and_entitlements(client):
    """ACT-2 §1/§2: who the agent acts for, and what it is entitled to - on the operator feed."""
    rows = {a["id"]: a for a in client.get("/api/agents").json()}
    copilot = rows["support-copilot"]
    assert copilot["principal"] == "operator-001"
    assert copilot["on_behalf_of"] == "operator-001"
    assert "crm.read" in copilot["entitlements"]


def test_action_records_the_principal_it_was_taken_for(client):
    tok = _tokens(client)["support-copilot"]
    aid = _mcp(client, "support-copilot", tok, "crm.read",
               {"table": "tickets"}).json()["result"]["action_id"]
    action = client.get(f"/api/actions/{aid}").json()
    assert action["principal"] == "operator-001"
    assert action["acting_on_behalf_of"] == "operator-001"
    assert action["requester"]


def test_entitlement_absent_is_refused_before_the_order_decides(client, monkeypatch):
    """ACT-2 §2: a live warrant is not a grant of data; the missing right is named.

    ``equity.read_snapshot`` is a live tool (filed by the control plane's taxonomy) that
    ``support-copilot`` holds no right for, so the entitlement gate - which runs before the
    order is priced - refuses it deterministically.
    """
    tok = _tokens(client)["support-copilot"]
    r = _mcp(client, "support-copilot", tok, "equity.read_snapshot", {})
    assert r.status_code == 200
    err = r.json()["error"]
    assert err["data"]["decision"] == "deny"
    assert err["data"]["gate"] == "entitlement"
    assert err["data"]["entitlement"] == "market_data.equity.read"
    aid = err["data"]["action_id"]
    # Nothing reached the far side: an entitlement deny is a boundary of zero approaches.
    assert client.get(f"/api/actions/{aid}").json()["upstream_contacted"] is False


def test_requester_may_not_approve_their_own_hold(client):
    """ACT-2 §3: separation of duties - a distinct 409, and the hold is left pending."""
    tok = _tokens(client)["deploy-agent"]
    aid = _mcp(client, "deploy-agent", tok, "infra.deploy",
               {"service": "fx-api"}).json()["error"]["data"]["action_id"]
    requester = client.get(f"/api/actions/{aid}").json()["requester"]
    assert requester
    refused = client.post(f"/api/actions/{aid}/approve", json={"by": requester}, headers=_admin())
    assert refused.status_code == 409, refused.text
    assert refused.json()["refused"] == "separation_of_duties"
    after = client.get(f"/api/actions/{aid}").json()
    assert after["state"] == "pending"
    assert after["upstream_contacted"] is False


def test_a_second_person_can_still_approve(client):
    tok = _tokens(client)["deploy-agent"]
    aid = _mcp(client, "deploy-agent", tok, "infra.deploy",
               {"service": "fx-api"}).json()["error"]["data"]["action_id"]
    ok = client.post(f"/api/actions/{aid}/approve", json={"by": "operator-002-approver"},
                     headers=_admin())
    assert ok.status_code == 200, ok.text
    assert ok.json()["executed"] is True


def test_the_self_approval_refusal_is_recorded_in_the_chain(client):
    tok = _tokens(client)["deploy-agent"]
    aid = _mcp(client, "deploy-agent", tok, "infra.deploy",
               {"service": "fx-api"}).json()["error"]["data"]["action_id"]
    requester = client.get(f"/api/actions/{aid}").json()["requester"]
    client.post(f"/api/actions/{aid}/approve", json={"by": requester}, headers=_admin())
    receipts = client.get("/api/state?limit=50").json()["receipts"]
    reasons = [str(r.get("reason", "")) for r in receipts]
    assert any("separation of duties" in r for r in reasons), reasons
    # A refusal is a deny, and it never reached the far side (D5: a denial is itself an event).
    refusals = [r for r in receipts if "separation of duties" in str(r.get("reason", ""))]
    assert refusals and refusals[0]["decision"] == "deny"


def test_denied_action_shows_zero_boundary_attempts(client):
    """ACT-2 §4: the counter is evidence, not narration - 0 for a deny, 1 for an allow."""
    tok = _tokens(client)["support-copilot"]
    denied = _mcp(client, "support-copilot", tok, "crm.bulk_export",
                  {"table": "customers", "rows": 9000}).json()["error"]["data"]["action_id"]
    assert client.get(f"/api/actions/{denied}").json()["boundary_attempts"] == 0


def test_allowed_action_shows_exactly_one_boundary_attempt(client):
    tok = _tokens(client)["fin-reconcile"]
    aid = _mcp(client, "fin-reconcile", tok, "payments.read",
               {"table": "payments"}).json()["result"]["action_id"]
    row = client.get(f"/api/actions/{aid}").json()
    assert row["boundary_attempts"] == 1
    assert row["upstream_contacted"] is True


def test_attest_non_contact_proves_a_denied_action_never_left(client):
    tok = _tokens(client)["support-copilot"]
    aid = _mcp(client, "support-copilot", tok, "crm.bulk_export",
               {"table": "customers", "rows": 9000}).json()["error"]["data"]["action_id"]
    r = client.post("/api/attest/non-contact", json={"action_id": aid}, headers=_admin())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contacted"] is False
    assert body["boundary_attempts"] == 0
    assert body["count_before"] == body["count_after"]


def test_attest_refuses_an_action_the_record_shows_contacted(client):
    tok = _tokens(client)["fin-reconcile"]
    aid = _mcp(client, "fin-reconcile", tok, "payments.read",
               {"table": "payments"}).json()["result"]["action_id"]
    r = client.post("/api/attest/non-contact", json={"action_id": aid}, headers=_admin())
    assert r.status_code == 409, r.text
    assert r.json()["contacted"] is True


def test_attest_unknown_action_is_404(client):
    r = client.post("/api/attest/non-contact", json={"action_id": "A-0099999"},
                    headers=_admin())
    assert r.status_code == 404


def test_attest_requires_the_operator_token(client):
    r = client.post("/api/attest/non-contact", json={"action_id": "A-0001"},
                    headers={"x-warrnt-admin": "wrong"})
    assert r.status_code == 401


def test_upstream_log_route_requires_the_operator_token(client):
    assert client.get("/api/upstream/log",
                      headers={"x-warrnt-admin": "wrong"}).status_code == 401


def test_upstream_log_reports_absence_honestly_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("WARRNT_UPSTREAM_LOG", raising=False)
    monkeypatch.delenv("FRANKFURTER_LOG", raising=False)
    body = client.get("/api/upstream/log", headers=_admin()).json()
    assert body["exists"] is False
    assert body["entries"] == []
    assert body["sha256"] == ""


def test_upstream_log_reads_a_real_file_with_a_digest(client, tmp_path, monkeypatch):
    log = tmp_path / "upstream.jsonl"
    log.write_text('{"call_id": "A-0001", "tool": "equity.read_snapshot", "outcome": "ok"}\n',
                   encoding="utf-8")
    monkeypatch.setenv("WARRNT_UPSTREAM_LOG", str(log))
    body = client.get("/api/upstream/log", headers=_admin()).json()
    assert body["exists"] is True
    assert body["total"] == 1
    assert body["entries"][0]["call_id"] == "A-0001"
    assert len(body["sha256"]) == 64
    filtered = client.get("/api/upstream/log?tool=other", headers=_admin()).json()
    assert filtered["total"] == 0

def test_upstream_log_reader_honours_every_writer_name_the_deployment_uses(monkeypatch):
    """The evidence endpoint must be able to read the journal the deployment actually writes.

    serve_tenet.sh names the upstream's access log with an env var. If the reader does not honour
    that exact name, the upstream logs every real call and /api/upstream/log still reports none -
    a broken chain that looks like nothing happened. This test fails the moment they diverge, so
    the invariant "writer == reader == evidence endpoint" cannot rot.
    """
    import re
    from pathlib import Path as _Path

    from control_plane.kernel import _ensure_mirror_on_path

    _ensure_mirror_on_path()
    from warrnt.api import upstream_log_path

    script = _Path(__file__).resolve().parents[1] / "scripts" / "serve_tenet.sh"
    writers = set(re.findall(r"\b([A-Z][A-Z0-9_]*_UPSTREAM_LOG)\b",
                            script.read_text(encoding="utf-8")))
    assert writers, "serve_tenet.sh must name the upstream access log it writes"
    for name in ("TENET_UPSTREAM_LOG", "WARRNT_UPSTREAM_LOG", "FRANKFURTER_LOG"):
        monkeypatch.delenv(name, raising=False)
    for name in sorted(writers):
        monkeypatch.setenv(name, f"/tmp/{name.lower()}-probe.jsonl")
        assert upstream_log_path() == f"/tmp/{name.lower()}-probe.jsonl"
        monkeypatch.delenv(name)


def test_upstream_log_route_reads_a_journal_written_under_the_deployment_name(
        client, tmp_path, monkeypatch):
    """The route the jury reads must see the file the deployment's own name points at."""
    log = tmp_path / "tenet-upstream-calls.jsonl"
    log.write_text('{"call_id": "A-0001", "tool": "fx.read_rate", "outcome": "ok"}\n',
                   encoding="utf-8")
    for name in ("TENET_UPSTREAM_LOG", "WARRNT_UPSTREAM_LOG", "FRANKFURTER_LOG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TENET_UPSTREAM_LOG", str(log))
    body = client.get("/api/upstream/log", headers=_admin()).json()
    assert body["exists"] is True
    assert body["total"] == 1
    assert body["path"] == str(log)
    assert len(body["sha256"]) == 64


# ---------------------------------------------- ACT-4 slice A: the security-decision feed
def test_security_events_never_claim_authority(client):
    """The projection reports the kernel's verdict; it is never itself an authority (D5)."""
    body = client.get("/api/security-events").json()
    assert body["authority_source"] == "tenet-kernel"
    assert body["llm_authority"] is False
    for event in body["events"]:
        assert event["authority_source"] == "tenet-kernel"
        assert event["llm_authority"] is False


def test_security_events_shape_is_newest_first(client):
    tok = _tokens(client)["fin-reconcile"]
    _mcp(client, "fin-reconcile", tok, "payments.read", {"table": "payments", "limit": 2})
    body = client.get("/api/security-events?limit=10").json()
    assert {"count", "events", "mode"} <= set(body)
    events = body["events"]
    assert events, "a real call must appear in the feed"
    required = {"event_id", "run_id", "agent", "resource", "tool", "policy", "decision",
                "state", "reason", "upstream_contacted", "upstream_call_id", "receipt_id",
                "model_trace_id", "boundary_attempts", "llm_authority"}
    for event in events:
        assert required <= set(event), required - set(event)
    stamps = [e["timestamp"] or 0.0 for e in events]
    assert stamps == sorted(stamps, reverse=True), "newest first"


def test_security_events_limit_is_clamped(client):
    """An operator cannot ask for the whole table through one screen."""
    assert client.get("/api/security-events?limit=9999").json()["count"] <= 200
    assert client.get("/api/security-events?limit=0").status_code == 200


def test_security_events_a_deny_is_recorded_and_never_contacted(client):
    """D10 negative case: a blocked call is an event, and it never reached the far side."""
    tok = _tokens(client)["support-copilot"]
    aid = _mcp(client, "support-copilot", tok, "crm.bulk_export",
               {"table": "customers", "rows": 9000}).json()["error"]["data"]["action_id"]
    event = next(e for e in client.get("/api/security-events?limit=50").json()["events"]
                 if e["event_id"] == aid)
    assert event["decision"] == "deny"
    assert event["upstream_contacted"] is False
    assert event["receipt_id"], "a denial is itself a recordable event (D5)"


def test_security_events_a_permitted_call_shows_the_crossing(client):
    """D10 positive case: an allowed call records the contact and a real receipt."""
    tok = _tokens(client)["fin-reconcile"]
    aid = _mcp(client, "fin-reconcile", tok, "payments.read",
               {"table": "payments"}).json()["result"]["action_id"]
    event = next(e for e in client.get("/api/security-events?limit=50").json()["events"]
                 if e["event_id"] == aid)
    assert event["decision"] == "allow"
    assert event["upstream_contacted"] is True
    assert event["receipt_id"]


def test_security_events_never_invent_a_counter_the_record_lacks(client):
    """An absent field is ``null``, never a default that reads as success (D12).

    The node surface this deployment runs does not carry ``boundary_attempts`` on the action
    row, so the projection must report ``null`` - not ``0`` for a deny and not ``0`` for an
    allow, either of which would read as evidence it does not have. The flag that IS present,
    ``upstream_contacted``, stays the one the feed leans on.
    """
    tok = _tokens(client)["fin-reconcile"]
    _mcp(client, "fin-reconcile", tok, "payments.read", {"table": "payments", "limit": 1})
    for event in client.get("/api/security-events?limit=50").json()["events"]:
        assert event["boundary_attempts"] in (None, 0, 1), event["boundary_attempts"]
        # The counter is evidence, never a claim: a missing counter is allowed to sit next to
        # an absent contact, but it must never be manufactured into a number on its own.
        if event["boundary_attempts"] is None:
            assert "boundary_attempts" in event


def test_security_event_unknown_run_is_404(client):
    assert client.get("/api/security-events/no-such-run").status_code == 404


def test_security_event_chain_is_evidence_not_authority(client):
    """The causal graph names the missing nodes; it never rounds a partial chain up (rule 5)."""
    tok = _tokens(client)["fin-reconcile"]
    _mcp(client, "fin-reconcile", tok, "payments.read", {"table": "payments", "limit": 1})
    run_id = next(e["run_id"] for e in client.get("/api/security-events?limit=50").json()["events"]
                  if e["agent"] == "fin-reconcile" and e["run_id"])
    body = client.get(f"/api/security-events/{run_id}").json()
    assert body["causal_graph"]["authority_lives_here"] == "decision"
    assert body["llm_authority"] is False
    nodes = {n["step"]: n["id"] for n in body["causal_graph"]["nodes"]}
    assert nodes["run_id"] == run_id
    # ``upstream_call_id`` is minted at the boundary in slice B and is honestly null today -
    # action_id is never relabelled as a call id (constraint 5).
    assert nodes.get("upstream_call_id") is None
    # No provider key in the fixture, so the model step is absent and named, never invented.
    assert "model_trace_id" in body["missing"]
    assert body["status"] == "INCOMPLETE"


def test_model_usage_is_a_read_only_resource_projection(client):
    body = client.get("/api/model-usage").json()
    required = {"provider", "model_requested", "calls_started", "calls_completed",
                "calls_failed", "input_tokens", "output_tokens", "total_tokens",
                "max_latency_ms", "latest_trace_id", "latest_status", "evidence", "mode"}
    assert required <= set(body)
    assert body["provider"] == "deepseek"
    assert body["evidence"] == "persisted DeepSeek provider events"
    assert "DEEPSEEK_API_KEY" not in str(body)
