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
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import config
from .kernel import Kernel, KernelUnavailable, build_kernel, live_upstream_configured

REPO_ROOT = Path(__file__).resolve().parent.parent

# The Control Room page is the repository's existing dashboard; served here so the boundary
# from UI -> API is one origin. Reflex (control_room/) stays a separate, optional surface.

# --------------------------------------------------------------- ACT-5: the fixed scenario
# The one scenario the browser may trigger. These are CONSTANTS: the tool and its arguments
# are never read from the request body, so a caller cannot steer the crossing (AC3). The same
# fixed call backs the startup warm trace (AC4).
SELF_CHECK_AGENT = "fx-trader"
SELF_CHECK_TOOL = "fx.read_rate"
SELF_CHECK_ARGS: dict[str, str] = {"base": "EUR", "symbols": "USD"}
SELF_CHECK_RATE_LIMIT_S = 3.0
SELF_CHECK_RUN_PREFIX = "selfcheck-"
STARTUP_RUN_PREFIX = "startup-"
ORIGIN_SELF_CHECK = "operator self-check"
ORIGIN_STARTUP = "startup self-check"


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


def _run_fixed_scenario(kernel: Kernel, *, origin: str, run_prefix: str) -> Optional[str]:
    """Run the ONE fixed scenario through the kernel and return its ``action_id``.

    The agent token is read from the kernel's own registry **inside this process** - exactly
    as ``/api/demo/run`` does - so no credential ever reaches the browser and the page can
    never become a second authority. The tool and args are the module constants; the request
    body is never consulted (AC3). The kernel still makes the decision: this only asks it to
    intercept the call. The run id carries the caller's prefix, and the origin label (why this
    action exists) is journaled beside it. Returns ``None`` when there is no live warrant for
    the agent, so the caller reports that honestly rather than inventing a crossing.
    """
    tokens = {str(a.get("id")): str(a.get("token") or "") for a in kernel.agents(dev=True)}
    agent_token = tokens.get(SELF_CHECK_AGENT, "")
    if not agent_token:
        return None
    run_id = run_prefix + secrets.token_hex(4)
    _decision, _reason, detail, _receipt, _executed = kernel.intercept(
        SELF_CHECK_AGENT, agent_token, SELF_CHECK_TOOL, dict(SELF_CHECK_ARGS), run_id=run_id)
    action_id = str((detail or {}).get("action_id")
                    or ((detail or {}).get("action") or {}).get("id") or "")
    if action_id:
        kernel.record_origin(action_id, origin)
    return action_id or None


async def _warm_trace(app: FastAPI) -> None:
    """AC4 startup warm trace: fill an empty centre once, never block, never fabricate.

    Only when the kernel holds ZERO actions AND a live upstream is configured does the control
    plane run its own fixed boundary self-check, so the first screen after any deploy is not
    blank; the label states plainly that the control plane ran it. Idempotent by construction:
    an existing action makes this a no-op. A failure logs one line and never blocks startup.
    """
    kernel = getattr(app.state, "kernel", None)
    if kernel is None:
        return
    try:
        if not live_upstream_configured():
            return
        if kernel.actions(limit=1):
            return
        _run_fixed_scenario(kernel, origin=ORIGIN_STARTUP, run_prefix=STARTUP_RUN_PREFIX)
    except Exception as exc:  # noqa: BLE001 - warm-up must never block startup
        print(f"[tenet] startup warm trace skipped: {exc}", flush=True)


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
                # T1: register the warrants for the REAL Frankfurter upstream
                # (``fx.read_rate``) when this process was pointed at one. The kernel signs
                # them; the control plane only supplies the spec, and with no upstream
                # configured the call is a documented no-op.
                app.state.kernel.issue_live_warrants()
            except Exception:  # noqa: BLE001 - never block startup on a seed quirk
                pass
        # Hand the assistance surface the SAME kernel this process serves, so its read tools and
        # evidence floor answer in-process (no HTTP hop, no second instance, no second path).
        try:
            from control_room import agents as _assist

            _assist.bind_kernel(app.state.kernel)
        except Exception:  # noqa: BLE001 - the surface degrades to HTTP reads, never to a crash
            pass
        # AC4: the first screen after any deploy must not be blank. Only an EMPTY kernel with a
        # live upstream triggers this one-time, plainly-labelled self-check; a failure never
        # blocks startup (the helper swallows and logs).
        await _warm_trace(app)
        yield

    app = FastAPI(title="TENET Control Plane", version="0.1.0", lifespan=lifespan)
    app.state.kernel = kernel
    app.state.identity = identity
    app.state.runs = {}          # run_id -> {run_id, action_id, question, ts}
    app.state.self_check_last = 0.0   # ACT-5: monotonic ts of the last operator self-check

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

    @app.get("/onboarding", response_class=HTMLResponse, include_in_schema=False)
    def onboarding() -> HTMLResponse:
        """The voice-guided walkthrough: the guide moves with the operator through the flow."""
        if not ONBOARDING_HTML.exists():
            return HTMLResponse("<h1>TENET</h1><p>Guided walkthrough page missing</p>", status_code=500)
        return HTMLResponse(ONBOARDING_HTML.read_text(encoding="utf-8"))

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
            # The live upstream the kernel may reach. ``absent`` is honest: with none configured
            # no call can cross, and the canonical scenario says so instead of inventing a rate.
            "live_upstream": "configured" if live_upstream_configured() else "absent",
        }
    # ------------------------------------------------------------------- kernel reads
    @app.get("/api/overview")
    def overview() -> JSONResponse:
        """Counters + authority summary + mode, one payload - all projections of state.

        The counts come from ``kernel.read`` (the single read implementation the specialist
        tools also use), so the operator's UI and an agent's tool can never see two different
        numbers. With no data the lists are empty, never seeded (contract TASK.6).

        ``upstream_configured`` is a read-only projection of the SAME predicate the demo route
        uses to refuse (``live_upstream_configured``). The page must label its action card LIVE
        or SIMULATED from a real deployment fact, never from a constant: it is ``true`` only when
        this process was pointed at a real MCP upstream, so a crossing it shows is a real one.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        return JSONResponse({**k.read("/api/overview"), "mode": config.mode(),
                             "upstream_configured": live_upstream_configured()})

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

    # --------------------------------------------------- one canonical chain per run (T9/§9)
    @app.get("/api/proof/{run_id}")
    def proof_for_run(run_id: str) -> JSONResponse:
        """The canonical chain for ONE run, assembled only from records that already exist.

        Read-only by construction: it reads the kernel's own actions for this ``run_id``, their
        receipts, the upstream's journal and the provider's event journal. It never calls the
        provider, never infers a missing id and never creates evidence. A chain with a hole is
        reported ``INCOMPLETE`` with the missing steps named; a contradiction - a denial that
        still contacted the upstream - is reported ``FAIL``. Neither is rounded up (D12).
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        assert k is not None  # _kernel_or_503 guarantees a kernel past its 503 branch
        from control_room import provider as provider_module  # local: not on any decision path

        rows = [a for a in k.actions(limit=200) if str(a.get("run_id") or "") == run_id]
        events = provider_module.read_events(run_id=run_id)
        started = [e for e in events if e.get("event") == "deepseek.request.started"]
        completed = [e for e in events if e.get("event") == "deepseek.request.completed"]
        failed = [e for e in events if e.get("event") == "deepseek.request.failed"]
        upstream = k.upstream_log(limit=200)
        journal = upstream.get("entries") or []
        actions: list[dict[str, Any]] = []
        for row in rows:
            action_id = str(row.get("action_id") or "")
            record = k.action(action_id) if action_id else None
            record = record if isinstance(record, dict) else {}
            crossing = record.get("execution_result") or {}
            receipt = row.get("receipt") or (record.get("receipt") or {}).get("id")
            decision = str(row.get("decision") or "")
            attempts = record.get("boundary_attempts")
            if attempts is None:
                attempts = (record.get("receipt") or {}).get("boundary_attempts")
            actions.append({
                "action_id": action_id,
                "agent": row.get("agent"),
                "tool": row.get("tool"),
                "action_class": row.get("action_class"),
                "authority": {"warrant": row.get("warrant"), "warrant_state": row.get("warrant_state"),
                              "policy_result": row.get("policy_result"),
                              "entitlement": row.get("entitlement") or crossing.get("entitlement")},
                "proposal_source": row.get("proposal_source") or "deepseek",
                "decision": {"decision": decision, "reason": row.get("reason"),
                             "decided_by": "tenet-kernel", "state": row.get("state")},
                "execution": {"upstream_contacted": bool(row.get("upstream_contacted")
                                                         or crossing.get("http_status")),
                              "boundary_attempts": attempts,
                              "http_status": crossing.get("http_status"),
                              "upstream": crossing.get("upstream") or crossing.get("url")},
                "receipt": {"receipt_id": receipt},
                "upstream_journal_calls": [e for e in journal
                                           if str(e.get("call_id") or "") == action_id],
            })
        missing: list[str] = []
        if started and not completed:
            missing.append("llm.call response (the provider call did not complete)")
        if not actions:
            missing.append("action")
        for a in actions:
            if not a["decision"]["decision"]:
                missing.append("decision")
            elif a["decision"]["decision"] in ("allow", "redact"):
                if not a["receipt"]["receipt_id"]:
                    missing.append("receipt")
                if not a["execution"]["upstream_contacted"]:
                    missing.append("upstream contact for a permitted call")
        violations = [a["action_id"] for a in actions
                      if a["decision"]["decision"] == "deny" and a["execution"]["boundary_attempts"]]
        status = "FAIL" if violations else ("COMPLETE" if not missing else "INCOMPLETE")
        return JSONResponse({
            "run_id": run_id,
            "status": status,
            "missing": sorted(set(missing)),
            "llm_authority": False,
            "authority_source": "tenet-kernel",
            "orchestration": {
                "provider": "deepseek",
                "base_url": provider_module.BASE_URL,
                "model_requested": provider_module.MODEL,
                "model_served": sorted({e.get("model_served") for e in completed
                                        if e.get("model_served")}),
                "calls_started": len(started),
                "calls_completed": len(completed),
                "calls_failed": len(failed),
                "llm_request_ids": [e.get("request_id") for e in completed if e.get("request_id")],
                "input_tokens": sum(int(e.get("input_tokens") or 0) for e in completed),
                "output_tokens": sum(int(e.get("output_tokens") or 0) for e in completed),
                "max_latency_ms": max([int(e.get("latency_ms") or 0) for e in completed] or [0]),
            },
            "agents": sorted({str(a.get("agent") or "") for a in actions if a.get("agent")}),
            "actions": actions,
            "provider_events": events,
            "upstream": {"path": upstream.get("path"), "exists": upstream.get("exists"),
                         "sha256": upstream.get("sha256"), "total": upstream.get("total")},
        })

    # ------------------------------------------- ACT-4: the security-decision projection
    @app.get("/api/model-usage")
    def model_usage() -> JSONResponse:
        """Read-only provider resource usage for the Control Room.

        This is evidence from the persisted DeepSeek event journal, not a second execution
        path. It reports which model actually answered, call count, tokens and latency; it
        never exposes credentials, prompts or response bodies.
        """
        try:
            from control_room import provider as provider_module
            events = provider_module.read_events()
        except Exception:  # noqa: BLE001
            events = []
        completed = [e for e in events if e.get("event") == "deepseek.request.completed"]
        started = [e for e in events if e.get("event") == "deepseek.request.started"]
        failed = [e for e in events if e.get("event") == "deepseek.request.failed"]
        latest = completed[-1] if completed else (failed[-1] if failed else None)
        input_tokens = sum(int(e.get("input_tokens") or 0) for e in completed)
        output_tokens = sum(int(e.get("output_tokens") or 0) for e in completed)
        total_tokens = sum(int(e.get("total_tokens") or 0) for e in completed)
        latency = [int(e.get("latency_ms") or 0) for e in completed]
        return JSONResponse({
            "provider": "deepseek",
            "model_requested": provider_module.MODEL,
            "model_served": (latest or {}).get("model_served"),
            "calls_started": len(started),
            "calls_completed": len(completed),
            "calls_failed": len(failed),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "max_latency_ms": max(latency) if latency else None,
            "latest_trace_id": (latest or {}).get("request_id"),
            "latest_status": (latest or {}).get("status"),
            "evidence": "persisted DeepSeek provider events",
            "mode": config.mode(),
        })

    @app.get("/api/security-events")
    def security_events(limit: int = 60) -> JSONResponse:
        """The security-decision feed the Control Room's first screen renders (ACT-4 slice A).

        A read-only projection of kernel state (actions + receipts) joined with the persisted
        provider evidence, so the operator can see, per action, what the agent tried to do, the
        kernel's verdict and whether data actually left the boundary. It decides nothing, and
        ``llm_authority`` is always ``false`` - the model trace is evidence, never a permission.
        Unknown fields are ``null``, never a default that reads as success. Unavailable kernel
        -> 503, the same refusal body every other read returns.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        body = k.security_events(limit=max(1, min(limit, 200)))
        return JSONResponse({**body, "mode": config.mode()})

    @app.get("/api/security-events/{run_id}")
    def security_event(run_id: str) -> JSONResponse:
        """One run's ``SecurityEvent``s plus the causal graph ``run_id → model_trace_id →
        action_id → decision → upstream_call_id → receipt_id`` (``docs/act-3-causal-graph.md``).

        The chain is evidence, not authority: the kernel's decision is the only place authority
        lives, and ``upstream_call_id`` is ``null`` until slice B mints it at the boundary -
        ``action_id`` is never relabelled as a call id. A partial chain is reported ``INCOMPLETE``
        with the missing nodes named, never rounded up. Unknown run -> 404; unavailable kernel
        -> 503, the same refusal body as every other read.
        """
        k, denied = _kernel_or_503(app)
        if denied:
            return denied
        body = k.security_event(run_id)
        if body is None:
            return JSONResponse({"error": f"unknown run {run_id}",
                                 "hint": "GET /api/security-events lists the runs"}, status_code=404)
        return JSONResponse({**body, "mode": config.mode()})

    # ---------------------------------------------------------- ACT-5: the live security trace
    @app.get("/api/live-trace")
    def live_trace(action_id: Optional[str] = None) -> JSONResponse:
        """The Control Room's centre: one real action composed with its authority evidence.

        Read-only and credential-free - the page polls it, and it exposes no token. ``trace`` is
        ``null`` when the kernel holds no action at all: the honest empty state, never a
        fabricated event. Every field is authority-neutral (``authority_source: "tenet-kernel"``,
        ``llm_authority: false``) and every field whose evidence is missing is ``null`` and named
        in ``trace.incomplete``. Unavailable kernel -> 503, the same refusal body as every read.

        ``action_id`` is an OPTIONAL, read-only query parameter (ACT-6 AC1). It is a read, not a
        contract change: it reuses the kernel's one composer, so the body shape is identical to
        the parameterless call. Omitted, the LAST real action is returned, exactly as before.
        An ``action_id`` the ledger does not hold is answered with the route's existing refusal
        body (the same shape ``GET /api/actions/{action_id}`` uses), never a fabricated trace.
        """
        k, unavailable = _kernel_or_503(app)
        if unavailable:
            return unavailable
        assert k is not None
        if action_id:
            composed = k.live_trace(action_id)
            if composed is None:
                return JSONResponse({"error": f"unknown action {action_id}",
                                     "hint": "GET /api/actions lists the ledger"}, status_code=404)
            return JSONResponse({
                "trace": composed,
                "authority_source": "tenet-kernel",
                "llm_authority": False,
                "mode": config.mode(),
            })
        return JSONResponse({
            "trace": k.live_trace(),
            "authority_source": "tenet-kernel",
            "llm_authority": False,
            "mode": config.mode(),
        })

    @app.post("/api/scenario/self-check")
    def scenario_self_check() -> JSONResponse:
        """The browser's ONLY trigger: run the fixed scenario, no credential, return the trace.

        Exactly the AC3 contract: the fixed ``fx-trader`` / ``fx.read_rate`` / EUR->USD call (the
        tool and args are server constants, never read from the request body), the agent token
        read in-process from the kernel registry as ``/api/demo/run`` does, a REAL crossing, then
        the AC1 ``trace`` object. At most one run per ``SELF_CHECK_RATE_LIMIT_S`` -> 429 with
        ``retry_after_s``; no live upstream -> 503 and NO record written. The run id is prefixed
        ``selfcheck-`` and the action metadata carries ``origin: "operator self-check"``.
        """
        k, unavailable = _kernel_or_503(app)
        if unavailable:
            return unavailable
        assert k is not None
        if not live_upstream_configured():
            return JSONResponse({"error": "no upstream configured"}, status_code=503)
        now = time.monotonic()
        elapsed = now - float(getattr(app.state, "self_check_last", 0.0) or 0.0)
        if elapsed < SELF_CHECK_RATE_LIMIT_S:
            retry_after = max(1, int(round(SELF_CHECK_RATE_LIMIT_S - elapsed)))
            return JSONResponse({"error": "rate limited", "retry_after_s": retry_after},
                                status_code=429)
        # Claim the slot BEFORE the crossing: two concurrent callers must not both run.
        app.state.self_check_last = now
        action_id = _run_fixed_scenario(k, origin=ORIGIN_SELF_CHECK,
                                        run_prefix=SELF_CHECK_RUN_PREFIX)
        if not action_id:
            return JSONResponse({"error": "no live warrant for this agent",
                                 "agent": SELF_CHECK_AGENT, "decision": "deny"}, status_code=409)
        return JSONResponse({
            "trace": k.live_trace(),
            "authority_source": "tenet-kernel",
            "llm_authority": False,
            "mode": config.mode(),
        })

    # ------------------------------------------- ACT-2 §4: proof of non-contact (evidence)
    @app.get("/api/upstream/log")
    def upstream_log(limit: int = 200, tool: str = "",
                     x_warrnt_admin: str = Header(default="")) -> JSONResponse:
        """The real upstream's own access log, as the kernel read it (ACT-2 §4).

        Operator-authenticated (the log names callers) and projected through the kernel's one
        implementation of the read, so this route and the node's cannot show different logs.
        ``exists: false`` when no log is configured - never a fake empty proof (D12).
        """
        denied = _require_admin(app, x_warrnt_admin)
        if denied:
            return denied
        k, unavailable = _kernel_or_503(app)
        if unavailable:
            return unavailable
        return JSONResponse(k.upstream_log(limit=max(0, min(limit, 500)), tool=tool))

    @app.post("/api/attest/non-contact")
    def attest_non_contact(body: dict[str, Any] = Body(default={}),
                           x_warrnt_admin: str = Header(default="")) -> JSONResponse:
        """Prove, from the record, that an action did NOT contact the upstream (ACT-2 §4).

        The attestation is assembled by the kernel from facts it already holds - the action's
        ``upstream_contacted`` flag, its ``boundary_attempts`` counter, and the upstream's own
        access log. 409 the moment either side shows contact; 404 for an unknown action. The
        control plane decides nothing here: it relays the kernel's verdict and its status.
        """
        denied = _require_admin(app, x_warrnt_admin)
        if denied:
            return denied
        k, unavailable = _kernel_or_503(app)
        if unavailable:
            return unavailable
        action_id = str((body or {}).get("action_id") or "").strip()
        out = dict(k.attest_non_contact(action_id))
        status = int(out.pop("status", 200))
        return JSONResponse(out, status_code=status)

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
        is a control plane anyone can drive. The ``{"by": "name"}`` body names the person
        pulling the brake, exactly as approve/deny require: a human decision without a name on
        it is not a decision, so an unattributed halt is refused (422), never committed.
        """
        return _revoke(app, agent_id, x_warrnt_admin, str((body or {}).get("by") or "").strip())

    @app.post("/revoke", include_in_schema=False)
    def revoke_compat(body: dict[str, Any] = Body(default={}),
                      x_warrnt_admin: str = Header(default="")) -> JSONResponse:
        """Compatibility alias the Control Room page's kill button posts to.

        Same single revoke path as ``/api/agents/{id}/revoke`` - the page's ``{agent: id}``
        body is translated here and nothing else changes. It carries the same named-person
        requirement as the canonical route.
        """
        agent_id = str(body.get("agent") or "").strip()
        if not agent_id:
            return JSONResponse({"error": "agent is required", "field": "agent"}, status_code=422)
        return _revoke(app, agent_id, x_warrnt_admin, str(body.get("by") or "").strip())

    # ------------------------------------------- the canonical live scenario (operator only)
    @app.post("/api/demo/run")
    async def demo_run(request: Request,
                       x_warrnt_admin: str = Header(default="")) -> JSONResponse:
        """Run the one canonical scenario server-side and return its evidence.

        Why this route exists: the Control Room's first screen must show a REAL crossing, and
        the operator must be able to trigger it **without a credential ever reaching the
        browser**. The agent token is read from the kernel's own registry inside this process
        and used here, so the page can never become a second authority and can never leak a
        token. The decision is still the kernel's - this route only asks it to intercept the
        call, exactly as ``/mcp`` does. No upstream configured -> 503, never a faked crossing.
        """
        denied = _require_admin(app, x_warrnt_admin)
        if denied:
            return denied
        k, unavailable = _kernel_or_503(app)
        if unavailable:
            return unavailable
        assert k is not None  # _kernel_or_503 guarantees a kernel past its 503 branch
        if not live_upstream_configured():
            return JSONResponse(
                {"error": "no live upstream configured", "decision": "deny",
                 "note": "point WARRNT_UPSTREAM at the real tool server - TENET never fakes a crossing"},
                status_code=503)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - an empty body IS the canonical scenario
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        agent_id = str(payload.get("agent") or "fx-trader")
        args = {"base": str(payload.get("base") or "EUR"),
                "symbols": str(payload.get("symbols") or "USD")}
        tokens = {str(a.get("id")): str(a.get("token") or "") for a in k.agents(dev=True)}
        agent_token = tokens.get(agent_id, "")
        if not agent_token:
            return JSONResponse({"error": "no live warrant for this agent", "agent": agent_id,
                                 "decision": "deny"}, status_code=409)
        run_id = "demo-" + secrets.token_hex(4)
        decision, reason, detail, _receipt, executed = k.intercept(
            agent_id, agent_token, "fx.read_rate", args, run_id=run_id)
        word = decision.value if hasattr(decision, "value") else str(decision)
        action_id = str((detail or {}).get("action_id")
                        or ((detail or {}).get("action") or {}).get("id") or "")
        record = k.action(action_id) if action_id else None
        record = record if isinstance(record, dict) else {}
        crossing = record.get("execution_result") or {}
        # "Contacted" means the upstream answered with an HTTP status. A permitted call whose
        # transport failed (dead host, refused connection) leaves no status behind, and
        # reporting that as a crossing would be exactly the kind of claim this product forbids.
        contacted = bool(crossing.get("http_status")) and word in ("allow", "redact")
        return JSONResponse({
            "scenario": "fx.read_rate",
            "agent": agent_id,
            "run_id": run_id,
            "action_id": action_id,
            "decision": word,
            "reason": reason,
            "executed": executed,
            "upstream_contacted": contacted,
            "execution_result": crossing,
            "receipt": record.get("receipt") or (detail or {}).get("receipt"),
            "tool": "fx.read_rate",
        })

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
        from control_room.agents import action_for_run
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
        # The run's OWN action first: a run that proposed a call is about that call, and the
        # payload must not name the state the run read before proposing (found live: the answer
        # was about A-0002 while the payload named A-0001).
        action_id = action_for_run(run_id) or _referenced_action(result)
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
    """The action_id an answer cited - the NEWEST one - taken from the real evidence.

    An answer about a call it just proposed also cites the state it read before proposing, so
    both ids appear. Returning the older one for the newer call is a one-field lie a reader
    sees immediately; the newest cited id wins. Nothing is invented: only ids the evidence
    actually carries are considered.
    """
    found: list[str] = []

    def _take(candidate: Any) -> None:
        text = str(candidate or "").strip()
        if text:
            found.append(text)

    for e in result.evidence:
        _take(getattr(e, "action_id", None))
        value = getattr(e, "value", None)
        if isinstance(value, str) and '"action_id"' in value:
            try:
                import json as _json

                parsed = _json.loads(value)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(parsed, dict):
                _take(parsed.get("action_id"))
                rows = parsed.get("actions")
                if isinstance(rows, list) and rows and isinstance(rows[-1], dict):
                    _take(rows[-1].get("action_id"))

    def _rank(action_id: str) -> tuple[int, str]:
        digits = "".join(ch for ch in action_id if ch.isdigit())
        return (int(digits) if digits else -1, action_id)

    return max(found, key=_rank) if found else None


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
    """The one revoke path: check the token, require a name, then delegate to the kernel.

    Two things are required, exactly as approve/deny require them: the operator token (an
    anonymous control plane is a control plane anyone can drive) and a named person (a human
    decision without a name on it is not a decision). ``by`` names the person pulling the
    brake; the halt is a control decision like any other, so an empty ``by`` is refused with
    the same 422 the approve door uses - before the kernel runs, so no revoke is committed and
    no receipt is created for an unattributed halt.
    """
    denied = _require_admin(app, supplied_token)
    if denied:
        return denied
    k, unavailable = _kernel_or_503(app)
    if unavailable:
        return unavailable
    if not by:
        return JSONResponse({"error": "a named person is required", "field": "by"},
                            status_code=422)
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
    from control_plane.kernel import SeparationOfDutiesRefused
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
    except SeparationOfDutiesRefused as exc:
        # ACT-2 §3: the requester may not approve their own hold. A distinct refusal with its
        # own marker, so a caller can tell "you may not decide this" from "this hold is gone".
        # The kernel records the refusal before it raises (a denial is itself an event, D5).
        return JSONResponse({"error": str(exc), "action_id": action_id,
                             "refused": "separation_of_duties"}, status_code=409)
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
ONBOARDING_HTML = REPO_ROOT / "onboarding.html"
