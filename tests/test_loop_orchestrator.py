"""The loop orchestrator (index.html): a journey rail, ONE named next step per outcome, no dead end.

The task brief (loop-orchestrator-task.txt) asks the Control Room to stop being a wall of facts and
become a compass: show WHERE in the seven-beat loop the operator stands (the rail) and name the ONE
next step for every possible outcome — allow, deny, hold and not-evaluated — so the screen never
dead-ends after the answer.

These tests prove it by a REAL chromium render of ``index.html`` (never by reading source):

  (AC1) the rail renders the seven beats SAY·SEE·UNDERSTAND·DECIDE·WITNESS·PROVE·WIN, and a beat is
        DONE only where the record PROVES it — evidence, not a timer or a client flag;
  (AC2) exactly one named next step appears for each terminal outcome, each with a control that
        performs it, and never a dead end (every outcome has a non-empty #nextStep);
  (AC3) the rail, the next step and the action card read the SAME evidence, so they cannot disagree;
  (AC4) the negative path (a deny) names the refusal reason and proves no upstream contact;
  (AC5) a human resolution (approve) moves the outcome from hold to allow and the rail follows.

When chromium is absent the tests SKIP with a clear reason — never a pass they did not earn.
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

ALLOW_ACTION_ID = "A-0001"
DENY_ACTION_ID = "A-0002"
HOLD_ACTION_ID = "A-0003"

# The kernel's own composed record, one per outcome. Field-for-field this is the shape
# control_plane/kernel.py emits (Amendment 3 added `state` and `executed`).
_ALLOW_TRACE = {
    "agent": "fx-trader",
    "action": {"tool": "fx.read_rate", "class": "read_market_data",
               "intent": "read the EUR/USD rate", "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "allow",
    "reason": "entitled to market_data.fx.read",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "fx-trader"},
               "entitlement": {"ok": True, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9001", "state": "active", "sig_ok": True, "ttl_remaining": 3400},
               "policy": {"ok": True, "detail": "order ok"}},
    "upstream": {"contacted": True, "http_status": 200,
                 "endpoint": "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD",
                 "value": {"EUR": 1.0, "USD": 1.1225},
                 "response_sha256": "f63f64a5e9b3584bd32e0ea70927ea574bea7ef3", "latency_ms": 34.856},
    "receipt_id": "4a8bae2f", "action_id": ALLOW_ACTION_ID,
    "state": "approved", "executed": True,
    "principal": "desk-operator", "on_behalf_of": "treasury",
    "timestamp": 1759420000, "origin": "operator self-check", "incomplete": [],
}
_DENY_TRACE = {
    "agent": "support-copilot",
    "action": {"tool": "fx.read_rate", "class": "read_market_data",
               "intent": "read the EUR/USD rate", "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "deny",
    "reason": "no entitlement to market_data.fx.read",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "support-copilot"},
               "entitlement": {"ok": False, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9002", "state": "active", "sig_ok": True, "ttl_remaining": 120},
               "policy": {"ok": False, "detail": "no entitlement"}},
    "upstream": {"contacted": False, "http_status": None, "endpoint": None, "value": None,
                 "response_sha256": None, "latency_ms": None},
    "receipt_id": "bfc7eacc", "action_id": DENY_ACTION_ID,
    "state": "denied", "executed": False,
    "principal": "support-ops", "on_behalf_of": "service-desk",
    "timestamp": 1759420001, "origin": "agent call", "incomplete": [],
}
_HOLD_TRACE = {
    "agent": "fx-auditor",
    "action": {"tool": "fx.read_rate", "class": "read_market_data",
               "intent": "read the EUR/USD rate", "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "human",
    "reason": "this order prices a live read with a person's decision · class observe",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "fx-auditor"},
               "entitlement": {"ok": True, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9003", "state": "active", "sig_ok": True, "ttl_remaining": 1800},
               "policy": {"ok": True, "detail": "order ok · require-human"}},
    "upstream": {"contacted": False, "http_status": None, "endpoint": None, "value": None,
                 "response_sha256": None, "latency_ms": None},
    "receipt_id": "9c0ffee0", "action_id": HOLD_ACTION_ID,
    "state": "pending", "executed": None,
    "principal": "risk-office", "on_behalf_of": "compliance",
    "timestamp": 1759420002, "origin": "operator self-check", "incomplete": [],
}
_TRACES = {ALLOW_ACTION_ID: _ALLOW_TRACE, DENY_ACTION_ID: _DENY_TRACE, HOLD_ACTION_ID: _HOLD_TRACE}


def _ask_with_proposal(trace):
    """The /api/ask payload for one trace: run-scoped AI evidence + the propose_action verdict."""
    verdict = {"submitted": True, "proposed_by": "deepseek", "authority": "tenet-kernel",
               "llm_authority": False, "agent": trace["agent"], "tool": trace["action"]["tool"],
               "resource": trace["action"]["tool"], "run_id": "run-1", "action_id": trace["action_id"],
               "decision": trace["decision"], "reason": trace["reason"],
               "executed": trace["upstream"]["contacted"],
               "upstream_contacted": trace["upstream"]["contacted"], "receipt": None, "rationale": ""}
    return {"run_id": "run-1",
            "answer": ("The kernel decided %s for %s. This is a proposal report - the model holds no "
                       "authority; the kernel is the only authority." % (trace["decision"], trace["agent"])),
            "evidence": [{"source": "propose_action", "claim": "verdict",
                          "value": json.dumps(verdict), "action_id": trace["action_id"]}],
            "specialists": ["Governance Agent", "Kernel Agent", "Control-Plane Agent"],
            "next_action": "watch the action card", "action_id": trace["action_id"],
            "provider": "deepseek", "model": "deepseek-chat", "kernel": "available",
            "ai": {"answer_origin": "model", "model_called": True, "model_completed": True,
                   "model_calls": 1, "input_tokens": 20, "output_tokens": 22, "total_tokens": 42,
                   "token_status": "reported", "model_requested": "deepseek-chat",
                   "model_served": "deepseek-chat", "trace_id": "tr-1"}}


def _drive_script(spec):
    """A trailing <script> that makes the page act like a person. ``spec`` is ``cmd`` or ``cmd:arg``:

    ``ask``            type a real intent and press "Ask TENET"   (arg: the intent text)
    ``who:G``          pick agent G in the "who acts" select and press "Let them try"
    ``resolve:approve``/``resolve:deny``  press the hold's Approve / Deny control after the ask
    ``receipt``        after an allow ask, press "Read the receipt"
    ``chain``          after an allow ask, press "See the whole chain"
    """
    cmds = spec.split(",")
    steps = []
    for c in cmds:
        cmd, _, arg = c.partition(":")
        arg = urllib.parse.unquote(arg)
        if cmd == "ask":
            steps.append(
                "var i=document.getElementById('intentInput');if(i){i.value=%s;}"
                "var g=document.getElementById('intentGo');if(g)g.click();" % json.dumps(arg or "read the EUR/USD rate"))
        elif cmd == "who":
            steps.append(
                "var s=document.getElementById('whoActs');if(s){s.value=%s;}"
                "var b=document.getElementById('whoGo');if(b)b.click();" % json.dumps(arg or "fx-trader"))
        elif cmd == "resolve":
            steps.append(
                "try{localStorage.setItem('warrnt_admin','test-operator-token')}catch(e){}"
                "var n=document.getElementById('operatorName');if(n)n.value=%s;" % json.dumps("indradev_"))
            steps.append(
                "var verb=%s;(function tryResolve(tries){"
                "var r=document.getElementById(verb==='deny'?'nsDeny':'nsApprove');"
                "if(!r)r=document.getElementById(verb==='deny'?'denyBtn':'approveBtn');"
                "if(r&&!r.disabled){r.click();return}"
                "if(tries>0){setTimeout(function(){tryResolve(tries-1)},400)}})(15);" % json.dumps(arg or "approve"))
        elif cmd == "receipt":
            steps.append("var r=document.getElementById('nsReadReceipt');if(r)r.click();")
        elif cmd == "chain":
            steps.append("var c=document.getElementById('nsChain');if(c)c.click();")
    # Run the steps from the injected script itself: it is parsed AFTER the page's main script (it sits
    # just before </body>), so intentGo/whoGo already exist. We do NOT wait for `load` — chromium's
    # --dump-dom can snapshot before the load event — and instead schedule with short timeouts so the
    # async fetch chain settles while --virtual-time-budget advances the clock.
    body = "".join("setTimeout(function(){%s},%d);" % (s, 300 + i * 900)
                   for i, s in enumerate(steps))
    return "<script>setTimeout(function(){%s},150);</script>" % body


class _Served:
    """A tiny server that answers the endpoint set index.html actually calls, so a real browser can
    render the whole loop. One action may be pre-loaded (by id) and one ask may be scripted to fail."""

    def __init__(self, trace=None, chain=None, ask_status=200, resolve_decision=None):
        self.trace = trace
        self.chain = chain if chain is not None else {
            "ok": True, "length": 1 if trace else 0,
            "head": (trace or {}).get("receipt_id"),
            "records": ([{"receipt_id": trace["receipt_id"], "action_id": trace["action_id"],
                          "decision": trace["decision"], "agent": trace["agent"],
                          "tool": trace["action"]["tool"], "prev": None, "ts": trace["timestamp"],
                          "hash": "0e11a5"}] if trace else [])}
        self.ask_status = ask_status
        self.resolve_decision = resolve_decision
        self.ask_calls = 0
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, body, ctype="application/json", status=200):
                b = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                p = re.sub(r"\?.*$", "", self.path)
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if p in ("/", "/index.html"):
                    drive = (q.get("drive") or [None])[0]
                    page = PAGE
                    if drive:
                        # Test-only: the shipped page is served unchanged, with a trailing script that
                        # acts as the operator (types an intent, clicks a control). The repo file is
                        # never modified; this only drives the real renderer the way a person would.
                        # index.html closes at the end of its <script> with no explicit </body>, so the
                        # driver is appended at EOF (still inside the body the browser infers).
                        page = PAGE + _drive_script(drive)
                    return self._send(page.encode(), "text/html")
                if p == "/api/overview":
                    return self._send({"mode": "live", "upstream_configured": True,
                                       "upstream": "local" if outer.trace else "unconfigured",
                                       "specialists": ["Governance Agent", "Kernel Agent",
                                                       "Control-Plane Agent"],
                                       "readiness": {"kernel": True, "provider": True}})
                if p == "/api/model-usage":
                    return self._send({"calls_completed": 1, "calls_started": 1, "calls_failed": 0,
                                       "total_tokens": 42, "input_tokens": 20, "output_tokens": 22})
                if p == "/api/security-events":
                    return self._send({"events": [], "count": 0})
                if p == "/api/state":
                    return self._send({"chain": outer.chain, "pending": [], "mode": "live"})
                if p == "/api/live-trace":
                    aid = (q.get("action_id") or [None])[0]
                    tr = outer.trace
                    if aid and tr and tr.get("action_id") != aid:
                        tr = None
                    if tr and outer.resolve_decision and tr.get("action_id") == HOLD_ACTION_ID:
                        tr = dict(tr)
                        approved = outer.resolve_decision in ("approve", "allow")
                        tr["decision"] = "allow" if approved else "deny"
                        tr["upstream"] = dict(tr["upstream"], contacted=approved,
                                              http_status=200 if approved else None,
                                              endpoint="https://api.frankfurter.dev/v1/latest" if approved else None,
                                              value={"EUR": 1.0, "USD": 1.1225} if approved else None,
                                              response_sha256=("a" * 40) if approved else None,
                                              latency_ms=12.0 if approved else None)
                        tr["decided_by"] = "indradev_"
                        tr["state"] = "approved" if approved else "denied"
                        tr["executed"] = True if approved else False
                    if tr:
                        return self._send({"trace": tr, "authority_source": "tenet-kernel",
                                           "llm_authority": False, "mode": "live",
                                           "action_id": tr["action_id"],
                                           "receipt_id": tr["receipt_id"]})
                    return self._send({"trace": None, "authority_source": "tenet-kernel",
                                       "llm_authority": False, "mode": "live",
                                       "action_id": aid, "reason": "no action recorded"})
                return self._send({}, "application/json", 404)

            def do_POST(self):
                p = re.sub(r"\?.*$", "", self.path)
                n = int(self.headers.get("content-length", "0") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                except Exception:
                    body = {}
                if p == "/api/ask":
                    outer.ask_calls += 1
                    if outer.ask_status != 200:
                        return self._send({"error": "provider unavailable"}, "application/json",
                                          outer.ask_status)
                    if not outer.trace:
                        return self._send({"error": "no upstream configured"}, "application/json", 400)
                    return self._send(_ask_with_proposal(outer.trace))
                if p in ("/api/resolve", "/api/approve", "/api/deny") or re.match(r"^/api/actions/[^/]+/(approve|deny)$", p):
                    d = body.get("decision") or ("deny" if p.endswith("deny") else "allow")
                    outer.resolve_decision = d
                    return self._send({"ok": True, "decision": d, "action_id": body.get("action_id")})
                return self._send({"ok": True})

            def log_message(self, *a):
                return

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d/" % self._httpd.server_address[1]

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()


def _rendered_dom(served, wait_budget=7000, drive=None):
    """Render index.html in chromium and return the settled DOM as one string. Skips if absent.

    ``drive`` (optional) is a _drive_script spec that makes the page act like an operator first."""
    if CHROMIUM is None:
        pytest.skip("chromium is not installed; the loop orchestrator tests need a real render")
    url = served.url if not drive else served.url + "?drive=" + urllib.parse.quote(drive)
    out = subprocess.run(
        [CHROMIUM, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
         "--virtual-time-budget=%d" % wait_budget, "--dump-dom", url],
        capture_output=True, text=True, timeout=120)
    return out.stdout if isinstance(out.stdout, str) else out.stdout.decode("utf-8", "replace")


# ------------------------------------------------------------------ reading the rendered DOM
def _section(dom, ident):
    """Return the inner HTML of the element with id ``ident`` (first closing of a nesting-safe scan)."""
    m = re.search(r'<[^>]*\bid="%s"[^>]*>' % re.escape(ident), dom)
    if not m:
        return ""
    start = m.end()
    return dom[start:start + 20000]


def _beats(dom):
    """The rail's beats as [(beat, state)] in DOM order, read from the rendered attributes."""
    return [(m.group("b"), m.group("s")) for m in re.finditer(
        r'data-beat="(?P<b>[A-Z]+)"\s+data-state="(?P<s>[a-z_]+)"', dom)]


def _outcome(dom):
    """The next step's declared outcome (its data-outcome attribute)."""
    m = re.search(r'id="nextStep"[^>]*data-outcome="([a-z_]+)"', dom)
    return m.group(1) if m else None


def _next_step_html(dom):
    """Everything the operator reads and can press in the next-step block."""
    m = re.search(r'<div class="nextStep" id="nextStep"[^>]*>(.*?)</div>\s*(?:<div class="chain"|<div class="rail"|<section|</main>)',
                  dom, re.S)
    return m.group(1) if m else _section(dom, "nextStep")


def _text(html):
    """The visible words of a fragment: tags stripped, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


@pytest.fixture
def allow_served():
    s = _Served(_ALLOW_TRACE)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def deny_served():
    s = _Served(_DENY_TRACE)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def hold_served():
    s = _Served(_HOLD_TRACE)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def failing_served():
    s = _Served(_ALLOW_TRACE, ask_status=503)
    try:
        yield s
    finally:
        s.close()


# ================================================================================================
# AC1 — the journey rail renders the seven beats and marks a beat done only where the record proves it
# ================================================================================================
def test_ac1_rail_renders_seven_beats_on_load(allow_served):
    """With a real allow on the record, the rail shows all seven beats in order, in the guide's words."""
    dom = _rendered_dom(allow_served)
    beats = _beats(dom)
    assert [b for b, _ in beats] == ["SAY", "SEE", "UNDERSTAND", "DECIDE", "WITNESS", "PROVE", "WIN"], beats
    rail = _text(_section(dom, "journeyRail"))
    for word in ("your words", "what I heard", "what your AI wants", "the kernel decided",
                 "it happened", "the receipt"):
        assert word in rail, "the rail must name every beat in plain words: missing %r in %r" % (word, rail)
    assert sum(1 for _, s in beats if s == "current") == 1, beats


def test_ac1_rail_marks_done_only_where_proven(allow_served):
    """A proven, executed allow marks all seven beats; the latest is 'current', not 'done'."""
    dom = _rendered_dom(allow_served)
    states = dict(_beats(dom))
    assert states["SAY"] == "done" and states["DECIDE"] == "done", states
    assert states["WIN"] in ("done", "current"), states
    assert states["WIN"] == "current", "the latest proven beat is where the operator stands: %s" % states


def test_ac1_rail_does_not_claim_proof_absent_from_the_record(deny_served):
    """A refusal that never crossed must NOT mark WIN done — the execution is not proven."""
    dom = _rendered_dom(deny_served)
    states = dict(_beats(dom))
    assert states["WIN"] != "done", "WIN must not be done when no execution is proven: %s" % states
    note = _text(_section(dom, "railNote"))
    assert note.startswith("You are at "), note


def test_ac1_rail_with_no_action_says_the_loop_has_not_started():
    """Before any action, the rail is honest: nothing done, and the note says so."""
    served = _Served(None)  # no action on record
    try:
        dom = _rendered_dom(served)
    finally:
        served.close()
    states = dict(_beats(dom))
    assert all(s == "not_yet" for s in states.values()), states
    assert "not started" in _text(_section(dom, "railNote")).lower()


# ================================================================================================
# AC2 — exactly ONE named next step for EVERY outcome; never a dead end
# ================================================================================================
def test_ac2_allow_names_the_receipt_as_the_next_step(allow_served):
    dom = _rendered_dom(allow_served, drive="ask")
    assert _outcome(dom) == "allow", _outcome(dom)
    step = _next_step_html(dom)
    words = _text(step).lower()
    assert "read the receipt" in words, words
    assert step.count('id="nsReadReceipt"') == 1, step
    assert "see the whole chain" in words, words


def test_ac2_deny_names_the_refusal_with_reason(deny_served):
    dom = _rendered_dom(deny_served, drive="ask")
    assert _outcome(dom) == "deny", _outcome(dom)
    words = _text(_next_step_html(dom))
    assert "nothing crossed" in words.lower(), words
    assert _DENY_TRACE["reason"] in words, "the step must name the kernel's own reason: %r" % words
    assert "never reached" in words.lower() or "not run" in words.lower(), words


def test_ac2_hold_offers_the_persons_decision(hold_served):
    dom = _rendered_dom(hold_served, drive="ask")
    assert _outcome(dom) == "hold", _outcome(dom)
    step = _next_step_html(dom)
    words = _text(step).lower()
    assert "approve" in words and "deny" in words, words
    assert 'id="nsApprove"' in step and 'id="nsDeny"' in step, step
    assert "not been sent" in words, "a hold must say no call was made yet: %r" % words


def test_ac2_not_evaluated_names_the_transport_failure(failing_served):
    dom = _rendered_dom(failing_served, drive="ask", wait_budget=9000)
    assert _outcome(dom) == "not_evaluated", _outcome(dom)
    words = _text(_next_step_html(dom)).lower()
    assert "nothing was decided" in words, words
    assert "retry" in words or "ask again" in words, words


def test_ac2_every_outcome_has_a_next_step_no_dead_end(allow_served, deny_served, hold_served):
    """The brief's core: after the answer, the screen ALWAYS names one next thing to do."""
    for served in (allow_served, deny_served, hold_served):
        dom = _rendered_dom(served, drive="ask")
        step = _next_step_html(dom)
        assert "your next step" in _text(step).lower(), step
        assert re.search(r"<(button|a)\b", step), "the next step must be actionable: %r" % step
        assert _text(step).strip(), "the next step must never be blank: %r" % step


# ================================================================================================
# AC3 — the rail, the next step and the card read ONE evidence and cannot disagree
# ================================================================================================
def test_ac3_allow_agrees_that_the_call_crossed(allow_served):
    dom = _rendered_dom(allow_served, drive="ask")
    assert _outcome(dom) == "allow"
    card = _section(dom, "actionCard")
    assert "contacted" in card.lower() or "crossed" in card.lower() or "HTTP 200" in card, card[:400]
    assert "receipt" in _text(_section(dom, "railNote")).lower()


def test_ac3_no_technical_id_before_the_card(allow_served):
    """The first thing shown stays the human action card; raw ids live behind their disclosure."""
    dom = _rendered_dom(allow_served, drive="ask")
    card_idx = dom.find('id="actionCard"')
    assert card_idx != -1
    for label, pat in (("receipt id", _ALLOW_TRACE["receipt_id"]),
                       ("action id", _ALLOW_TRACE["action_id"])):
        pos = dom.find(pat)
        if pos != -1:
            assert pos > card_idx, "the technical identifier %s appears before the action card" % label


# ================================================================================================
# AC4 — the negative path is a first-class journey, not an error
# ================================================================================================
def test_ac4_deny_rail_stops_at_decide_not_win(deny_served):
    """A denial still walks SAY..DECIDE, is witnessed, and stops short of WIN — an honest rail."""
    dom = _rendered_dom(deny_served, drive="ask")
    states = dict(_beats(dom))
    assert states["DECIDE"] in ("done", "current"), states
    assert states["WIN"] not in ("done", "current"), states


# ================================================================================================
# AC5 — a person's resolution moves hold -> allow and the rail follows
# ================================================================================================
def test_ac5_approve_moves_the_outcome_and_the_rail(hold_served):
    """After a human approves the held action, the next step becomes 'read the receipt' and WIN proves."""
    dom = _rendered_dom(hold_served, drive="ask,resolve:approve", wait_budget=14000)
    assert _outcome(dom) == "allow", _outcome(dom)
    words = _text(_next_step_html(dom)).lower()
    assert "read the receipt" in words, words
    states = dict(_beats(dom))
    assert states["WIN"] in ("done", "current"), states


# ================================================================================================
# AC6 (receipt -> chain) + AC8 (the resolved QA flag), read from the shipped file / real render
# ================================================================================================
def test_ac6_receipt_opens_the_whole_chain(allow_served):
    dom = _rendered_dom(allow_served, drive="ask,receipt,chain", wait_budget=14000)
    chain = _section(dom, "nsChainView")
    words = _text(chain).lower()
    assert "chain" in words, chain
    assert _ALLOW_TRACE["receipt_id"] in chain, "the chain view must carry the real receipt: %r" % chain
    assert "verified" in words or "not verified" in words, chain


def test_ac8_qa_flag_no_longer_claims_a_real_orchestrator_on_boot():
    """The boot-time false claim is gone: __TENET_QA__.realOrchestrator must not be hardcoded true."""
    assert "__TENET_QA__" in PAGE, "the QA seam must survive"
    assert not re.search(r'realOrchestrator\s*:\s*true', PAGE), \
        "the static realOrchestrator:true literal claimed a real orchestrator before any run"
    assert not re.search(r'realOrchestrator\s*=\s*true', PAGE), \
        "no code path may set realOrchestrator true unconditionally at load"


def test_ac8_qa_flag_is_resolved_from_evidence_at_runtime(allow_served):
    """At runtime the flag reflects what happened: true only after a real model-backed ask completed."""
    dom = _rendered_dom(allow_served, drive="ask", wait_budget=10000)
    m = re.search(r'data-real-orchestrator="([a-z]+)"', dom)
    assert m, "the page must publish the resolved orchestrator evidence after a run"
    assert m.group(1) == "true", (
        "a completed model-backed ask must resolve realOrchestrator true, got %r" % m.group(1))
    o = re.search(r'data-answer-origin="([a-z]+)"', dom)
    assert o and o.group(1) in ("model", "demo"), o


def test_ac8_qa_flag_is_false_before_the_evidence_arrives():
    """Before any ask the flag must be false, not the old unconditional true (D12)."""
    served = _Served(_ALLOW_TRACE)
    try:
        dom = _rendered_dom(served)  # rendered, but the operator never pressed Ask
    finally:
        served.close()
    m = re.search(r'data-real-orchestrator="([a-z]+)"', dom)
    # no ask was driven, so the attribute is either absent (never set) or explicitly "false"
    assert m is None or m.group(1) == "false", m
