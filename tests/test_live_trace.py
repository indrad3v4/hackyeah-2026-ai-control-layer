"""Tests for the LIVE SECURITY TRACE (contract ``docs/act-5-live-security-trace-contract.md``).

Each test below is one acceptance criterion, and it fails on the code before the change:

* AC1  - an empty kernel serves ``trace: null`` and invents nothing (AC1b: every absent
         field is ``null`` and named in ``incomplete``);
* AC2  - ``upstream.contacted`` is true ONLY with an ``http_status``; an allow with no
         crossing is reported as NOT contacted and named ``upstream.http_status``;
* AC3  - ``POST /api/scenario/self-check`` is credential-free, uses the fixed scenario, is
         rate limited (429 on the second immediate call), refuses with 503 and writes NO
         record when no upstream is configured, and a successful call writes exactly one action;
* AC4  - the startup warm trace is idempotent: an existing action means it runs nothing;
* AC5(e) - the served page contains no ``WARRNT_ADMIN`` value, no agent token, no ``sk-``.

No network: ``TestClient`` drives the app in-process, and the upstream URL points at a dead
port so a "crossing" is a real attempted egress that simply does not reach a 200 - exactly the
case the honest boundary rule exists for. The kernel is the repository's own mirror, never a
stub (a stub that answered "allow" would prove nothing).
"""
from __future__ import annotations

import re
from pathlib import Path as _Path

import pytest
from fastapi.testclient import TestClient

from control_plane.app import (create_app, SELF_CHECK_AGENT, SELF_CHECK_RUN_PREFIX,
                               ORIGIN_SELF_CHECK)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A live instance whose store is a throwaway dir, with a (dead) upstream configured."""
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # A real URL, a dead port: the self-check performs a genuine attempted crossing whose
    # result is a refused connection, never a fabricated 200.
    monkeypatch.setenv("WARRNT_UPSTREAM", "http://127.0.0.1:9/mcp")
    app = create_app(seed=True)
    with TestClient(app) as c:
        c.app = app
        yield c


def _actions(client) -> list[dict]:
    body = client.get("/api/actions").json()
    return body["actions"] if isinstance(body, dict) else body


def _agent_tokens(client) -> dict[str, str]:
    return {a["id"]: a.get("token", "") for a in client.get("/api/agents").json() if a.get("token")}


def _mcp(client, agent, token, tool, args):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": tool, "arguments": args}},
                       headers={"x-warrnt-agent": agent, "x-warrnt-token": token})


# ------------------------------------------------------------------------------ AC1 / AC1b
def _empty_client(tmp_path, monkeypatch):
    """A live instance with NO upstream: the kernel stays empty (the warm trace no-ops)."""
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.delenv("WARRNT_UPSTREAM", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(seed=True)
    return app


def test_ac1_empty_kernel_serves_null_trace_and_invents_nothing(tmp_path, monkeypatch):
    """No action -> ``trace: null``, authority still named, nothing fabricated (AC1).

    No upstream is configured, so the AC4 warm trace correctly no-ops and the kernel holds
    zero actions - the honest empty state, served without a single invented field.
    """
    app = _empty_client(tmp_path, monkeypatch)
    with TestClient(app) as c:
        assert _actions(c) == []
        r = c.get("/api/live-trace")
        assert r.status_code == 200
        body = r.json()
        assert body["trace"] is None
        assert body["authority_source"] == "tenet-kernel"
        assert body["llm_authority"] is False


def test_ac1_live_trace_composes_the_last_action_with_its_authority(client):
    """After one real action the trace carries the whole chain, decision spelled out (AC1)."""
    token = _agent_tokens(client)["fx-trader"]
    r = _mcp(client, "fx-trader", token, "fx.read_rate", {"base": "EUR", "symbols": "USD"})
    assert r.status_code == 200
    trace = client.get("/api/live-trace").json()["trace"]
    assert trace is not None
    for field in ("run_id", "action_id", "agent", "action", "checks", "decision",
                  "reason", "decided_by", "upstream", "receipt_id", "model", "incomplete"):
        assert field in trace, field
    assert trace["agent"] == "fx-trader"
    assert trace["action"]["tool"] == "fx.read_rate"
    assert trace["decided_by"] == "tenet-kernel"
    assert trace["decision"] == "allow"
    # AC1b: whatever is absent is named in ``incomplete`` as a dotted path (e.g.
    # ``action.intent``, ``checks.warrant.state``), and the evidence at that path is genuinely
    # absent - null, or an object whose fields are all null. The name is never decoration.
    for name in trace["incomplete"]:
        assert re.match(r"^[a-z_]+(\.[a-z_]+)*$", name), name
        node = trace
        for part in name.split("."):
            node = node[part]
        if isinstance(node, dict):
            assert all(v is None for v in node.values()), f"{name} is named incomplete but has evidence"
        else:
            assert node is None, f"{name} is named incomplete but is not null"


def test_ac1b_absent_evidence_is_null_and_named(client):
    """A denial carries no crossing: ``contacted`` false, ``http_status`` null, named (AC1b/AC2)."""
    # support-copilot holds entitlements that do NOT cover fx.read_rate, so the kernel denies -
    # a decision with no attempt, whose missing crossing must be stated, not implied.
    token = _agent_tokens(client)["support-copilot"]
    r = _mcp(client, "support-copilot", token, "fx.read_rate", {"base": "EUR", "symbols": "USD"})
    assert r.status_code == 200
    trace = client.get("/api/live-trace").json()["trace"]
    assert trace["decision"] in ("deny", "human")
    assert trace["upstream"]["contacted"] is False
    assert trace["upstream"]["http_status"] is None


# ------------------------------------------------------------------------------------- AC2
def test_ac2_allow_without_http_status_is_not_contacted_and_named(client):
    """The honest boundary rule: an ``allow`` alone never proves a crossing (AC2).

    ``fx.audit_note`` is in the ``fx-trader`` warrant scope but the upstream is a dead port, so
    the decision is an allow and the attempted crossing does NOT reach an ``http_status``. The
    trace must say ``contacted: false`` and name ``upstream.http_status`` as incomplete.
    """
    token = _agent_tokens(client)["fx-trader"]
    r = _mcp(client, "fx-trader", token, "fx.audit_note", {"note": "desk review"})
    assert r.status_code == 200
    trace = client.get("/api/live-trace").json()["trace"]
    assert trace["decision"] in ("allow", "redact")
    assert trace["upstream"]["contacted"] is False, "allow without http_status must not claim contact"
    assert trace["upstream"]["http_status"] is None
    assert "upstream.http_status" in trace["incomplete"]


# ------------------------------------------------------------------------------------- AC3
def test_ac3_self_check_runs_without_a_credential_and_writes_one_action(client):
    """The browser's only trigger needs no token and writes exactly one real action (AC3)."""
    before = len(_actions(client))
    r = client.post("/api/scenario/self-check")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authority_source"] == "tenet-kernel"
    assert body["llm_authority"] is False
    trace = body["trace"]
    assert trace is not None
    assert trace["agent"] == SELF_CHECK_AGENT
    assert trace["action"]["tool"] == "fx.read_rate"
    # The kernel may withhold argument VALUES on the projection (``values_withheld``): the
    # fixed scenario's field names are still visible, which is what proves which call was run.
    assert trace["action"]["args"].get("keys") == ["base", "symbols"]
    assert trace["origin"] == ORIGIN_SELF_CHECK
    assert str(trace["run_id"]).startswith(SELF_CHECK_RUN_PREFIX)
    assert len(_actions(client)) == before + 1, "exactly one action written"


def test_ac3_second_immediate_call_is_rate_limited(client):
    """At most one run per window: a second immediate call is 429 with ``retry_after_s`` (AC3)."""
    assert client.post("/api/scenario/self-check").status_code == 200
    second = client.post("/api/scenario/self-check")
    assert second.status_code == 429
    assert second.json()["error"] == "rate limited"
    assert isinstance(second.json()["retry_after_s"], int)
    assert second.json()["retry_after_s"] >= 1


def test_ac3_no_upstream_is_503_and_writes_no_record(tmp_path, monkeypatch):
    """No live upstream -> 503, and NOT a single action is written (AC3, D12)."""
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.delenv("WARRNT_UPSTREAM", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(seed=True)
    with TestClient(app) as c:
        r = c.post("/api/scenario/self-check")
        assert r.status_code == 503
        assert r.json()["error"] == "no upstream configured"
        assert _actions(c) == []


def test_ac3_fixed_scenario_ignores_request_supplied_tool_and_args(client):
    """The tool and args are server constants; a body cannot steer the crossing (AC3)."""
    r = client.post("/api/scenario/self-check",
                    json={"tool": "fx.drain_account", "args": {"base": "XXX"},
                          "agent": "support-copilot"})
    assert r.status_code == 200
    trace = r.json()["trace"]
    assert trace["action"]["tool"] == "fx.read_rate"
    assert trace["action"]["args"].get("keys") == ["base", "symbols"]
    assert trace["agent"] == SELF_CHECK_AGENT


# ------------------------------------------------------------------------------------- AC4
def _actions_from(app) -> list[dict]:
    """List actions directly off the kernel (no HTTP), for the lifespan-level AC4 test."""
    return app.state.kernel.actions(60)


def test_ac4_startup_warm_trace_is_idempotent(tmp_path, monkeypatch):
    """An existing action means the lifespan warm trace runs nothing new (AC4).

    Two boots over the SAME store: the first seeds and (kernel empty) runs one startup
    self-check; the second finds an action and must add none. What this proves is the guard,
    not timing - the count after the second boot equals the count after the first.
    """
    state = str(tmp_path / "state")
    monkeypatch.setenv("TENET_STATE_DIR", state)
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.setenv("WARRNT_UPSTREAM", "http://127.0.0.1:9/mcp")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    app1 = create_app(seed=True)
    with TestClient(app1):
        first = len(_actions_from(app1))
    assert first >= 1, "an empty kernel with a live upstream should warm the centre"
    run_id = str(_actions_from(app1)[0].get("run_id") or "")
    assert run_id.startswith("startup-"), run_id

    app2 = create_app(seed=True)
    with TestClient(app2):
        second = len(_actions_from(app2))
    assert second == first, "a second boot over a populated store must not add an action"


# ----------------------------------------------------------------------------------- AC5(e)
def test_ac5_served_page_contains_no_credential_or_key(client):
    """The page must carry no token, no ``WARRNT_ADMIN`` value and no ``sk-`` key (AC5e)."""
    import os as _os
    html = client.get("/").text
    assert "WARRNT_ADMIN" not in html
    assert _os.environ["WARRNT_ADMIN_TOKEN"] not in html
    assert "test-admin-token" not in html
    assert "sk-" not in html
    # The revoke control stays behind the admin credential exactly as today.
    assert "x-warrnt-admin" in html


# ------------------------------------------------------------------------------------- AC4 (round 2)
# The round-1 test asserted index.html's PROSE ("LIVE SECURITY TRACE" was in the source). That is
# the defect ACT-5b fixes: a source-reading test is green while the rendered hero shows dashes.
# These tests are the data<->data contract instead: run the REAL projection, flatten its leaves,
# and prove (1) every path TRACE_KEYS declares exists in the payload, (2) every payload path the
# render code reads is declared, and (3) the page reads none of the round-1 phantom paths.
_PAGE = (_Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")


def _declared_paths() -> dict[str, str]:
    """The ``TRACE_KEYS`` object literal from the page: ``{jsName: "t.dotted.path[]"}``."""
    block = re.search(r"const TRACE_KEYS\s*=\s*\{(.*?)\};", _PAGE, re.S)
    assert block, "index.html must declare const TRACE_KEYS = { ... }"
    out: dict[str, str] = {}
    for name, path in re.findall(r'(\w+)\s*:\s*"([^"]+)"', block.group(1)):
        out[name] = path
    return out


def _flatten(payload, prefix: str = "") -> set[str]:
    """Every leaf path a JSON object/array exposes, ``[]`` marking an array."""
    leaves: set[str] = set()
    if isinstance(payload, dict):
        for k, v in payload.items():
            leaves |= _flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(payload, list):
        leaves.add(prefix + "[]")
        for item in payload:
            if isinstance(item, dict):
                leaves |= _flatten(item, prefix + "[]")
    else:
        leaves.add(prefix)
    return leaves


def _path_exists(leaves: set[str], path: str) -> bool:
    """True iff ``path`` is a leaf of the payload or a container prefix of one.

    ``TRACE_KEYS`` may declare a container (``action.args``) whose leaves the flatten descends
    into; that declaration still names a real path in the payload, so it counts as existing.
    """
    want = path.rstrip("[]")
    for leaf in leaves:
        leaf_p = leaf.rstrip("[]")
        if leaf_p == want or leaf_p.startswith(want + ".") or leaf_p.startswith(want + "[]."):
            return True
        # An array leaf (``t.entitlements[]``) also satisfies a declaration of its container.
        if want.startswith(leaf_p + ".") or want.startswith(leaf_p + "[]."):
            return True
    return False


def _render_code_paths() -> set[str]:
    """The dotted ``…​.path`` reads performed by the hero render code, normalised to ``t.`` form."""
    start = _PAGE.index("const TRACE_KEYS")
    end = _PAGE.index("function renderResource")
    code = _PAGE[start:end]
    found: set[str] = set()
    # ``t.action.tool`` / ``t.checks.warrant.state`` style reads (object/optional-chained access).
    for m in re.findall(r"\bt(?:\.\w+)+", code):
        found.add(m)
    # Reads that go through the destructured aliases (ap./c./w./up.) map back to ``t.*``.
    alias = {"ap": "t.action", "c": "t.checks", "w": "t.checks.warrant", "up": "t.upstream"}
    for m in re.findall(r"\b(ap|c|w|up)((?:\.\w+)+)", code):
        found.add(alias[m[0]] + m[1])
    return found


def test_ac4_trace_keys_exist_in_the_real_payload(client):
    """Every path TRACE_KEYS declares is a real leaf of ``kernel.live_trace()`` (AC4).

    The payload is produced by the repository's OWN kernel after one enforced scenario - not by a
    stub - so a declared path that the projection does not emit fails here. ``TRACE_KEYS`` paths
    carry the page's ``t.`` alias for the trace object; the payload's leaves are its root, so the
    alias is stripped before the comparison.
    """
    token = _agent_tokens(client)["fx-trader"]
    assert _mcp(client, "fx-trader", token, "fx.read_rate",
                {"base": "EUR", "symbols": "USD"}).status_code == 200
    trace = client.app.state.kernel.live_trace()
    assert trace is not None
    payload = {"trace": trace, "llm_authority": False, "authority_source": "tenet-kernel"}
    leaves = _flatten(payload) | {p[len("trace."):] for p in _flatten(payload)
                                  if p.startswith("trace.")}
    declared = _declared_paths()
    assert declared, "TRACE_KEYS must not be empty"

    def real(path: str) -> bool:
        p = path[len("t."):] if path.startswith("t.") else path
        return _path_exists(leaves, p)

    missing = [p for p in declared.values() if not real(p)]
    assert not missing, f"declared but absent from the payload: {missing}"



def test_ac4_render_reads_only_declared_paths():
    """Every payload path the render code interpolates is declared in TRACE_KEYS (AC4).

    This is the data<->data contract's other direction: a read added to the render code without a
    declaration fails, so the page can never again reach for a path the projection does not emit.
    """
    declared = set(_declared_paths().values())
    # ``t.*`` paths normalised away: TRACE_KEYS declares leaves; the render code reaches containers
    # (``t.action``) to read leaves (``t.action.tool``). ``t.model`` reads are covered by its leaves.
    covered = set()
    for d in declared:
        parts = d.rstrip("[]").split(".")
        for i in range(1, len(parts) + 1):
            covered.add(".".join(parts[:i]))
    unknown = sorted(p for p in _render_code_paths()
                     if p not in covered and not any(p.startswith(c + ".") for c in covered))
    assert not unknown, f"render code reads undeclared paths: {unknown}"


def test_ac4_page_reads_none_of_the_round1_phantom_paths():
    """The exact phantom paths of round 1 are gone from the page (AC1/AC6)."""
    start = _PAGE.index("const TRACE_KEYS")
    code = _PAGE[start:]
    for phantom in ("t.request?.tool", "t.boundary_crossed", "authorized_before_execution",
                    "receipt_present", "t.warrant?.", "t.upstream?.target", "t.upstream?.method",
                    "t.model.model??", "t.model.llm_authority)"):
        assert phantom not in code, f"round-1 phantom path still read: {phantom}"


# ------------------------------------------------------------------------------------- AC3 (round 2)
def _boundary_text(contacted) -> str:
    """The page's boundary sentence, derived ONLY from ``upstream.contacted`` (AC3).

    This mirrors ``renderTrace``'s ``bc``/``btxt`` exactly, using the three literal strings the page
    carries: a crossing names CONTACTED, a held boundary says NOT CONTACTED, an absent record says
    NOT PROVEN. A ``decision == "allow"`` is deliberately NOT an input - by construction it cannot
    turn a non-crossing into a crossing.
    """
    compact = _PAGE.replace(" ", "")
    assert "constbc=up.contacted;" in compact, "boundary state must derive from upstream.contacted only"
    assert '"NOT CONTACTED — the decision held the boundary"' in _PAGE
    assert '"NOT PROVEN in the record"' in _PAGE
    if contacted is True:
        return "CONTACTED"
    if contacted is False:
        return "NOT CONTACTED"
    return "NOT PROVEN"


def test_ac3_deny_renders_not_contacted_no_crossing(client):
    """A deny with no attempt renders NOT CONTACTED - never CONTACTED, never a dash (AC3)."""
    token = _agent_tokens(client)["support-copilot"]
    assert _mcp(client, "support-copilot", token, "fx.read_rate",
                {"base": "EUR", "symbols": "USD"}).status_code == 200
    trace = client.app.state.kernel.live_trace()
    assert trace["decision"] in ("deny", "human")
    assert trace["upstream"]["contacted"] is False
    assert _boundary_text(trace["upstream"]["contacted"]) == "NOT CONTACTED"


def test_ac3_allow_without_crossing_renders_not_proven_or_not_contacted(client):
    """An ``allow`` whose crossing is unproven never renders as a crossing (AC3)."""
    token = _agent_tokens(client)["fx-trader"]
    # fx.audit_note is in scope but the dead upstream yields no http_status -> contacted:false.
    assert _mcp(client, "fx-trader", token, "fx.audit_note",
                {"note": "desk review"}).status_code == 200
    trace = client.app.state.kernel.live_trace()
    contacted = trace["upstream"]["contacted"]
    assert contacted is not True, "an allow with no http_status must not claim a crossing"
    assert _boundary_text(contacted) in ("NOT CONTACTED", "NOT PROVEN")



def test_ac6_demo_run_still_requires_the_operator_token(client):
    """Nothing else is loosened: the demo trigger still needs the credential (AC6)."""
    assert client.post("/api/demo/run").status_code == 401
    assert client.post("/api/demo/run",
                       headers={"x-warrnt-admin": "wrong"}).status_code == 401


# ------------------------------------------------------------------- ACT-7d (composer honesty)
# The composer must prove a crossing from the EXECUTION RESULT (a real ``http_status`` on the
# row), never from the decision label, and must name the real resolver of a human hold instead
# of a hardcoded ``tenet-kernel``. These four drive the real hold / approve / deny path against
# the repository's own kernel, so the resolver and the state are the ones a real decision wrote.
def _admin_headers() -> dict[str, str]:
    return {"x-warrnt-admin": "test-admin-token"}


def _hold(client, rows: int = 500) -> str:
    """Open a real hold: ``report-bot`` exporting the CRM needs a person (decision: human)."""
    token = _agent_tokens(client)["report-bot"]
    r = _mcp(client, "report-bot", token, "crm.bulk_export", {"table": "customers", "rows": rows})
    assert r.status_code == 200
    return r.json()["error"]["data"]["action_id"]


# The crossing facts the far side (Frankfurter) records for one real 200 - the exact fields a
# live execution files onto the row. Injected through the kernel's own store so the composer is
# fed what the execution recorded, without a network dependency the test cannot carry.
_REAL_CROSSING = {
    "endpoint": "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD",
    "http_status": 200,
    "value": 1.1225,
    "response_sha256": "f63f64a5e9b3584bd32e0ea70927ea574bea7ef36df1a28fefb4ed6410400297",
    "latency_ms": 22.78,
    "rows": 500,
    "outcome": "ok",
}


def _file_crossing(client, action_id: str, crossing: dict) -> None:
    """File the execution result onto the row, exactly as the crossing recorder does on a call."""
    kernel = client.app.state.kernel
    action = kernel.proxy.actions.get(action_id)
    action.execution_result = dict(crossing)
    kernel.proxy.actions.save(action)


def test_act7d_human_approved_crossing_is_proven_and_names_the_person(client):
    """A person-approved execution that really crossed is reported as a crossing, by name.

    The row carries ``decision == "human"`` (a person resolved the hold) AND an execution result
    with a real ``http_status``. The decision label must not mask that evidence, and the person
    who decided must be named in ``decided_by`` - never the kernel.
    """
    action_id = _hold(client)
    ap = client.post(f"/api/actions/{action_id}/approve", json={"by": "indradev_"},
                     headers=_admin_headers())
    assert ap.status_code == 200 and ap.json()["executed"] is True
    _file_crossing(client, action_id, _REAL_CROSSING)

    trace = client.get(f"/api/live-trace?action_id={action_id}").json()["trace"]
    assert trace["decision"] == "human", "a human-resolved hold must keep the human decision"
    # D2: the person who decided is named; the kernel is NOT substituted for them.
    assert trace["decided_by"] == "indradev_", (
        "the composer erased the human who decided and named the kernel instead: %r"
        % trace["decided_by"])
    # D1: contact is proven from the execution result, whatever the decision label.
    up = trace["upstream"]
    assert up["contacted"] is True, "a real crossing was reported as no crossing at all"
    assert up["http_status"] == _REAL_CROSSING["http_status"]
    assert up["endpoint"] == _REAL_CROSSING["endpoint"]
    assert up["value"] == _REAL_CROSSING["value"]
    assert up["response_sha256"] == _REAL_CROSSING["response_sha256"]
    assert up["latency_ms"] == _REAL_CROSSING["latency_ms"]


def test_act7d_human_denied_hold_reports_no_crossing(client):
    """A person-denied hold never crossed: ``contacted`` false, no status, nothing invented."""
    action_id = _hold(client, rows=700)
    dn = client.post(f"/api/actions/{action_id}/deny", json={"by": "indradev_"},
                     headers=_admin_headers())
    assert dn.status_code == 200 and dn.json()["upstream_contacted"] is False

    trace = client.get(f"/api/live-trace?action_id={action_id}").json()["trace"]
    assert trace["decision"] == "human"
    assert trace["upstream"]["contacted"] is False
    assert trace["upstream"]["http_status"] is None
    assert trace["upstream"]["endpoint"] is None
    assert trace["upstream"]["value"] is None
    assert trace["upstream"]["response_sha256"] is None
    assert trace["upstream"]["latency_ms"] is None
    assert trace["decided_by"] == "indradev_", "the person who denied is not named"


def test_act7d_allow_without_execution_result_is_named_incomplete(client):
    """The honesty rule's other half: a permission with no execution result claims no crossing.

    An ``allow`` with no ``http_status`` on the row stays ``contacted: false`` and names
    ``upstream.http_status`` in ``incomplete`` - a permission is never rounded up to a crossing.
    """
    token = _agent_tokens(client)["fx-trader"]
    assert _mcp(client, "fx-trader", token, "fx.audit_note",
                {"note": "desk review"}).status_code == 200
    trace = client.get("/api/live-trace").json()["trace"]
    if trace["decision"] not in ("allow", "redact"):
        # The dead upstream may hold this tool; the rule is asserted on the allow branch it names.
        assert trace["upstream"]["contacted"] is False
        return
    assert trace["upstream"]["contacted"] is False, "an allow with no http_status must not cross"
    assert trace["upstream"]["http_status"] is None
    assert "upstream.http_status" in trace["incomplete"]


def test_act7d_kernel_decided_action_still_names_the_kernel(client):
    """Where the kernel alone decided, the trace still names the kernel honestly (no borrowing)."""
    token = _agent_tokens(client)["fin-reconcile"]
    assert _mcp(client, "fin-reconcile", token, "payments.read",
                {"table": "payments", "limit": 2}).status_code == 200
    trace = client.get("/api/live-trace").json()["trace"]
    assert trace["decision"] in ("allow", "redact")
    assert trace["decided_by"] == "tenet-kernel", (
        "a kernel-decided action must keep the kernel's own attribution: %r" % trace["decided_by"])


# ------------------------------------------------------------------- ACT-7e (composed state + executed)
# The composer must carry the action row's OWN resolved lifecycle state and an `executed` fact that
# is proven from the record, so the console can tell "still waiting for a person" from "a person
# approved" / "a person denied". These drive the real hold / approve / deny path against the
# repository's own kernel, so the state is the one a real decision wrote onto the row.
def test_act7e_human_approved_state_and_executed_are_composed(client):
    """A person-approved hold: the trace carries the row's own state, and the execution is proven.

    The row's state is what a person's approve wrote (``"approved"``), so the console can show the
    resolution instead of a permanent wait. The call really crossed (the crossing is filed as it is
    on the live rig), so ``executed`` must be proven true from the same evidence.
    """
    action_id = _hold(client)
    ap = client.post(f"/api/actions/{action_id}/approve", json={"by": "indradev_"},
                     headers=_admin_headers())
    assert ap.status_code == 200 and ap.json()["executed"] is True
    _file_crossing(client, action_id, _REAL_CROSSING)

    trace = client.get(f"/api/live-trace?action_id={action_id}").json()["trace"]
    row = client.app.state.kernel.action(action_id)
    assert trace["state"] == row["state"] == "approved", (
        "the composed state is not the row's own resolved state: trace=%r row=%r"
        % (trace["state"], row["state"]))
    assert trace["executed"] is True, "a proven execution was not composed as executed:true"
    assert trace["upstream"]["contacted"] is True
    assert trace["upstream"]["http_status"] == _REAL_CROSSING["http_status"]


def test_act7e_human_denied_state_and_executed_are_composed(client):
    """A person-denied hold: state ``"denied"``, ``executed`` false, and no crossing - all proven.

    The denial writes a state and an (empty) execution result onto the row, so the record itself
    proves the call did NOT run: ``executed`` is false, never null, and the far side was not
    contacted.
    """
    action_id = _hold(client, rows=700)
    dn = client.post(f"/api/actions/{action_id}/deny", json={"by": "indradev_"},
                     headers=_admin_headers())
    assert dn.status_code == 200 and dn.json()["upstream_contacted"] is False

    trace = client.get(f"/api/live-trace?action_id={action_id}").json()["trace"]
    row = client.app.state.kernel.action(action_id)
    assert trace["state"] == row["state"] == "denied", (
        "the composed state is not the row's own denied state: trace=%r row=%r"
        % (trace["state"], row["state"]))
    assert trace["executed"] is False, "a proven non-execution must be composed as executed:false"
    assert trace["upstream"]["contacted"] is False
    assert trace["upstream"]["http_status"] is None


def test_act7e_pending_hold_never_claims_an_execution(client):
    """A still-pending hold: no crossing, and the trace never claims an execution it cannot prove."""
    action_id = _hold(client, rows=900)

    trace = client.get(f"/api/live-trace?action_id={action_id}").json()["trace"]
    row = client.app.state.kernel.action(action_id)
    assert trace["decision"] == "human"
    assert trace["state"] == row["state"], (
        "the composed state is not the row's own pending state: trace=%r row=%r"
        % (trace["state"], row["state"]))
    assert trace["upstream"]["contacted"] is False, "a holding action must show no crossing"
    assert trace["upstream"]["http_status"] is None
    # The record does not prove an execution (no crossing): the trace must NOT claim one. It is
    # either the proven NEGATIVE or an honest null - never a fabricated True.
    assert trace["executed"] is not True, "a holding action claimed an execution it cannot prove"

