#!/usr/bin/env python
"""The REAL upstream behind the gate: a live MCP server backed by Frankfurter.

This replaces the fixture MCP server (``node/scripts/mcp_fixture_server.py``) for the
deliverable. The difference that matters for the proof is *where the truth lives*:

* every tool call performs a real HTTPS request to the European Central Bank reference
  rates published by Frankfurter (``https://api.frankfurter.dev/v1/latest``);
* every received call is appended to this server's OWN JSONL access log (``--log``),
  including the caller's explicit ``call_id``;
* the log, not the kernel's counter, is what a proof reads to decide whether an action
  actually reached the upstream. The node keeps its own count; this process is the other
  side, so "the denied call never reached upstream" is a fact about *this* log.

The process is deliberately separate from the control plane / kernel: it is started on its
own port and the node is only told its URL (``WARRNT_UPSTREAM``).

Usage::

    python -m upstream.frankfurter_server --port 8210 --log state/upstream/calls.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

# The public, key-less reference-rate endpoint. One URL, one source of truth.
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
DEFAULT_BASE = "EUR"
DEFAULT_SYMBOLS = "USD"

_LOG_PATH = os.environ.get("FRANKFURTER_LOG", "")
# The last raw exchange-rate payload this process actually fetched from Frankfurter. Kept
# in-process so a tool call returns real data and a proof can show the same rates on both
# sides without a second network hop.
_LAST_RATE: dict = {}

# The egress counter (contract T1/T3). This process - the far side of the gate - is the only
# writer, and it counts a request at the exact moment it is about to leave the box:
# ``sent`` is incremented immediately BEFORE ``httpx`` is handed the request, ``completed``
# immediately AFTER the response body has been read. A denied or held action never reaches
# ``_fetch_rate`` at all, so ``sent`` cannot move for it. Read back over ``/stats`` so a
# proof can assert "nothing left the box" against the boundary itself, not against a claim
# made by the layer that made the decision.
_EGRESS: dict[str, int] = {"sent": 0, "completed": 0, "failed": 0}


def _record(call_id: str, tool: str, args: dict, outcome: str,
            payload: dict | None = None, error: str = "", crossing: dict | None = None) -> None:
    """Append one line to this server's own access log.

    The ``call_id`` is written verbatim: it is the caller's explicit correlation handle, so
    an auditor can line up the kernel's action/receipt with the upstream's own record. When
    the call crossed the boundary, ``crossing`` carries exactly what left and what came
    back (endpoint, status, digest, latency, value) - recorded at the far side, so it cannot
    be confused with the layer's own report.
    """
    if not _LOG_PATH:
        return
    entry = {
        "ts": round(time.time(), 6),
        "call_id": call_id or "",
        "tool": tool,
        "args": args,
        "pid": os.getpid(),
        "outcome": outcome,
        "error": error[:200],
        "rate_fetched": bool(payload),
    }
    if crossing:
        entry["crossing"] = crossing
    path = Path(_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
        fh.flush()


def _fetch_rate(base: str, symbols: str) -> dict:
    """A real HTTPS call to Frankfurter. Raises on a non-2xx so a failure is a failure.

    The egress counter moves here and only here: ``sent`` is bumped in the same statement
    that hands the request to the transport, ``completed`` once the body has been read. The
    digest is taken over the bytes actually received, so the proof can re-hash the same
    response and get the same value - the rate is never re-typed by hand.
    """
    with httpx.Client(timeout=10.0) as client:
        request = client.build_request("GET", FRANKFURTER_URL,
                                       params={"base": base, "symbols": symbols})
        started = time.time()
        # About to cross the boundary: count it before a byte can leave.
        _EGRESS["sent"] += 1
        try:
            resp = client.send(request)
            raw = resp.content
            resp.raise_for_status()
        except Exception:
            _EGRESS["failed"] += 1
            raise
        # The reply is home: count it done.
        _EGRESS["completed"] += 1
        latency_ms = round((time.time() - started) * 1000.0, 3)
        return {"raw": resp.text, "status": resp.status_code, "url": str(request.url),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "latency_ms": latency_ms, "json": resp.json()}


def build_server() -> MCPServer:
    server = MCPServer(name="tenet-frankfurter-upstream", version="1.0.0")

    @server.tool(name="fx.read_rate",
                 description="live ECB reference rate for a base/symbols pair (real Frankfurter)")
    def fx_read_rate(call_id: str = "", base: str = DEFAULT_BASE,
                     symbols: str = DEFAULT_SYMBOLS) -> dict:
        args = {"base": base, "symbols": symbols, "call_id": call_id}
        try:
            fetched = _fetch_rate(base, symbols)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised as an MCP error
            _record(call_id, "fx.read_rate", args, outcome="error",
                    error=f"{type(exc).__name__}: {exc}")
            raise
        payload = fetched["json"]
        _LAST_RATE.clear()
        _LAST_RATE.update(payload)
        rate = (payload.get("rates") or {}).get(symbols)
        body = {"tool": "fx.read_rate", "call_id": call_id, "ok": True,
                "base": payload.get("base", base), "date": payload.get("date"),
                "symbol": symbols, "value": rate, "rates": payload.get("rates", {}),
                "endpoint": fetched["url"], "http_status": fetched["status"],
                "response_sha256": fetched["sha256"], "latency_ms": fetched["latency_ms"],
                "response_bytes": fetched["bytes"],
                "source": FRANKFURTER_URL}
        _record(call_id, "fx.read_rate", args, outcome="ok", payload=payload,
                crossing={"endpoint": fetched["url"], "http_status": fetched["status"],
                          "response_sha256": fetched["sha256"],
                          "latency_ms": fetched["latency_ms"], "value": rate})
        return body

    @server.tool(name="fx.last",
                 description="the last rate this upstream fetched, without a new network call")
    def fx_last(call_id: str = "") -> dict:
        args = {"call_id": call_id}
        if not _LAST_RATE:
            _record(call_id, "fx.last", args, outcome="empty", payload={})
            return {"tool": "fx.last", "call_id": call_id, "ok": False,
                    "error": "no rate fetched yet"}
        _record(call_id, "fx.last", args, outcome="ok", payload=_LAST_RATE)
        return {"tool": "fx.last", "call_id": call_id, "ok": True,
                "base": _LAST_RATE.get("base"), "date": _LAST_RATE.get("date"),
                "rates": _LAST_RATE.get("rates", {}), "source": FRANKFURTER_URL}

    @server.tool(name="fx.audit_note",
                 description="attach a desk note to the audit trail (never a new network call)")
    def fx_audit_note(call_id: str = "", desk: str = "",
                      fields: list[str] | None = None) -> dict:
        """A write-shaped tool with no network egress at all.

        It exists so the redaction case (T4) has something a rule can name. The payload is
        the caller's declared ``fields`` list - the same shape ``crm.read`` uses - so the
        contract is the mirror's own: a rule with ``redact=["fields"]`` strips the named
        personal fields out of this list *before* the upstream is handed the request. What
        this log received is therefore the proof: the personal field is simply not in it.
        Nothing here calls Frankfurter, so the redacted case is shown by what arrived, not
        by the absence of a rate.
        """
        received = list(fields or [])
        args = {"call_id": call_id, "desk": desk, "fields": received}
        _record(call_id, "fx.audit_note", args, outcome="ok")
        return {"tool": "fx.audit_note", "call_id": call_id, "ok": True,
                "desk": desk, "received_fields": received}


    @server.custom_route("/stats", methods=["GET"])
    async def stats(_request: Request) -> JSONResponse:
        """The boundary's own egress counter (T1/T3) - read by the proof, written by nobody else.

        ``sent`` moves only in ``_fetch_rate`` immediately before the request is handed to
        the transport. A denied or held action therefore leaves it untouched, and the proof
        asserts exactly that: same ``sent`` before and after a refusal.
        """
        return JSONResponse({**_EGRESS, "pid": os.getpid(),
                             "log": _LOG_PATH, "rate_cached": bool(_LAST_RATE)})

    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Real Frankfurter-backed MCP upstream.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8210)
    parser.add_argument("--log", default="", help="JSONL access log, one line per call")
    args = parser.parse_args()

    global _LOG_PATH
    _LOG_PATH = args.log
    if _LOG_PATH:
        os.makedirs(os.path.dirname(os.path.abspath(_LOG_PATH)), exist_ok=True)

    server = build_server()
    server.run(transport="streamable-http", host=args.host, port=args.port,
               json_response=True, stateless_http=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
