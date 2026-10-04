"""AC3 (ACT-6): the Control Room's first screen, proven by a REAL render, not by reading the source.

The page's renderer functions are inline in ``index.html`` and not exported, and this repo has no
JS DOM toolkit (no jsdom/playwright/puppeteer; ``node/`` is a Python package). The one mechanism
that executes the page for real is therefore the same one ``scripts/check_rendered_trace.py`` uses:
serve ``index.html`` plus canned ``/api/*`` responses from a stdlib ``http.server`` fixture, then
dump the rendered DOM with ``chromium --headless --dump-dom`` and assert on what a viewer sees.

The four points this file proves:

  (a) a detail whose ``value`` is a JSON object renders as JSON, never the literal ``[object Object]``;
  (b) the first rendered block is the ACTION CARD, and it appears before any technical identifier;
  (c) the empty state says what TENET does and how to start, and carries none of the old
      "No action yet" / "Nothing to show" strings;
  (d) a 429 carrying ``retry_after_s`` renders exactly ``Rate limited · retrying in Ns`` with the
      real N (never the old ``Rate limited — retry in Ns``), and reads as waiting, not as a failure.

When chromium is absent the test SKIPS with a clear reason (it never claims a pass it did not earn),
exactly as ``scripts/check_rendered_trace.py`` exits 2 instead of pretending.
"""
from __future__ import annotations

import functools
import http.server
import json
import re
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path
from pathlib import Path as _Path

import pytest

REPO_ROOT = _Path(__file__).resolve().parent.parent
PAGE = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
CHROMIUM = shutil.which("chromium") or ("/usr/bin/chromium" if _Path("/usr/bin/chromium").exists() else None)

# ---------------------------------------------------------------- canned payloads (real shapes)
# The exact object-under-value case (data-flow-contract.md: the fx server returns ``rates`` as a
# dict). ``up.value`` renders from this, and must never fall through to ``[object Object]``.
_OBJECT_VALUE = {"EUR": 1.0, "USD": 1.1225, "GBP": 0.8512}

_TRACE_OBJECT_VALUE = {
    "agent": "fx-trader",
    "action": {"tool": "fx.read_rate", "class": "read_market_data", "intent": "read the EUR/USD rate",
               "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "allow",
    "reason": "entitled to market_data.fx.read",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "warrant verified"},
               "entitlement": {"ok": True, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9001", "state": "active", "sig_ok": True, "ttl_remaining": 3488},
               "policy": {"ok": True, "detail": "order ok"}},
    "upstream": {"contacted": True, "http_status": 200,
                 "endpoint": "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD",
                 "value": _OBJECT_VALUE, "response_sha256": "f63f64a5e9b3584bd32e0ea70927ea574bea7ef3",
                 "latency_ms": 34.856},
    "receipt_id": "4a8bae2f",
    "action_id": "A-0001",
    "principal": "desk-operator",
    "on_behalf_of": "treasury",
    "timestamp": 1759420000,
    "origin": "operator self-check",
    "incomplete": [],
}


def _api_payloads(*, trace, overview_retry_after=None):
    """The canned ``/api/*`` bodies the page reads on load. ``trace`` may be ``None`` (empty state)."""
    def live_trace(_req):
        return {"trace": trace, "authority_source": "tenet-kernel", "llm_authority": False,
                "mode": "live"}

    def overview(_req):
        if overview_retry_after is not None:
            return {"__status__": 429, "error": "rate limited", "retry_after_s": overview_retry_after}
        return {"mode": "live", "upstream_configured": True}

    return {
        "/api/live-trace": (lambda _r: live_trace(_r)),
        "/api/overview": overview,
        "/api/model-usage": (lambda _r: {"calls_completed": 1, "total_tokens": 42,
                                          "input_tokens": 20, "output_tokens": 22,
                                          "max_latency_ms": 12, "mode": "live",
                                          "model_served": "deepseek-chat"}),
        "/api/security-events": (lambda _r: {"events": []}),
    }

class _Handler(http.server.BaseHTTPRequestHandler):
    """Serve ``index.html`` at ``/`` and the canned API payloads; everything else is a 404."""

    def _route(self):
        payloads = self.server.payloads  # type: ignore[attr-defined]
        path = re.sub(r"\?.*$", "", self.path)
        if path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
        elif path in payloads:
            data = dict(payloads[path](self))
            status = int(data.pop("__status__", 200))
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
        else:
            body = b"{}"
            self.send_response(404)
            self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _route

    def log_message(self, *_args):  # keep pytest output clean
        return


class _Served:
    """A real HTTP server on a free port, torn down afterwards (no external tooling).

    ``handler`` defaults to :class:`_Handler`; a caller that needs to vary its answer per query
    (ACT-6 AC4: ``/api/live-trace?action_id=…``) passes its own subclass.
    """

    def __init__(self, payloads, handler=_Handler):
        self._payloads = payloads
        self._handler = handler
        self._server = None
        self._thread = None

    def __enter__(self) -> str:
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._handler)
        self._server.payloads = self._payloads  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_address[1]}/"

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _rendered_dom(url: str) -> str:
    """The DOM chromium produces after the page's own JS has run (or skip / fail honestly)."""
    if CHROMIUM is None:
        pytest.skip("chromium is absent; the AC3 render cannot be performed (no pass claimed)")
    proc = subprocess.run(
        [CHROMIUM, "--headless", "--no-sandbox", "--disable-gpu",
         "--virtual-time-budget=6000", "--dump-dom", url],
        capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, f"chromium exited {proc.returncode}: {proc.stderr[:400]}"
    return proc.stdout


def _text(dom: str, element_id: str) -> str:
    """The visible text inside the element with ``id``, tags stripped and whitespace collapsed.

    A depth-aware scan is used (not a lazy ``.*?</``) so a container with nested elements is
    captured whole: ``emptyState`` wraps ``<h2>``/``<p>``/``<ol>``, and a lazy match would stop
    at the first inner close tag.
    """
    start = re.search(rf'<[^>]+id="{element_id}"[^>]*>', dom)
    if not start:
        return ""
    inner_start = start.end()
    depth = 1
    pos = inner_start
    for tag in re.finditer(r"<(/?)(\w+)([^>]*)>", dom[inner_start:]):
        if tag.group(2).lower() in ("br", "img", "input", "meta", "link", "hr"):
            continue
        depth += -1 if tag.group(1) == "/" else 1
        if depth == 0:
            pos = inner_start + tag.start()
            break
    text = re.sub(r"<[^>]+>", " ", dom[inner_start:pos])
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def _body_order(dom: str) -> list[str]:
    """The ids of interest, in the order they appear in the rendered body."""
    body = dom.split("<body", 1)[-1]
    markers = []
    for name in ("traceCard", "actionTitle", "techDetails", "traceBody"):
        idx = body.find(f'id="{name}"')
        if idx != -1:
            markers.append((idx, name))
    return [name for _idx, name in sorted(markers)]


# --------------------------------------------------------------------------- the four AC3 points
def test_ac3a_object_value_renders_as_json_never_object_object():
    """(a) a detail whose ``value`` is a JSON object renders as JSON, never ``[object Object]``."""
    payloads = _api_payloads(trace=_TRACE_OBJECT_VALUE)
    with _Served(payloads) as url:
        dom = _rendered_dom(url)
    card = _text(dom, "traceCard")
    assert card, "the action card rendered nothing"
    # The string lives in a JS source comment on the page; what matters is that the RENDERED card
    # never shows it (the raw JSON must be rendered by ``jsonSafe``).
    assert "[object Object]" not in card, f"the card rendered the literal [object Object]: {card!r}"
    assert "1.1225" in card, f"the object value's real content is missing from the card: {card!r}"


def test_ac3b_action_card_is_first_before_any_technical_identifier():
    """(b) the first rendered block is the action card, before any technical identifier."""
    payloads = _api_payloads(trace=_TRACE_OBJECT_VALUE)
    with _Served(payloads) as url:
        dom = _rendered_dom(url)
    order = _body_order(dom)
    assert order, "none of the expected blocks were found in the rendered DOM"
    assert order[0] == "traceCard", f"the first rendered block is not the action card: {order}"
    # The action card owns the first readable line, and no technical identifier precedes it.
    body = dom.split("<body", 1)[-1]
    card_idx = body.find('id="traceCard"')
    for identifier, label in (("W-9001", "run_id/warrant id"), ("A-0001", "action id"),
                              ("4a8bae2f", "receipt id")):
        pos = body.find(identifier)
        assert pos != -1, f"the technical identifier {label} ({identifier}) is not on the page at all"
        assert pos > card_idx, f"the technical identifier {label} appears before the action card"
    # The technical identifiers live under the collapsed disclosure, not in the first layer.
    title = _text(dom, "actionTitle")
    assert "W-9001" not in title and "A-0001" not in title and "4a8bae2f" not in title, \
        f"a technical identifier leaked into the first layer: {title!r}"
    assert "Technical details" in _text(dom, "techDetails") or "Technical details" in dom, \
        "the Technical details disclosure is missing"


def test_ac3c_empty_state_explains_tenet_and_has_no_stale_phrase():
    """(c) the empty state says what TENET does and how to start, with no stale placeholder."""
    payloads = _api_payloads(trace=None)
    with _Served(payloads) as url:
        dom = _rendered_dom(url)
    empty = _text(dom, "emptyState")
    assert empty, "the empty state did not render"
    lowered = empty.lower()
    assert "no action yet" not in lowered, f"stale empty-state phrase 'No action yet': {empty!r}"
    assert "nothing to show" not in lowered, f"stale empty-state phrase 'Nothing to show': {empty!r}"
    # It must say what TENET does AND how to start a real action.
    assert "tenet" in lowered, f"the empty state never says what TENET is: {empty!r}"
    assert "warrnt_upstream" in lowered or "tool server" in lowered, \
        f"the empty state does not say how to start: {empty!r}"
    assert "run" in lowered, f"the empty state offers no way to start: {empty!r}"


def test_ac3d_rate_limited_state_reads_as_waiting_with_real_retry_after():
    """(d) a 429 with ``retry_after_s`` renders ``Rate limited · retrying in Ns`` with the real N."""
    payloads = _api_payloads(trace=None, overview_retry_after=7)
    with _Served(payloads) as url:
        dom = _rendered_dom(url)
    page = _text(dom, "selfCheckMsg") or dom
    assert "Rate limited · retrying in 7s" in page, \
        f"the rate-limited wording/retry-after is wrong: {page!r}"
    assert "Rate limited — retry in" not in dom, "the old rate-limit wording survived"
    # It reads as waiting, not as a failure.
    assert "wait" in page.lower() and "kernel" in page.lower(), \
        f"the rate-limited state does not read as waiting: {page!r}"
    assert PAGE.count('"Rate limited · retrying in "') == 1 or \
        "Rate limited · retrying in " in PAGE, "the page no longer carries the exact wording"


# --------------------------------------------------- ACT-7b T6: the page invents no operator
def test_t6_index_html_fabricates_no_operator_identity_for_a_control_route():
    """ACT-7b T6 - the page never sends an invented `by` to a control route.

    A control action must carry the identity the human declared. A hardcoded placeholder such as
    ``{by:"operator"}`` is a fabricated decision-maker, so it must not appear anywhere in the
    served page — not on the revoke route, not on the approve/deny route.
    """
    # no literal `by:"..."` constant of any kind is sent as the control body
    fabricated = re.findall(r'by\s*:\s*"[^"$+]*"', PAGE)
    assert not fabricated, "the page still sends a fabricated operator identity: %r" % fabricated
    # the declared-name seam exists and both doors read it
    assert "operatorName" in PAGE, "the page has no operator-name field to carry the real identity"
    assert "declaredOperator" in PAGE, "the page does not read a declared operator name"
    assert PAGE.count("declaredOperator()") >= 2, \
        "both the revoke and the approve/deny doors must use the declared name"
    # and no control body is attributed to a made-up placeholder name
    assert '"operator"' not in PAGE, "the literal placeholder identity `\"operator\"` is still present"


# --------------------------------------------------------- ACT-6 AC3/AC4: the card follows selection
# Two actions on the record, same resource, two agents, two verdicts (the screen's whole point).
# The parameterless call returns the LATEST (the ALLOW); the query call returns THAT action. The
# test drives the page's real ``selectEvent`` in a real chromium and asserts the headline card
# repaints from the selected record - so it FAILS if the card keeps rendering the latest trace.
_ALLOW_ACTION_ID = "A-0001"
_DENY_ACTION_ID = "A-0002"

_ALLOW_TRACE = {
    "agent": "fx-trader",
    "action": {"tool": "fx.read_rate", "class": "read_market_data", "intent": "read the EUR/USD rate",
               "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "allow",
    "reason": "entitled to market_data.fx.read",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "desk-operator"},
               "entitlement": {"ok": True, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9001", "state": "active", "sig_ok": True, "ttl_remaining": 3488},
               "policy": {"ok": True, "detail": "order ok"}},
    "upstream": {"contacted": True, "http_status": 200,
                 "endpoint": "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD",
                 "value": {"EUR": 1.0, "USD": 1.1225}, "response_sha256": "f63f64a5e9b3584bd32e0ea70927ea574bea7ef3",
                 "latency_ms": 34.856},
    "receipt_id": "a7203811",
    "action_id": _ALLOW_ACTION_ID,
    "principal": "desk-operator",
    "on_behalf_of": "treasury",
    "timestamp": 1759420000,
    "origin": "operator self-check",
    "incomplete": [],
}

_DENY_TRACE = {
    "agent": "support-copilot",
    "action": {"tool": "fx.read_rate", "class": "read_market_data", "intent": "read the EUR/USD rate",
               "args": {"base": "EUR", "symbols": "USD"}},
    "decision": "deny",
    "reason": "no entitlement to market_data.fx.read",
    "decided_by": "tenet-kernel",
    "checks": {"identity": {"ok": True, "detail": "support-ops"},
               "entitlement": {"ok": False, "right": "market_data.fx.read"},
               "warrant": {"id": "W-9002", "state": "active", "sig_ok": True, "ttl_remaining": 120},
               "policy": {"ok": False, "detail": "no entitlement"}},
    "upstream": {"contacted": False, "http_status": None, "endpoint": None, "value": None,
                 "response_sha256": None, "latency_ms": None},
    "receipt_id": "f617d705",
    "action_id": _DENY_ACTION_ID,
    "principal": "support-ops",
    "on_behalf_of": "service-desk",
    "timestamp": 1759420001,
    "origin": "agent call",
    "incomplete": [],
}


def _feed_event(trace):
    """The ``/api/security-events`` row for a trace - ``event_id`` is the ``action_id`` the page
    hands to ``selectEvent`` and therefore to ``/api/live-trace?action_id=…``."""
    return {"event_id": trace["action_id"], "run_id": trace["action_id"], "agent": trace["agent"],
            "actor": trace["agent"], "intent": trace["action"]["intent"], "resource": trace["action"]["tool"],
            "tool": trace["action"]["tool"], "action_class": trace["action"]["class"],
            "warrant": trace["checks"]["warrant"]["id"], "warrant_state": trace["checks"]["warrant"]["state"],
            "policy": trace["checks"]["policy"]["detail"], "decision": trace["decision"],
            "state": "decided", "reason": trace["reason"],
            "upstream_contacted": trace["upstream"]["contacted"],
            "upstream_call_id": None,
            "execution_result": trace["upstream"] if trace["upstream"]["contacted"] else None,
            "receipt_id": trace["receipt_id"], "model_trace_id": None, "model_requested": None,
            "model_served": None, "boundary_attempts": 0, "authority_source": "tenet-kernel",
            "llm_authority": False, "timestamp": trace["timestamp"]}


def _selection_payloads(*, select_event_id):
    """Canned API bodies for two events, plus a driver that clicks one row after the page loads.

    ``/api/live-trace`` (no parameter) returns the LATEST (the ALLOW). ``?action_id=`` returns THAT
    action's trace. The driver is served only to the test browser - the repo's ``index.html`` is
    untouched by it.
    """
    events = [_feed_event(_ALLOW_TRACE), _feed_event(_DENY_TRACE)]  # newest first: ALLOW, DENY
    by_id = {_ALLOW_ACTION_ID: _ALLOW_TRACE, _DENY_ACTION_ID: _DENY_TRACE}

    def live_trace(req):
        action_id = (getattr(req, "query", {}) or {}).get("action_id")
        if action_id:
            return {"__status__": 200, "trace": by_id.get(action_id), "authority_source": "tenet-kernel",
                    "llm_authority": False, "mode": "live"}
        return {"trace": _ALLOW_TRACE, "authority_source": "tenet-kernel", "llm_authority": False,
                "mode": "live"}

    driver = (f"<script>window.addEventListener('load',function(){{"
              f"setTimeout(function(){{selectEvent({select_event_id!r})}},1500)}});</script>")
    payloads = {
        "/api/live-trace": live_trace,
        "/api/overview": (lambda _r: {"mode": "live", "upstream_configured": True}),
        "/api/model-usage": (lambda _r: {"calls_completed": 2, "total_tokens": 42, "input_tokens": 20,
                                          "output_tokens": 22, "max_latency_ms": 12, "mode": "live",
                                          "model_served": "deepseek-chat"}),
        "/api/security-events": (lambda _r: {"count": len(events), "events": events, "mode": "live"}),
        "__driver__": driver,
    }
    return payloads


class _QueryHandler(_Handler):
    """The test handler: it keeps the query string so ``?action_id=`` reaches the payload fn, and
    it appends the selection driver to the served page."""

    def _route(self):
        parsed = urllib.parse.urlparse(self.path)
        self.query = dict(urllib.parse.parse_qsl(parsed.query))  # type: ignore[attr-defined]
        payloads = self.server.payloads  # type: ignore[attr-defined]
        if parsed.path in ("/", "/index.html"):
            body = (PAGE + payloads["__driver__"]).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
        elif parsed.path in payloads:
            data = dict(payloads[parsed.path](self))
            status = int(data.pop("__status__", 200))
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
        else:
            body = b"{}"
            self.send_response(404)
            self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _route


def test_ac6_card_follows_the_selected_record_not_the_latest():
    """AC3/AC4: selecting a record repaints the headline card from THAT record.

    The latest action is the ALLOW; the DENY is earlier. The driver selects the DENY row. If the
    card keeps rendering the latest trace (the defect), the card still shows the ALLOW and this
    test fails - which is exactly how the red proof is taken.
    """
    payloads = _selection_payloads(select_event_id=_DENY_ACTION_ID)
    with _Served(payloads, handler=_QueryHandler) as url:
        dom = _rendered_dom(url)

    title = _text(dom, "actionTitle")
    card = _text(dom, "traceCard")
    assert card, "the action card rendered nothing"
    # The selected DENY is on the card: its agent, its verdict, its boundary result, its receipt.
    assert "support-copilot" in title, f"the headline card did not follow the selected record: {title!r}"
    assert "fx-trader" not in title, f"the card still shows the latest (ALLOW) action: {title!r}"
    assert "DENY" in card, f"the selected DENY verdict is not on the card: {card!r}"
    assert "NOT CONTACTED" in card, f"the selected boundary result is not on the card: {card!r}"
    assert "f617d705" in card, f"the selected receipt is not on the card: {card!r}"
    # And the ALLOW's receipt must NOT be shown as the selected record's receipt.
    assert "a7203811" not in card, f"the card shows the latest action's receipt, not the selection: {card!r}"


def test_ac6_card_defaults_to_the_latest_action_on_load():
    """AC3: with no selection the default is still the latest action (the ALLOW here)."""
    payloads = _selection_payloads(select_event_id=_ALLOW_ACTION_ID)
    payloads["__driver__"] = ""  # nothing is clicked, so the card must show the latest trace
    with _Served(payloads, handler=_QueryHandler) as url:
        dom = _rendered_dom(url)
    title = _text(dom, "actionTitle")
    card = _text(dom, "traceCard")
    assert "fx-trader" in title, f"the default card is not the latest action: {title!r}"
    assert "a7203811" in card, f"the latest action's receipt is missing from the default card: {card!r}"


def test_ac6e_card_prints_the_upstream_url_once_escaped_never_double_escaped():
    """ACT-6e: the card prints the upstream URL with a plain ``&`` in every row - never ``&amp;``.

    The endpoint the kernel recorded carries a plain ``&`` (``...?base=EUR&symbols=USD``). The
    "Where the data would go" row escapes it once for HTML insertion, so the browser decodes it
    back to ``&``. The "Did it happen" outcome row built its sub-line as already-escaped HTML and
    then escaped that whole string a SECOND time, so the entity survived to ``textContent`` as the
    literal four characters ``&amp;`` - the card disagreed with the URL the kernel actually called.
    This renders the card from a real chromium and asserts on the visible text: the URL must read
    ``base=EUR&symbols=USD`` and the card text must carry no literal ``&amp;``.
    """
    endpoint = "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD"
    trace = json.loads(json.dumps(_ALLOW_TRACE))  # a canned allow whose endpoint has the plain &
    trace["upstream"] = {**trace["upstream"], "endpoint": endpoint, "contacted": True}
    payloads = _api_payloads(trace=trace)
    with _Served(payloads) as url:
        dom = _rendered_dom(url)

    card = _text(dom, "traceCard")
    assert card, "the action card rendered nothing"
    # (a) the URL is printed with a plain & exactly as the kernel recorded it.
    assert "base=EUR&symbols=USD" in card, \
        f"the card did not print the upstream URL with a plain '&': {card!r}"
    # (b) the card text carries no literal entity: it was escaped and then assigned as text.
    assert "&amp;" not in card, \
        f"the card leaked a double-escaped entity into its text: {card!r}"
    # The URL appears in more than one row (destination and outcome); both must agree, unescaped.
    assert card.count("base=EUR&symbols=USD") >= 2, \
        f"the URL is not printed identically in every row that shows it: {card!r}"



# ------------------------------------------- ACT NEW-AC7: the rail is a way in, and it says why it stops
def _chain_payload(receipt):
    chain = {"ok": True, "length": 1, "head": receipt,
             "proof": {"correlation": [{"receipt_id": receipt}]}}
    return {"chain": chain}


def test_rail_beats_open_their_evidence_and_the_stall_is_named():
    """Every beat is a control, and a WITNESS that cannot advance names the reason.

    The trace holds a receipt, but this server serves no ``/api/state``, so the chain the page
    read knows nothing about it. The rail must not look frozen: the note says the chain does not
    list the receipt and offers the chain as the way to re-read it.
    """
    payloads = _api_payloads(trace=dict(_TRACE_OBJECT_VALUE))
    with _Served(payloads) as url:
        dom = _rendered_dom(url)
    beats = [b for b in re.findall(r'<div class="beat"[^>]*>', dom) if "${k}" not in b]
    assert len(beats) == 7, f"the rail did not render seven beats: {beats!r}"
    assert all('role="button"' in b for b in beats), f"a beat is not a control: {beats!r}"
    assert all("cursor:pointer" in b for b in beats), f"a beat does not look clickable: {beats!r}"
    assert all('data-beat=' in b for b in beats), beats
    note = _text(dom, "railNote")
    assert "does not list" in note, f"the stall is not named: {note!r}"
    assert "chain" in note.lower(), f"the stall names no way out: {note!r}"


def test_rail_reaches_the_proof_when_the_chain_lists_the_receipt():
    """The same trace WITH the chain listing the receipt must advance past WITNESS.

    Positive half of the pair: nothing about the stall sentence may appear when the proof is
    actually in the chain the page read.
    """
    receipt = _TRACE_OBJECT_VALUE["receipt_id"]
    payloads = _api_payloads(trace=dict(_TRACE_OBJECT_VALUE))
    payloads["/api/state"] = (lambda _r, _c=_chain_payload(receipt): _c)
    with _Served(payloads) as url:
        dom = _rendered_dom(url)
    note = _text(dom, "railNote")
    assert "does not list" not in note, f"the chain lists the receipt yet the rail stalls: {note!r}"
    assert "You are at" in note, note
    assert "PROVE" in note or "WIN" in note, f"the rail never reached the proof: {note!r}"
