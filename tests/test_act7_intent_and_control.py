"""ACT-7 vertical slice #1 - the intent entry and the real human control, proven by a REAL render.

The contract (section 3) puts the smallest complete end-user journey on top of machinery that
already exists::

    user intent -> real model proposal -> real kernel decision
    -> ALLOW / DENY / HOLD -> real upstream contact or none -> receipt
    -> real human control (Approve / Deny / Revoke)

Every state asserted here is a verdict the kernel really produced; nothing in this file invents a
lifecycle. The tests are written the way section 4 demands: each one FAILS before the change and
PASSES after, and none of them asserts "an element exists" where the product meaning requires the
selected action to actually be displayed. They read the RENDERED DOM (chromium ``--dump-dom``),
exactly as ``tests/test_control_room_experience.py`` does, because a source-reading test is what
let round 1 ship a page whose prose promised evidence it never rendered.

Two layers, one harness:

  * a stdlib HTTP server serves ``index.html`` plus canned ``/api/*`` bodies and RECORDS every
    request the page makes (method, path, headers, body), so a test can assert on what the page
    actually POSTed - never on what the source says it should;
  * a driver script (served only to the test browser, never present in the repo's ``index.html``)
    performs the interaction a person would: type an intent, press the button, choose who acts,
    press Approve / Deny.

T1 .. T6 map one-to-one onto section 4. When chromium is absent each test SKIPS with a clear
reason and claims no pass it did not earn.
"""
from __future__ import annotations

import http.server
import json
import re
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
CHROMIUM = shutil.which("chromium") or (
    "/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None)


# ------------------------------------------------------------------ canned kernel-shaped payloads
# The action ids are the kernel's own shapes (docs/tenet-happy-path-evidence.json): the ALLOW leg
# is ``fx-trader`` on ``fx.read_rate``; the DENY leg is ``support-copilot``; the HOLD leg is
# ``fx-auditor`` (W-9003, ``fx.read_rate => require-human``). Same resource, three verdicts.
ALLOW_ACTION_ID = "A-0002"
DENY_ACTION_ID = "A-0003"
HOLD_ACTION_ID = "A-0004"

_ALLOW_TRACE = {
    "agent": "fx-trader",
    "action": {"tool": "fx.read_rate", "class": "read_market_data", "intent": "read the EUR/USD rate",
               "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "allow",
    "reason": "read-only \u00b7 live reference rate \u00b7 in scope \u00b7 class observe",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "fx-trader"},
               "entitlement": {"ok": True, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9001", "state": "active", "sig_ok": True, "ttl_remaining": 3488},
               "policy": {"ok": True, "detail": "order ok \u00b7 class observe"}},
    "upstream": {"contacted": True, "http_status": 200,
                 "endpoint": "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD",
                 "value": {"EUR": 1.0, "USD": 1.1225},
                 "response_sha256": "f63f64a5e9b3584bd32e0ea70927ea574bea7ef3", "latency_ms": 22.78},
    "receipt_id": "1fbb161d",
    "action_id": ALLOW_ACTION_ID,
    "principal": "desk-operator", "on_behalf_of": "treasury",
    "timestamp": 1759420000, "origin": "operator self-check", "incomplete": [],
}
_DENY_TRACE = {
    "agent": "support-copilot",
    "action": {"tool": "fx.read_rate", "class": "read_market_data", "intent": "read the EUR/USD rate",
               "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "deny",
    "reason": "no entitlement to market_data.fx.read",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "support-copilot"},
               "entitlement": {"ok": False, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9002", "state": "active", "sig_ok": True, "ttl_remaining": 120},
               "policy": {"ok": False, "detail": "no entitlement"}},
    "upstream": {"contacted": False, "http_status": None, "endpoint": None, "value": None,
                 "response_sha256": None, "latency_ms": None},
    "receipt_id": "bfc7eacc",
    "action_id": DENY_ACTION_ID,
    "principal": "support-ops", "on_behalf_of": "service-desk",
    "timestamp": 1759420001, "origin": "agent call", "incomplete": [],
}

_HOLD_TRACE = {
    "agent": "fx-auditor",
    "action": {"tool": "fx.read_rate", "class": "read_market_data", "intent": "read the EUR/USD rate",
               "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "human",
    "reason": "this order prices a live read with a person's decision \u00b7 class observe",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "fx-auditor"},
               "entitlement": {"ok": True, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9003", "state": "active", "sig_ok": True, "ttl_remaining": 1800},
               "policy": {"ok": True, "detail": "order ok \u00b7 require-human"}},
    "upstream": {"contacted": False, "http_status": None, "endpoint": None, "value": None,
                 "response_sha256": None, "latency_ms": None},
    "receipt_id": "9c0ffee0",
    "action_id": HOLD_ACTION_ID,
    "principal": "risk-office", "on_behalf_of": "compliance",
    "timestamp": 1759420002, "origin": "operator self-check", "incomplete": [],
}


def _feed_event(trace):
    """The ``/api/security-events`` row for a trace - ``event_id`` is the action id."""
    action = trace["action"]
    return {"event_id": trace["action_id"], "run_id": trace["action_id"], "agent": trace["agent"],
            "actor": trace["agent"], "intent": action["intent"], "resource": action["tool"],
            "tool": action["tool"], "action_class": action.get("class"),
            "warrant": trace["checks"]["warrant"]["id"], "warrant_state": trace["checks"]["warrant"]["state"],
            "policy": trace["checks"]["policy"]["detail"], "decision": trace["decision"],
            "state": "pending" if trace["decision"] == "human" else "decided", "reason": trace["reason"],
            "upstream_contacted": trace["upstream"]["contacted"], "upstream_call_id": None,
            "execution_result": trace["upstream"] if trace["upstream"]["contacted"] else None,
            "receipt_id": trace["receipt_id"], "model_trace_id": None, "model_requested": None,
            "model_served": None, "boundary_attempts": 0, "authority_source": "tenet-kernel",
            "llm_authority": False, "timestamp": trace["timestamp"]}


# ------------------------------------------------------------------------------- the test harness
class _Recorder:
    """Every request the page makes, in order - what the page ACTUALLY sent, not what it should."""

    def __init__(self):
        self.calls = []  # list of {"method", "path", "query", "headers", "body"}

    def record(self, method, path, query, headers, body):
        self.calls.append({"method": method, "path": path, "query": query,
                           "headers": {k.lower(): v for k, v in dict(headers).items()},
                           "body": body})

    def posted(self, path_prefix):
        return [c for c in self.calls
                if c["method"] == "POST" and c["path"].startswith(path_prefix)]


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serve ``index.html`` at ``/`` plus the canned API bodies; record every request.

    ``do_POST`` is the whole point: the page's intent box, its who-acts selector and its
    Approve/Deny buttons all speak over POST, and a test may only assert on the bytes the page
    sent. Everything else is a 404.
    """

    def _dispatch(self, method):
        parsed = urllib.parse.urlparse(self.path)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = raw.decode("utf-8") if raw else ""
        # Expose the parsed request so a payload fn can branch on it without re-reading the stream.
        self.query = query
        self.body = body
        self.server.recorder.record(method, parsed.path, query, self.headers, body)

        payloads = self.server.payloads
        if parsed.path in ("/", "/index.html") and method == "GET":
            out = (PAGE + payloads.get("__driver__", "")).encode("utf-8")
            status, ctype = 200, "text/html; charset=utf-8"
        elif parsed.path in [k for k in payloads if not k.startswith("__")]:
            data = dict(payloads[parsed.path](self))
            status = int(data.pop("__status__", 200))
            out = json.dumps(data).encode("utf-8")
            ctype = "application/json"
        elif re.fullmatch(r"/api/actions/[^/]+", parsed.path):
            data = dict(payloads["__action_detail__"](self))
            status = int(data.pop("__status__", 200))
            out = json.dumps(data).encode("utf-8")
            ctype = "application/json"
        elif re.fullmatch(r"/api/actions/[^/]+/(approve|deny|revoke)", parsed.path):
            data = dict(payloads["__action_control__"](self))
            status = int(data.pop("__status__", 200))
            out = json.dumps(data).encode("utf-8")
            ctype = "application/json"
        elif re.fullmatch(r"/api/agents/[^/]+/revoke", parsed.path):
            data = dict(payloads["__agent_revoke__"](self))
            status = int(data.pop("__status__", 200))
            out = json.dumps(data).encode("utf-8")
            ctype = "application/json"
        else:
            out, status, ctype = b"{}", 404, "application/json"
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def log_message(self, *_args):  # keep pytest output clean
        return


class _Served:
    """A real HTTP server on a free port; torn down afterwards. Nothing external is needed."""

    def __init__(self, payloads):
        self._payloads = payloads
        self.recorder = _Recorder()
        self._server = None
        self._thread = None

    def __enter__(self):
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.payloads = self._payloads
        self._server.recorder = self.recorder
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return "http://127.0.0.1:%d/" % self._server.server_address[1]

    def __exit__(self, *_exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _rendered_dom(url):
    """The DOM chromium produces after the page's own JS (and the driver) have run."""
    if CHROMIUM is None:
        pytest.skip("chromium is absent; the ACT-7 render cannot be performed (no pass claimed)")
    proc = subprocess.run(
        [CHROMIUM, "--headless", "--no-sandbox", "--disable-gpu",
         "--virtual-time-budget=9000", "--dump-dom", url],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, "chromium exited %d: %s" % (proc.returncode, proc.stderr[:400])
    return proc.stdout


def _text(dom, element_id):
    """Visible text inside the element with ``id``, tags stripped and whitespace collapsed.

    The scan is depth-aware (not a lazy ``.*?</``) so a container with nested elements is captured
    whole - the action card wraps ``div``/``span`` and a lazy match would stop at the first close.
    """
    start = re.search(r'<[^>]+id="%s"[^>]*>' % re.escape(element_id), dom)
    if not start:
        return ""
    inner = start.end()
    depth, pos = 1, inner
    for tag in re.finditer(r"<(/?)(\w+)([^>]*)>", dom[inner:]):
        if tag.group(2).lower() in ("br", "img", "input", "meta", "link", "hr"):
            continue
        depth += -1 if tag.group(1) == "/" else 1
        if depth == 0:
            pos = inner + tag.start()
            break
    text = re.sub(r"<[^>]+>", " ", dom[inner:pos])
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def _probe(dom, key):
    """A value the driver wrote into ``#probe`` as JSON - the page's own record of what it did."""
    raw = _text(dom, "probe")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data.get(key) if isinstance(data, dict) else None


# ------------------------------------------------------------------------------ payload builders
_ASK_DEGRADED = {
    "run_id": "run-noprop",
    "answer": ("Refusal: the agentic surface is DEGRADED (provider key ABSENT). No model call was "
               "made. The kernel record is attached as evidence and remains the only authority - "
               "nothing was authorized by this answer."),
    "evidence": [{"source": "/api/actions", "claim": "record",
                  "value": "no action in the record", "action_id": None}],
    "specialists": [], "next_action": "retry when provider available",
    "action_id": None, "provider": "deepseek", "model": "deepseek-chat", "kernel": "available",
}


def _proposal_evidence(trace):
    """The propose_action verdict as it arrives inside /api/ask evidence (agents.py:157)."""
    verdict = {"submitted": True, "proposed_by": "deepseek", "authority": "tenet-kernel",
               "llm_authority": False, "agent": trace["agent"], "tool": "fx.read_rate",
               "resource": "fx.read_rate", "run_id": "run-1", "action_id": trace["action_id"],
               "decision": trace["decision"], "reason": trace["reason"],
               "executed": trace["upstream"]["contacted"],
               "upstream_contacted": trace["upstream"]["contacted"], "receipt": None, "rationale": ""}
    return {"source": "propose_action", "claim": "verdict", "value": json.dumps(verdict),
            "action_id": trace["action_id"]}


def _ask_with_proposal(trace):
    return {"run_id": "run-1",
            "answer": ("The kernel decided %s for %s on fx.read_rate. Reason: %s. This is a "
                       "proposal report - the model holds no authority; the kernel is the only "
                       "authority." % (trace["decision"], trace["agent"], trace["reason"])),
            "evidence": [_proposal_evidence(trace)],
            "specialists": ["Governance Agent", "Kernel Agent", "Control-Plane Agent"],
            "next_action": "watch the action card", "action_id": trace["action_id"],
            "provider": "deepseek", "model": "deepseek-chat", "kernel": "available"}


def _base_payloads(events=None, ask_body=None, pending=None, state=None, live_trace_body=None):
    """The canned API surface the page reads. Every response carries the authority facts.

    ``state`` is a mutable dict a test can seed (e.g. ``{"held": True}``) so the resolve routes
    behave like the real control plane: a token-less Approve does not move a held action, a token
    present moves it and the action detail then reports the new state. ``live_trace_body`` overrides
    the top-level ``/api/live-trace`` trace (the one the overview card paints from) so a test can
    exercise a specific record shape without an ``action_id`` query.
    """
    state = state if state is not None else {}
    by_id = {ALLOW_ACTION_ID: _ALLOW_TRACE, DENY_ACTION_ID: _DENY_TRACE, HOLD_ACTION_ID: _HOLD_TRACE}

    def live_trace(req):
        action_id = (req.query or {}).get("action_id")
        return {"trace": by_id.get(action_id) if action_id else (live_trace_body or _ALLOW_TRACE),
                "authority_source": "tenet-kernel", "llm_authority": False, "mode": "live"}

    def ask(_req):
        return ask_body if ask_body is not None else _ASK_DEGRADED

    def demo_run(req):
        # The real route is admin-gated (app.py:691, _require_admin); the harness mirrors that only
        # when a test asks for it (``state["demo_requires_admin"]``), so the ordinary HOLD/ALLOW
        # rendering can be exercised without a token while the credential rule still gets a test.
        if state.get("demo_requires_admin"):
            lower = {k.lower() for k in req.headers.keys()}
            if "x-warrnt-admin" not in lower and "authorization" not in lower:
                return {"__status__": 401, "error": "missing operator token",
                        "agent": None, "decision": None}
        raw = req.body or ""
        try:
            wanted = (json.loads(raw) if raw else {}).get("agent", "fx-trader")
        except ValueError:
            wanted = "fx-trader"
        trace = {"fx-trader": _ALLOW_TRACE, "support-copilot": _DENY_TRACE,
                 "fx-auditor": _HOLD_TRACE}.get(wanted, _ALLOW_TRACE)
        return {"scenario": "fx.read_rate", "agent": trace["agent"], "run_id": "demo-x",
                "action_id": trace["action_id"], "decision": trace["decision"],
                "reason": trace["reason"], "executed": trace["upstream"]["contacted"],
                "upstream_contacted": trace["upstream"]["contacted"],
                "execution_result": trace["upstream"], "receipt": trace["receipt_id"],
                "tool": "fx.read_rate"}

    def action_control(req):
        # The real control plane guards these routes with the operator token in x-warrnt-admin
        # (control_plane/app.py:645, ``x_warrnt_admin: str = Header(default="")``); an Authorization
        # bearer is accepted too so the harness does not force one credential shape.
        lower = {k.lower() for k in req.headers.keys()}
        authorised = "x-warrnt-admin" in lower or "authorization" in lower
        held = bool(state.get("held"))
        if authorised:
            state["held"] = False
            state["resolved"] = True
            return {"ok": True, "action_id": HOLD_ACTION_ID, "state": "decided",
                    "decision": "allow", "resolved_by": "operator-1"}
        return {"__status__": 401, "ok": False, "error": "missing operator token",
                "action_id": HOLD_ACTION_ID, "state": "pending" if held else "unknown"}

    def action_detail(req):
        held = bool(state.get("held")) and not state.get("resolved")
        trace = dict(_HOLD_TRACE)
        trace["state"] = "pending" if held else ("decided" if state.get("resolved") else "pending")
        trace["decision"] = "human" if held else ("allow" if state.get("resolved") else "human")
        trace["executed"] = bool(state.get("resolved"))
        return {"trace": trace, "authority_source": "tenet-kernel", "llm_authority": False}

    def agent_revoke(req):
        # Mirrors the real route (control_plane/app.py, _revoke): the operator token is required
        # (401 without it) AND a named person is required (422 without one) - the halt is refused
        # before anything is committed. The name the page sent is echoed back in `by`.
        lower = {k.lower() for k in req.headers.keys()}
        if "x-warrnt-admin" not in lower and "authorization" not in lower:
            return {"__status__": 401, "error": "operator token required"}
        raw = req.body or ""
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        by = str((body or {}).get("by") or "").strip()
        if not by:
            return {"__status__": 422, "error": "a named person is required", "field": "by"}
        state["revoked_by"] = by
        return {"agent": body.get("agent") or "fx-trader", "state": "halted", "by": by}

    return {
        "/api/live-trace": live_trace,
        "/api/overview": (lambda _r: {"mode": "live", "upstream_configured": True}),
        "/api/model-usage": (lambda _r: {"calls_completed": 1, "total_tokens": 42, "input_tokens": 20,
                                          "output_tokens": 22, "max_latency_ms": 12, "mode": "live",
                                          "model_served": "deepseek-chat"}),
        "/api/security-events": (lambda _r: {"count": len(events or []), "events": events or [],
                                             "mode": "live"}),
        "/api/actions/pending": (lambda _r: {"count": len(pending or []), "pending": pending or []}),
        "/api/ask": ask,
        "/api/demo/run": demo_run,
        "__action_control__": action_control,
        "__action_detail__": action_detail,
        "__agent_revoke__": agent_revoke,
    }


# ------------------------------------------------------------------------------------- the driver
# Served ONLY to the test browser (appended after the page). It performs the human interaction and
# leaves a JSON record of what it attempted in ``#probe`` so a test can tell "the page rejected me"
# from "the driver could not find the control". It never fabricates a page state.
_DRIVER = """
<script>
(function () {
  function log(o) { var p = document.getElementById('probe');
    if (!p) { p = document.createElement('pre'); p.id = 'probe';
      p.style.display = 'none'; document.body.appendChild(p); }
    p.textContent = JSON.stringify(o); }
  function set(id, val) { var e = document.getElementById(id); if (e) { e.value = val; }
    return !!e; }
  function click(id) { var e = document.getElementById(id); if (e) { e.click(); } return !!e; }
  var steps = [];
  var report = { ctl: {}, act: {}, results: steps };
  function snap(prefix, ids) { ids.forEach(function (id) {
    report[prefix][id] = !!document.getElementById(id); }); }
  function run() {
    try {
      window.confirm = function () { return true; };  // the human would click OK; the driver records the request
      if (window.__token__) { localStorage.setItem('warrnt_admin', window.__token__); }
      else { localStorage.removeItem('warrnt_admin'); }
      if (window.__operator__ !== null && window.__operator__ !== undefined) {
        set('operatorName', window.__operator__);
      }
      snap('ctl', ['intentInput', 'intentGo', 'proposalText', 'actionCard', 'whoActs', 'whoGo',
                   'approveBtn', 'denyBtn', 'traceBody', 'operatorName', 'revoke']);
      if (window.__intent__) {
        set('intentInput', window.__intent__);
        click('intentGo');
      }
      setTimeout(function () {
        var card = document.getElementById('actionCard');
        report.act.cardText = card ? card.textContent.replace(/\\s+/g, ' ').trim() : '';
        if (window.__who__) {
          set('whoActs', window.__who__);
          var sel = document.getElementById('whoActs');
          if (sel && sel.tagName === 'SELECT') { sel.dispatchEvent(new Event('change')); }
          click('whoGo');
        }
        setTimeout(function () {
          if (window.__press__ === 'approve') { click('approveBtn'); }
          if (window.__press__ === 'deny') { click('denyBtn'); }
          if (window.__press__ === 'revoke') { click('revoke'); }
          // A refusal is written synchronously before the click handler's first await, but the page
          // polls /api/live-trace every 2s and re-paints #footer — so sample it early, before a poll
          // can clobber it. The resolve message on #controlMsg is written after the round-trip, so
          // sample that late.
          setTimeout(function () {
            var f = document.getElementById('footer');
            report.act.footer = f ? f.textContent.replace(/\\s+/g, ' ').trim() : '';
          }, 150);
          setTimeout(function () {
            var m = document.getElementById('controlMsg');
            report.act.controlMsg = m ? m.textContent.replace(/\\s+/g, ' ').trim() : '';
            log(report);
          }, 1500);
        }, 1400);
      }, 1400);
    } catch (err) { report.error = String(err); log(report); }
  }
  if (document.readyState === 'complete') { setTimeout(run, 500); }
  else { window.addEventListener('load', function () { setTimeout(run, 500); }); }
})();
</script>
"""


def _driver(intent=None, who=None, press=None, token=None, operator=None):
    """The config script plus the interaction script, both appended to the served page."""
    cfg = {"__intent__": intent, "__who__": who, "__press__": press, "__token__": token,
           "__operator__": operator}
    return "<script>window.__cfg__ = %s; %s</script>" % (
        json.dumps(cfg),
        "".join("window.%s = %s;" % (k, json.dumps(v)) for k, v in cfg.items())) + _DRIVER


def _render(payloads, intent=None, who=None, press=None, token=None, operator=None):
    """Serve the page with a driver that performs one interaction; return (dom, recorder).

    ``payloads`` is the canned API surface; the driver config is added under ``__driver__``. The
    recorder outlives the server so a test can inspect every request the page made.
    """
    body = dict(payloads)
    body["__driver__"] = _driver(intent=intent, who=who, press=press, token=token, operator=operator)
    served = _Served(body)
    url = served.__enter__()
    try:
        dom = _rendered_dom(url)
    finally:
        served.__exit__(None, None, None)
    return dom, served.recorder


# ==================================================================== T1 .. T6
# Each test drives the rendered page and asserts on product-meaningful rendered state plus the
# bytes the page actually sent. None asserts "an element exists" where the meaning requires the
# selected action to be displayed.


def test_t1_intent_box_posts_ask_and_renders_proposal_without_authority():
    """T1 positive - the intent box really posts /api/ask and renders the verdict as a PROPOSAL.

    The page must (a) send ``{"q": ...}`` to /api/ask, (b) show the model's answer, and (c) show
    the kernel's verdict on the action card while never presenting itself as the authorizer
    (TENET stays the only authority; ``llm_authority`` false is stated, not implied).
    """
    payloads = _base_payloads(events=[_feed_event(_ALLOW_TRACE)], ask_body=_ask_with_proposal(_ALLOW_TRACE))
    dom, rec = _render(payloads, intent="Check today's EUR/USD rate for me.")

    asks = [c for c in rec.calls if c["path"] == "/api/ask"]
    assert asks, "the page never contacted /api/ask — the intent box is not wired to the real path"
    assert asks[0]["method"] == "POST", "the intent box must POST /api/ask, got %s" % asks[0]["method"]
    assert "EUR/USD" in asks[0]["body"], "the typed intent did not reach /api/ask: %r" % asks[0]["body"]

    proposal = _text(dom, "proposalText")
    assert proposal, "no proposal text was rendered for the answer"
    assert "proposal" in proposal.lower() or "no authority" in proposal.lower(), (
        "the answer is not framed as a proposal (never a permission): %r" % proposal[:200])

    card = _text(dom, "actionCard")
    assert card, "the propose_action verdict was not rendered as an action card"
    assert "read today's eur/usd exchange rate" in card.lower(), (
        "the action card does not translate fx.read_rate to a human sentence: %r" % card[:300])
    assert "fx-trader" in card.lower(), "the action card does not name who is asking"
    assert _ALLOW_TRACE["reason"] in card, "the kernel's own reason is not shown verbatim"


def test_t2_no_proposal_yields_no_decision():
    """T2 negative - when the answer carries no propose_action verdict, the surface invents nothing.

    The page must render the proposal and explicitly state that no decision was produced. It must
    NOT render an action card, and it must NOT contain an allow/deny verdict of its own making.
    """
    payloads = _base_payloads(events=[], ask_body=_ASK_DEGRADED)
    dom, _rec = _render(payloads, intent="Tell me a joke about the weather.")

    proposal = _text(dom, "proposalText")
    assert proposal, "the page rendered nothing for a proposal-less answer"
    card = _text(dom, "actionCard")
    assert not card, "the page invented an action card with no propose_action verdict: %r" % card[:200]
    lowered = (proposal + " " + _text(dom, "askSection")).lower()
    assert "no decision" in lowered or "not authorised" in lowered or "not authorized" in lowered \
        or "no action in the record" in lowered or "degraded" in lowered, (
        "the page did not state plainly that no decision was produced: %r" % proposal[:200])
    for invented in ("allowed", "denied"):
        assert invented not in card.lower(), "the page invented a %r verdict" % invented


def test_t3_held_action_is_shown_waiting_and_in_pending():
    """T3 positive - the HOLD state is real and is shown as waiting, not as done.

    Choosing ``fx-auditor`` must POST /api/demo/run and the page must render a card whose
    consequence line says nothing was sent yet, alongside the human controls.
    """
    payloads = _base_payloads(events=[_feed_event(_HOLD_TRACE)],
                              pending=[_feed_event(_HOLD_TRACE)], state={"held": True})
    dom, rec = _render(payloads, who="fx-auditor")

    runs = [c for c in rec.calls if c["path"] == "/api/demo/run"]
    assert runs, "choosing who acts never contacted /api/demo/run"
    assert "fx-auditor" in runs[0]["body"], "the selector did not send the chosen agent: %r" % runs[0]["body"]

    # The real route is admin-gated (app.py:691); when the operator token is present the page must
    # carry it, exactly as it does for approve/deny. Without the token the page must stay honest.
    tok_payloads = _base_payloads(events=[_feed_event(_HOLD_TRACE)],
                                  pending=[_feed_event(_HOLD_TRACE)],
                                  state={"held": True, "demo_requires_admin": True})
    tok_dom, tok_rec = _render(tok_payloads, who="fx-auditor", token="operator-token")
    tok_runs = [c for c in tok_rec.calls if c["path"] == "/api/demo/run"]
    assert tok_runs and ({k.lower() for k in tok_runs[0]["headers"]} & {"x-warrnt-admin", "authorization"}), (
        "with a token the page must authenticate the admin-gated /api/demo/run route")
    assert _text(tok_dom, "actionCard"), "the authenticated demo route did not render the verdict"

    card = _text(dom, "actionCard").lower()
    assert "not been sent" in card or "nothing has been sent" in card, (
        "the held action is not shown as not-yet-sent: %r" % card[:300])
    assert _text(dom, "approveBtn") or "approve" in _text(dom, "controlBlock").lower(), (
        "a held action must offer a real Approve control")
    assert "waiting for you" in _text(dom, "controlBlock").lower() or "approve" in card, (
        "the held action does not present the human control")


def test_t3b_admin_gated_demo_route_without_token_is_honest():
    """T3b negative - the admin-gated /api/demo/run answers 401 and the page says so.

    ``/api/demo/run`` is protected by the operator token on the real control plane
    (``app.py:691``). With no token the page must post the real route, receive the real 401, and
    state that the authenticated console is required — it must not invent a verdict and must not
    show an action card for a decision the kernel never produced.
    """
    payloads = _base_payloads(events=[_feed_event(_ALLOW_TRACE)],
                              state={"held": True, "demo_requires_admin": True})
    dom, rec = _render(payloads, who="support-copilot")

    runs = [c for c in rec.calls if c["path"] == "/api/demo/run"]
    assert runs, "choosing who acts never contacted the real /api/demo/run route"
    text = (_text(dom, "proposalText") + " " + _text(dom, "actionCard")).lower()
    assert "operator console" in text or "protected" in text or "401" in text, (
        "the real 401 from the admin-gated demo route was swallowed: %r" % text[:300])
    assert not _text(dom, "actionCard"), (
        "the page rendered an action card for a decision the kernel never produced")


def test_t4_no_operator_token_changes_nothing():
    """T4 negative - without a token the control is honestly protected and nothing moves.

    Pressing Approve with no ``warrnt_admin`` must (a) still surface the control (not hide it),
    (b) state that it is protected, and (c) leave the action pending - no fake execution.
    """
    state = {"held": True}
    payloads = _base_payloads(events=[_feed_event(_HOLD_TRACE)],
                              pending=[_feed_event(_HOLD_TRACE)], state=state)
    dom, rec = _render(payloads, who="fx-auditor", press="approve", token=None)

    block = _text(dom, "controlBlock").lower()
    assert "protected" in block or "operator" in block, (
        "with no token the control must say plainly that it is protected: %r" % block[:300])
    assert state.get("resolved") is not True, "approve moved a held action despite no operator token"
    approvals = [c for c in rec.calls if c["path"].endswith("/approve")]
    if approvals:
        sent = {k.lower() for k in approvals[0]["headers"].keys()}
        assert "x-warrnt-admin" not in sent and "authorization" not in sent, (
            "the page sent an operator credential it did not have")
    assert "executed" not in _text(dom, "actionCard").lower(), (
        "the page faked an execution with no token")


def test_t5_token_approve_resolves_and_shows_execution():
    """T5 positive - the token-bearing Approve resolves the hold and shows the real outcome.

    The page must POST /api/actions/{id}/approve WITH the operator token, RE-READ the action, and
    render the resulting executed state plus a receipt. Approve and Deny are both proven (two
    renders) so the pair is exercised. The operator declares a name, as ACT-7b requires: the page
    sends the declared name, never an invented one.
    """
    for press in ("approve", "deny"):
        state = {"held": True}
        payloads = _base_payloads(events=[_feed_event(_HOLD_TRACE)],
                                  pending=[_feed_event(_HOLD_TRACE)], state=state)
        dom, rec = _render(payloads, who="fx-auditor", press=press, token="operator-token",
                           operator="anna.kowalska")

        choices = [c for c in rec.calls if c["path"].endswith("/" + press)]
        assert choices, "pressing %s never POSTed to the real /api/actions/{id}/%s route" % (press, press)
        assert choices[0]["headers"].get("authorization") or choices[0]["headers"].get("x-warrnt-admin"), (
            "the %s request did not carry the operator token" % press)
        assert HOLD_ACTION_ID in choices[0]["path"], (
            "the control did not target the held action id: %r" % choices[0]["path"])
        # the request carries the name the operator DECLARED, not a fabricated constant
        assert "anna.kowalska" in choices[0]["body"], (
            "the %s request did not carry the declared operator name: %r" % (press, choices[0]["body"]))
        # the page re-read the action after the attempt
        rereads = [c for c in rec.calls if c["method"] == "GET"
                   and c["path"] == "/api/actions/" + HOLD_ACTION_ID]
        assert rereads, "the page did not RE-READ the action after %s" % press
        assert state.get("resolved") is True, "%s did not resolve the hold with a valid token" % press
        card = _text(dom, "actionCard").lower() + " " + _text(dom, "controlBlock").lower()
        assert "receipt" in card or "9c0ffee0" in card, "no receipt surfaced after %s" % press


def test_t6_approve_on_unknown_action_does_not_fabricate_success():
    """T6 negative - the control plane error on an unknown id is shown, not swallowed.

    The page must POST the real approve route and, when the server reports the action is unknown
    (404/409), surface that real error and show NO receipt and NO execution.
    """
    def unknown_control(_req):
        return {"__status__": 404, "ok": False, "error": "unknown action id",
                "action_id": "A-9999", "state": "unknown"}

    payloads = _base_payloads(events=[], pending=[], state={"held": True})
    payloads["__action_control__"] = unknown_control
    dom, rec = _render(payloads, who="fx-auditor", press="approve", token="operator-token",
                       operator="anna.kowalska")

    approvals = [c for c in rec.calls if c["path"].endswith("/approve")]
    assert approvals, "no approve attempt was made against the real route"
    text = _text(dom, "controlBlock").lower() + " " + _text(dom, "actionCard").lower()
    assert "error" in text or "unknown" in text or "not found" in text or "failed" in text, (
        "the real error was swallowed: %r" % text[:300])
    # The action was never resolved: the page must NOT have re-read it, must NOT claim a resolution,
    # and must NOT show an execution. The held action's own receipt may stay on screen (it was
    # really recorded), but no NEW evidence of success may be invented.
    rereads = [c for c in rec.calls if c["method"] == "GET" and c["path"] == "/api/actions/" + HOLD_ACTION_ID]
    assert not rereads, "the page re-read the action as if the failed 404 attempt had resolved it"
    assert "resolved by" not in text and "executed" not in text, (
        "the page fabricated a successful resolution for an unknown action: %r" % text[:300])


def test_defect_deny_card_shows_one_honest_sentence():
    """The verified defect fix - an unrecorded action class reads as ONE honest sentence.

    Before: the DENY card's "Data involved" rendered ``action class not recorded`` followed by an
    empty ``{}``. After: a single human sentence, and never an empty brace object.
    """
    trace = dict(_DENY_TRACE)
    trace["action"] = {"tool": "fx.read_rate", "intent": "read the EUR/USD rate"}  # no class, no args
    payloads = _base_payloads(events=[_feed_event(trace)], live_trace_body=trace)
    dom, _rec = _render(payloads)

    body = _text(dom, "traceBody")
    assert "{}" not in body, "the empty technical fallback {} is still rendered: %r" % body[:400]
    assert "no action-class detail was recorded" in body.lower(), (
        "the honest sentence for an unrecorded class is missing: %r" % body[:400])


# ============================================================ ACT-7b: the page invents no operator
# Requirement 5: approve, deny and revoke must send the name the operator DECLARED in the console.
# If no name is declared the control action is not sent at all and the page says so plainly.
# These drive the RENDERED page and assert on the bytes it actually POSTed.

def test_act7b_revoke_sends_the_declared_operator_name():
    """revoke with a declared name posts that exact name to the real revoke route."""
    state = {"held": False}
    payloads = _base_payloads(events=[_feed_event(_ALLOW_TRACE)], state=state)
    dom, rec = _render(payloads, press="revoke", token="operator-token", operator="indradev_")

    posts = [c for c in rec.calls if c["method"] == "POST" and c["path"].endswith("/revoke")]
    assert posts, "pressing Stop agent never POSTed to the real /api/agents/{id}/revoke route"
    assert "indradev_" in posts[0]["body"], (
        "the revoke request did not carry the declared operator name: %r" % posts[0]["body"])
    assert state.get("revoked_by") == "indradev_", "the declared name never reached the route"
    assert "operator\"" not in posts[0]["body"], "the page sent a fabricated constant identity"
    notice = _text(dom, "operatorNotice").lower()
    assert "indradev_" in notice and "halted" in notice, (
        "the page did not confirm the halt and name the decider: %r" % notice[:300])


def test_act7b_revoke_without_a_declared_name_sends_nothing_and_says_so():
    """revoke with no declared name sends NO request and explains why, in the message area."""
    state = {"held": False}
    payloads = _base_payloads(events=[_feed_event(_ALLOW_TRACE)], state=state)
    dom, rec = _render(payloads, press="revoke", token="operator-token")  # no operator name

    posts = [c for c in rec.calls if c["method"] == "POST" and c["path"].endswith("/revoke")]
    assert not posts, "the page sent an unattributed revoke anyway: %r" % posts
    assert state.get("revoked_by") is None, "an unnamed revoke reached the route"
    # The refusal is durable (the 2s refresh poll owns #footer), so the page carries it on its own
    # operator-notice line as well as the footer.
    notice = _text(dom, "operatorNotice").lower()
    footer = _text(dom, "footer").lower()
    said = notice + " || " + footer
    assert "name" in said and "no request was sent" in said, (
        "the page did not say plainly why the unattributed halt was not sent: %r" % said[:300])


def test_act7b_approve_without_a_declared_name_sends_nothing_and_says_so():
    """approve/deny with no declared name sends NO request and says so in controlMsg."""
    for press in ("approve", "deny"):
        state = {"held": True}
        payloads = _base_payloads(events=[_feed_event(_HOLD_TRACE)],
                                  pending=[_feed_event(_HOLD_TRACE)], state=state)
        dom, rec = _render(payloads, who="fx-auditor", press=press, token="operator-token")

        posts = [c for c in rec.calls if c["method"] == "POST" and c["path"].endswith("/" + press)]
        assert not posts, "the page sent an unattributed %s anyway: %r" % (press, posts)
        assert state.get("resolved") is not True, "an unnamed %s moved the held action" % press
        msg = _text(dom, "controlMsg").lower()
        assert "name" in msg and ("no request" in msg or "declare" in msg), (
            "the page did not say plainly why the unnamed %s was not sent: %r" % (press, msg[:300]))
