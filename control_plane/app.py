"""TENET Control Plane - the FastAPI app factory and the single user-facing runtime.

Run with::

    uvicorn control_plane.app:app --host 0.0.0.0 --port $PORT

This module owns the HTTP surface only. Every decision is delegated to the enforcement
kernel through :class:`control_plane.kernel.Kernel`; no route here allows, redacts or
contacts an upstream. If the kernel cannot answer, the decision endpoints return 503 and
``/api/ask`` returns a refusal - never a silent allow (contract TASK.2).

The three logical boundaries live in one process but stay explicit:

    Control Room (index.html)  ->  Control Plane (this app)  ->  Enforcement Kernel (mirror)
"""
from __future__ import annotations

import hmac
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import config
from .kernel import Kernel, KernelUnavailable, build_kernel

REPO_ROOT = Path(__file__).resolve().parent.parent

# The Control Room page is the repository's existing dashboard; served here so the boundary
# from UI -> API is one origin. Reflex (control_room/) stays a separate, optional surface.


def _kernel_or_503(app: FastAPI) -> tuple[Optional[Kernel], Optional[JSONResponse]]:
    """Return the kernel, or a 503 refusal when the authority is unavailable.

    A decision endpoint that cannot reach the kernel must refuse: fail-closed is the only
    safe answer when the thing that decides is missing.
    """
    kernel = getattr(app.state, "kernel", None)
    if kernel is None:
        return None, JSONResponse(
            {"error": "enforcement kernel unavailable", "decision": "deny",
             "note": "the control plane refuses to decide on its own"},
            status_code=503)
    return kernel, None


def _status(kernel: Optional[Kernel], identity: config.Identity) -> tuple[str, str]:
    """The one place the LIVE / DEGRADED / DEMO verdict is computed.

    * DEMO       - TENET_MODE=demo: fixtures are the source (never production).
    * LIVE       - live mode, kernel present, provider key PRESENT.
    * DEGRADED   - live mode but the authority or the provider is missing, with a reason.
    """
    if config.is_demo():
        return config.DEMO, "demo mode: fixture events only, never the production path"
    if kernel is None:
        return config.DEGRADED, "enforcement kernel unavailable"
    if not config.provider_key_present():
        return config.DEGRADED, "provider key ABSENT"
    return config.LIVE, "kernel present · provider key present"


def create_app(*, kernel: Optional[Kernel] = None, seed: bool = True) -> FastAPI:
    """Build the control-plane app. ``kernel`` is injectable for tests; default builds from the mirror."""

    identity = config.Identity.now()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Build the kernel once, before the first request, and re-issue the seed warrants the
        # same way the node does. A kernel that cannot build leaves ``app.state.kernel`` None,
        # and every decision route then fails closed with 503.
        if app.state.kernel is None:
            try:
                app.state.kernel = build_kernel()
            except KernelUnavailable:
                app.state.kernel = None
        if seed and app.state.kernel is not None:
            try:
                app.state.kernel.proxy.issue_all(reset_registry=False)
                app.state.kernel.proxy._expire_holds_of_halted_agents()
            except Exception:  # noqa: BLE001 - never block startup on a seed quirk
                pass
        # Hand the assistance surface the SAME kernel this process serves, so its read tools and
        # evidence floor answer in-process (no HTTP hop, no second instance, no second path).
        try:
            from control_room import agents as _assist

            _assist.bind_kernel(app.state.kernel)
        except Exception:  # noqa: BLE001 - the surface degrades to HTTP reads, never to a crash
            pass
        yield

    app = FastAPI(title="TENET Control Plane", version="0.1.0", lifespan=lifespan)
    app.state.kernel = kernel
    app.state.identity = identity
    app.state.runs = {}          # run_id -> {run_id, action_id, question, ts}

    # The operator token authorises the human-decision routes. It is the SAME token the kernel
    # uses (WARRNT_ADMIN_TOKEN) - this layer does not invent a second secret. When the operator
    # sets nothing, one is generated for this process and printed once, exactly as the node does.
    app.state.admin_token = os.environ.get("WARRNT_ADMIN_TOKEN", "").strip()
    app.state.generated_token = ""
    if not app.state.admin_token:
        app.state.generated_token = secrets.token_urlsafe(24)
        app.state.admin_token = app.state.generated_token
        print("[tenet] WARRNT_ADMIN_TOKEN is unset - generated for this process only:\n"
              f"[tenet]   {app.state.generated_token}\n"
              "[tenet] mutating routes need the header x-warrnt-admin: <token>", flush=True)

    # ------------------------------------------------------------------- UI + health
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def control_room() -> HTMLResponse:
        """The TENET Control Room page (the repository's existing dashboard)."""
        if not INDEX_HTML.exists():
            return HTMLResponse("<h1>TENET</h1><p>Control Room page missing</p>", status_code=500)
        return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))

    @app.get("/health")
    def health() -> dict[str, Any]:
        k = app.state.kernel
        status, reason = _status(k, app.state.identity)
        return {
            "status": status,
            "mode": config.mode(),
            "reason": reason,
            "provider": config.PROVIDER,
            "model": config.MODEL,
            "provider_key": "PRESENT" if config.provider_key_present() else "ABSENT",
            "model_provider": "deepseek",
            "commit": app.state.identity.commit,
            "uptime": app.state.identity.uptime_s(),
            "kernel": "available" if k is not None else "unavailable",
        }
    # ------------------------------------------------------------------- kernel reads
    @app.get("/api/overview")
    def overview() -> JSONResponse:
        """Counters + authority summary + mode, one payload - all projections of state.

        The counts come from ``kernel.read`` (the single read implementation the specialist
        tools also use), so the operator's UI and an agent's tool can never see two different
        numbers. With no data the lists are empty, never seeded (contract TASK.6).
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        return JSONResponse({**k.read("/api/overview"), "mode": config.mode()})

    @app.get("/api/activity")
    def activity(limit: int = 50) -> JSONResponse:
        """Ordered recent events, newest first - real receipts and real actions only.

        Each event is a record the node already holds; no synthesized events and no
        placeholder timestamps. Events carry ``run_id`` and ``action_id`` when the record
        itself does (contract TASK.5: one correlation, two traces).
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        events = k.activity(max(1, min(limit, 200)))["events"]
        if config.is_demo():
            # Fixtures are appended AFTER the real events and carry source="fixture", so the
            # demo feed is labelled and separated - it never replaces a live event (TASK.6).
            from .fixtures import fixture_events

            events = events + fixture_events(max(1, min(limit, 200)))
            return JSONResponse({"count": len(events), "events": events,
                                 "mode": config.mode(), "demo_feed": True})
        return JSONResponse({"count": len(events), "events": events, "mode": config.mode()})

    @app.get("/api/actions")
    def actions(state: str = "", limit: int = 60) -> JSONResponse:
        """The canonical Action log: the same object the console renders and an answer quotes."""
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        rows = (k.pending(limit) if state == "pending" else k.actions(limit))
        return JSONResponse({"counts": k.counts(), "pending": k.pending(),
                             "count": len(rows), "actions": rows})

    @app.get("/api/actions/pending")
    def actions_pending(limit: int = 50) -> JSONResponse:
        """Actions whose state is pending - the human holds, newest first.

        Declared before ``/api/actions/{action_id}``: otherwise "pending" is read as an id.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        rows = k.pending(max(1, min(limit, 200)))
        return JSONResponse({"count": len(rows), "pending": rows})

    @app.get("/api/actions/{action_id}")
    def action_detail(action_id: str) -> JSONResponse:
        """One action: its decision, its receipt and whether the upstream was contacted.

        Returns the kernel's own ``public()`` row, flattened, with a ``receipt_id`` alias so a
        consumer that names the receipt that way still finds it. No field is invented.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        row = k.action(action_id)
        if row is None:
            return JSONResponse({"error": f"unknown action {action_id}",
                                 "hint": "GET /api/actions lists the ledger"}, status_code=404)
        return JSONResponse({**row, "receipt_id": row.get("receipt") or None})

    @app.get("/api/agents")
    def agents() -> JSONResponse:
        """Agents with their authority state - the node's own payload, no second shape.

        Tokens appear only when ``WARRNT_DEV=1``, exactly as the node does it: a demo
        convenience so ``/mcp`` can be driven locally, never a production behaviour.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        return JSONResponse(k.agents(dev=config.dev()))

    @app.get("/api/warrants")
    def warrants() -> JSONResponse:
        """Signed orders with lifecycle state - the node's own payload, no second shape."""
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        return JSONResponse(k.warrants())

    @app.get("/api/state")
    def state_alias(limit: int = 60) -> JSONResponse:
        """Compatibility alias the Control Room page polls. The kernel's state, plus the mode.

        The page reads ``agents``, ``warrants``, ``receipts``, ``actions``, ``revoked`` and
        ``last_stop`` - all of them fields ``state()`` already returns, so the live feed is the
        real one and the demo feed is never what ``/api/*`` answers with.

        For the PROOF panel (F8) this also exposes the receipt chain and the per-action
        correlation - ``chain`` and ``proof`` - as pure projections of kernel state. Nothing
        here decides anything and nothing is invented: when the kernel cannot answer, the whole
        body is a 503 refusal, exactly like every other read.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        st = k.state(limit=limit)
        st["mode"] = config.mode()
        st["node"] = "TENET"
        # PROOF panel: the chain (ok / length / head / archive state) and the
        # run_id <-> action_id <-> receipt correlation, straight off the kernel.
        st["chain"] = k.chain()
        st["proof"] = k.proof(limit=limit)
        return JSONResponse(st)

    @app.get("/api/proof")
    def proof(limit: int = 60) -> JSONResponse:
        """The PROOF panel's projection, and nothing else.

        It **projects kernel state**: the receipt chain verdict and the per-action correlation
        ``run_id <-> action_id <-> receipt`` the UI's PROOF panel renders. It decides nothing and
        invents nothing - every id comes from a real action/receipt the kernel already holds.
        Unavailable kernel -> 503, never a synthesized body.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        return JSONResponse({"chain": k.chain(), **k.proof(limit=max(1, min(limit, 200))),
                             "mode": config.mode()})

    # ------------------------------------------------------- human-decision endpoints
    @app.post("/api/actions/{action_id}/approve")
    async def approve(action_id: str, request: Request,
                      x_warrnt_admin: str = Header(default="")) -> JSONResponse:
        return await _resolve(app, action_id, approve=True, request=request, token=x_warrnt_admin)

    @app.post("/api/actions/{action_id}/deny")
    async def deny(action_id: str, request: Request,
                   x_warrnt_admin: str = Header(default="")) -> JSONResponse:
        return await _resolve(app, action_id, approve=False, request=request, token=x_warrnt_admin)

    @app.post("/api/agents/{agent_id}/revoke")
    def revoke(agent_id: str, body: dict[str, Any] = Body(default={}),
               x_warrnt_admin: str = Header(default="")) -> JSONResponse:
        """Revoke an agent/authority. A thin wrapper over the one revoke path in the kernel.

        Same receipts, same state change - there is no second code path to drift (D3). The
        operator token is the kernel's own (``WARRNT_ADMIN_TOKEN``): an anonymous control plane
        is a control plane anyone can drive. The optional ``{"by": "name"}`` body names the
        person pulling the brake for the record; it changes no decision.
        """
        return _revoke(app, agent_id, x_warrnt_admin, str((body or {}).get("by") or "").strip())

    @app.post("/revoke", include_in_schema=False)
    def revoke_compat(body: dict[str, Any] = Body(default={}),
                      x_warrnt_admin: str = Header(default="")) -> JSONResponse:
        """Compatibility alias the Control Room page's kill button posts to.

        Same single revoke path as ``/api/agents/{id}/revoke`` - the page's ``{agent: id}``
        body is translated here and nothing else changes.
        """
        agent_id = str(body.get("agent") or "").strip()
        if not agent_id:
            return JSONResponse({"error": "agent is required", "field": "agent"}, status_code=422)
        return _revoke(app, agent_id, x_warrnt_admin, str(body.get("by") or "").strip())

    # ------------------------------------------------------------------- interception
    @app.post("/mcp")
    async def mcp(request: Request,
                  x_warrnt_agent: str = Header(default=""),
                  x_warrnt_token: str = Header(default=""),
                  x_warrnt_run: str = Header(default="")) -> JSONResponse:
        """Mirror of the node's ``/mcp`` tools/call interception, on the one process.

        This is how a call reaches the enforcement kernel in this deployment (contract TASK.1):
        the control plane does not decide. It hands the call to ``Kernel.intercept`` - the same
        gate, the same order, the same chain - and translates the verdict into the node's exact
        JSON-RPC shape, so the proof script can drive the whole vocabulary over HTTP through the
        one process instead of reaching around it. Unavailability is a refusal, never an allow.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        body = await _json_body(request)
        rpc_id = body.get("id")
        if body.get("method") != "tools/call":
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": -32601,
                                           "message": "only tools/call is intercepted"}})
        params = body.get("params") or {}
        tool = params.get("name")
        args = params.get("arguments") or {}
        if not tool:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": -32602, "message": "params.name required"}})

        try:
            decision, reason, detail, _receipt, executed = k.intercept(
                x_warrnt_agent, x_warrnt_token, tool, args, run_id=x_warrnt_run)
        except Exception:  # noqa: BLE001 - a kernel that cannot answer must fail closed
            return JSONResponse({"error": "enforcement kernel unavailable", "decision": "deny",
                                 "note": "the control plane refuses to decide on its own"},
                                status_code=503)

        word = decision.value if hasattr(decision, "value") else str(decision)

        if word in ("allow", "redact"):
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {
                "decision": word, "reason": reason, "executed": executed,
                "action_id": detail.get("action_id"), "receipt": detail.get("receipt"),
                "redacted": detail.get("redacted"),
                "upstream_params": detail.get("upstream_params"),
                **detail.get("result", {}),
            }})
        # Only refusals are errors. ``human`` is a held call: no upstream contact, and the
        # action_id it carries is what a named person decides.
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": {
            "code": {"deny": -32001, "human": -32002, "revoked": -32003}.get(word, -32000),
            "message": reason,
            "data": {"decision": word, "executed": executed, **detail},
        }})

    # ------------------------------------------------------------------- ask (agents)
    @app.post("/api/ask")
    async def ask(request: Request) -> JSONResponse:
        """Run the REAL orchestrator. The answer never authorizes anything.

        When the provider or the kernel is unavailable the body is a refusal carrying the
        kernel record as evidence - never an invented answer, never an allow (AC2/AC7).
        """
        from control_room.agents import answer as run_orchestrator

        body = await _json_body(request)
        question = str(body.get("q") or body.get("question") or "").strip()
        if not question:
            return JSONResponse({"error": "a question is required", "field": "q"},
                                status_code=422)
        k = app.state.kernel
        result = await run_orchestrator(question)
        run_id = result.run_id
        # Correlate the agent trace with a security trace without merging them (TASK.5):
        # the run record carries the action_id it referenced, if the answer named one.
        action_id = _referenced_action(result)
        app.state.runs[run_id] = {"run_id": run_id, "action_id": action_id,
                                  "question": question, "ts": __import__("time").time()}
        payload = {
            "run_id": run_id,
            "answer": result.answer,
            "evidence": [e.model_dump() for e in result.evidence],
            "specialists": result.specialists,
            "next_action": result.next_action,
            "action_id": action_id,
            "provider": config.PROVIDER,
            "model": config.MODEL,
            "kernel": "available" if k is not None else "unavailable",
        }
        return JSONResponse(payload)

    return app


def _referenced_action(result: Any) -> Optional[str]:
    """The action_id an answer cited, if any - taken from the real evidence, never invented."""
    for e in result.evidence:
        if getattr(e, "action_id", None):
            return e.action_id
        value = getattr(e, "value", None)
        if isinstance(value, str) and '"action_id"' in value:
            try:
                import json as _json

                parsed = _json.loads(value)
                if isinstance(parsed, dict) and parsed.get("action_id"):
                    return str(parsed["action_id"])
            except Exception:  # noqa: BLE001
                continue
    return None


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _require_admin(app: FastAPI, supplied: str) -> Optional[JSONResponse]:
    """401 unless the caller holds the operator token, exactly as the kernel's own node does.

    The token is the kernel's (``WARRNT_ADMIN_TOKEN``, stored on the kernel's settings); this
    layer never invents its own auth and never stores a second secret.
    """
    import hmac

    expected = getattr(app.state, "admin_token", "") or ""
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        return JSONResponse({"error": "operator token required",
                             "hint": "send the x-warrnt-admin header"}, status_code=401)
    return None


def _revoke(app: FastAPI, agent_id: str, supplied_token: str, by: str = "") -> JSONResponse:
    """The one revoke path: check the token, then delegate to the kernel. Nothing else.

    ``by`` names the person pulling the brake. It is optional (the kernel already privileges
    the admin token) and purely auditable: it never decides anything, it is echoed back so an
    external driver can record a named human, exactly as approve/deny already do.
    """
    denied = _require_admin(app, supplied_token)
    if denied:
        return denied
    k, unavailable = _kernel_or_503(app)
    if unavailable:
        return unavailable
    t0 = k.revoke(agent_id)
    if t0 is None:
        return JSONResponse({"error": "unknown agent or already halted", "agent": agent_id},
                            status_code=409)
    return JSONResponse({"agent": agent_id, "state": "halted", "by": by,
                         "warrant": k.proxy.agents[agent_id].warrant, "revoked_at": t0})



async def _resolve(app: FastAPI, action_id: str, *, approve: bool, request: Request,
                   token: str) -> JSONResponse:
    """Approve / deny a held action. The kernel runs the call; this layer only relays.

    Two things are required, and neither is optional: the operator token (an anonymous control
    plane is a control plane anyone can drive) and a named person (a human decision without a
    name on it is not a decision). Only then does the kernel run the held call.
    """
    from warrnt.controlplane import HoldRefused  # type: ignore import-not-found

    denied = _require_admin(app, token)
    if denied:
        return denied
    k, unavailable = _kernel_or_503(app)
    if unavailable:
        return unavailable
    body = await _json_body(request)
    by = str(body.get("by") or body.get("human") or "").strip()
    if not by:
        return JSONResponse({"error": "a named person is required", "field": "by"},
                            status_code=422)
    try:
        out = k.resolve_hold(action_id, approve, by)
    except HoldRefused as exc:
        return JSONResponse({"error": str(exc), "action_id": action_id}, status_code=409)
    except Exception:  # noqa: BLE001 - a kernel that cannot answer must fail closed
        return JSONResponse({"error": "enforcement kernel unavailable", "decision": "deny",
                             "note": "the control plane refuses to decide on its own",
                             "action_id": action_id}, status_code=503)
    action = out.get("action", {})
    return JSONResponse({
        "action_id": action_id,
        "state": action.get("state"),
        "decision": action.get("decision"),
        "receipt_id": action.get("receipt") or out.get("receipt"),
        "upstream_contacted": action.get("upstream_contacted"),
        "executed": out.get("executed"),
        "outcome": out.get("outcome"),
        "decided_by": action.get("decided_by"),
    })


app = create_app(seed=True)




INDEX_HTML = REPO_ROOT / "index.html"
