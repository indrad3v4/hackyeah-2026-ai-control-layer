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
    """A real HTTP server on a free port, torn down afterwards (no external tooling)."""

    def __init__(self, payloads):
        self._payloads = payloads
        self._server = None
        self._thread = None

    def __enter__(self) -> str:
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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

