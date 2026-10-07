"""The kernel boundary: import the mirrored enforcement kernel as a library.

The mirror (`node/warrnt`) is shipped inside this repository, so the control plane reaches
the authority by import - there is no HTTP hop to a second process and therefore no second
decision path. Everything the control plane knows about decisions comes from here.

Two rules this module exists to enforce:

* the control plane may **read** kernel state and **call** kernel decision functions;
* the control plane may **never** decide on its own. When the kernel does not answer, the
  caller gets :class:`KernelUnavailable` and must refuse - never a silent allow.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_DIR = REPO_ROOT / "node"


class KernelUnavailable(RuntimeError):
    """The enforcement kernel could not produce a decision. Callers must fail closed."""


class SeparationOfDutiesRefused(RuntimeError):
    """The named person may not decide a request they themselves are the actor of.

    Declared here, in the control plane's own boundary layer, because the rule belongs to
    TENET's policy layering. The mirror carries no such rule and does not export such a name -
    importing one from ``warrnt.controlplane`` would be a reference to something that does not
    exist, so the check lives where it is actually enforced.
    """


def _ensure_mirror_on_path() -> None:
    """Put the mirrored kernel package on ``sys.path`` once, at import time.

    ``node/`` is added (not ``node/warrnt``) so ``import warrnt`` resolves to the mirror.
    Idempotent and cheap: repeated imports do not grow ``sys.path``.
    """
    node = str(NODE_DIR)
    if node not in sys.path:
        sys.path.insert(0, node)


def load_kernel() -> Any:
    """Import the enforcement kernel from the mirror.

    Raises :class:`KernelUnavailable` if the mirror is missing or unimportable - the control
    plane would rather refuse every request than run without an authority.
    """
    _ensure_mirror_on_path()
    try:
        from warrnt.api import build_proxy  # type: ignore import-not-found
        from warrnt.config import Settings  # type: ignore import-not-found
    except Exception as exc:  # noqa: BLE001 - any import failure is unavailability
        raise KernelUnavailable(
            f"enforcement kernel mirror is not importable from {NODE_DIR}: "
            f"{type(exc).__name__}: {exc}") from exc
    return {"build_proxy": build_proxy, "Settings": Settings}


def _dev() -> bool:
    return os.environ.get("WARRNT_DEV", "").strip() in ("1", "true", "yes")


def _refresh(warrant: Any, now: float) -> str:
    from warrnt.warrants import refresh_state  # type: ignore import-not-found

    return refresh_state(warrant, now)


# ============================================== ACT-2 §2: the entitlement register
# A warrant grants authority to act; it is not a grant of data. This register answers the
# second question - which data an agent holds the right to read - and it lives with the
# operator, not in the mirror: the kernel enforces it, the register states it. A tool the
# register does not file is not gated here (the mirrored taxonomy may know tools the
# operator holds no opinion about).
ENTITLEMENT_OF_TOOL: dict[str, str] = {
    "crm.read": "crm.tickets.read",
    "fx.read_rate": "market_data.fx.read",
    "fx.last": "market_data.fx.read",
    "equity.read_snapshot": "market_data.equity.read",
}

ENTITLEMENTS: dict[str, set[str]] = {
    "support-copilot": {"crm.tickets.read"},
    "fx-trader": {"market_data.fx.read"},
    "fx-auditor": {"market_data.fx.read"},
}


def missing_entitlement(agent_id: str, tool: str) -> str:
    """The right the register withholds, or ``""`` when it grants it (or holds no opinion).

    A tool with no filed right is not silently entitled: it is simply not this gate's
    business, and the mirrored order decides it as before.
    """
    right = ENTITLEMENT_OF_TOOL.get(tool, "")
    if not right:
        return ""
    return "" if right in ENTITLEMENTS.get(agent_id, set()) else right


# The six rungs of the kernel's own ladder, mirrored here ONLY to recognise a class the
# evaluation already named - never to classify an act. The taxonomy itself stays in the
# kernel (``node/warrnt/actions.py``); this set is how the composer tells a real class name
# from any other token that happens to follow the word "class". A token not in this set is
# not accepted, so the fallback can never invent a class the evaluation did not name.
_ACTION_CLASS_NAMES = ("observe", "read_personal", "draft", "write_reversible",
                       "irreversible", "authorize")


def _class_from_reason(reason: Optional[str]) -> Optional[str]:
    """The action class the DECISION's own evaluation named, or ``None``.

    The evaluated decision evidence is the kernel's ``reason`` string; its class phrase is
    ``class <name>`` (e.g. ``... · class observe`` / ``class irreversible · ... · the machine
    prepares, a person decides``). This reads the SAME fact the why-line renders, so the
    reaches line and the why-line cannot disagree. Only a token that is a real rung of the
    kernel's ladder is accepted - a stray "class" with anything else after it is ignored, so
    nothing is ever invented. (AGENTS.md D3: one source of truth; D12: claim only what ran.)
    """
    if not reason:
        return None
    for token in re.findall(r"\bclass\s+([a-z_]+)", str(reason)):
        if token in _ACTION_CLASS_NAMES:
            return token
    return None


# R1, verbatim (``node/warrnt/actions.py``, the taxonomy module): an unclassified act is refused.
# The stream view quotes this sentence rather than leaving a blank where a class should be, so a
# row the layer refused to classify cannot read as "no opinion recorded".
R1_REFUSAL = ("no action class for this tool · the layer refuses what it "
              "cannot classify")


def stream_row(action: dict[str, Any], taxonomy: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One row of the stream: the action's own facts, its class, and the taxonomy's decider line.

    ``taxonomy`` is the kernel's own table keyed by class name - the same ``actions`` listing
    ``/api/state`` publishes (``class_listing()``: class, decider, decider_text, meaning, tools).
    The class is read off the ROW, never inferred from the tool name here, so this view can only
    repeat a classification the kernel already made. A row carrying no class is reported as
    unclassified and is given R1's refusal sentence word for word: the closed set is closed, and
    an act outside it is refused rather than left blank.

    No adjective is added and no field is invented: every key below is either the action row's own
    value or the taxonomy's own string. (AGENTS.md D3 one source of truth, D12 claim only what ran.)
    """
    cls = str(action.get("action_class") or "")
    entry = taxonomy.get(cls)
    return {
        "action_id": action.get("action_id"),
        "run_id": action.get("run_id"),
        "ts": action.get("ts"),
        "agent": action.get("agent"),
        "tool": action.get("tool"),
        "class": (entry or {}).get("class"),
        "decider": (entry or {}).get("decider"),
        # A classified row names who decides it ("the node decides", "a person decides · the machine
        # prepares only"). An unclassified one has no decider at all - only R1's refusal.
        "decider_text": (entry or {}).get("decider_text") or R1_REFUSAL,
        "meaning": (entry or {}).get("meaning"),
        "decision": action.get("decision"),
        "state": action.get("state"),
        "reason": action.get("reason"),
        # The lifecycle facts AC5's fourth state needs: when the state was resolved and by whom.
        "decided_ts": action.get("decided_ts"),
        "decided_by": action.get("decided_by"),
        "unclassified": entry is None,
    }


class Kernel:
    """A thin, read-only-plus-decide handle on the enforcement kernel.

    It exposes only what the control plane needs: state projections and the decision calls
    (``intercept``, ``resolve_hold``, ``revoke``). There is no method here that allows,
    redacts or contacts an upstream by itself - only the kernel does that.
    """

    def __init__(self, proxy: Any):
        self.proxy = proxy

    # ------------------------------------------------------------------ reads
    def state(self, limit: int = 60) -> dict[str, Any]:
        return self.proxy.state(limit=limit)

    def actions(self, limit: int = 60) -> list[dict[str, Any]]:
        return self.proxy.actions.listing(limit=limit)

    def pending(self, limit: int = 60) -> list[dict[str, Any]]:
        return self.proxy.actions.listing(state="pending", limit=limit)

    def stream(self, limit: int = 20) -> list[dict[str, Any]]:
        """The last N actions, judged: each row's own class + the taxonomy's decider line.

        This is the one gap the brief names: the kernel HOLDS the classification of every action
        it decided and the taxonomy says who decides each class, but nothing joined the two on the
        way out. The join happens here, once, so every surface (the console panel, the observer
        page, an answer) reads the same judgement instead of re-deriving it and drifting.

        The taxonomy comes from ``self.state()["actions"]`` - the node's own ``class_listing()`` -
        so the decider lines cannot be re-worded here (D3). ``stream_row`` reads the class off the
        row the kernel recorded; a row with no class is refused with R1's sentence, never blank.
        """
        limit = max(1, min(int(limit or 20), 200))
        taxonomy = {str(c.get("class")): c for c in (self.state(limit=1).get("actions") or [])}
        return [stream_row(a, taxonomy) for a in self.actions(limit)]

    def action(self, action_id: str) -> Optional[dict[str, Any]]:
        """One action, plus the identity facts from the actor's own agent record.

        No field is invented: ``requester`` is the identity the ledger recorded as having
        asked for the act, and the delegation facts are read from the agent the order was
        issued to. An action whose agent is unknown carries empty strings, not guesses.
        """
        a = self.proxy.actions.get(action_id)
        if a is None:
            return None
        row = a.public()
        agent = self.proxy.agents.get(a.agent)
        row["requester"] = a.actor or a.agent
        row["principal"] = getattr(agent, "principal", "") or ""
        row["acting_on_behalf_of"] = getattr(agent, "on_behalf_of", "") or ""
        return row

    # --------------------------------------- a run's actions, from the PERSISTENT store (T9/§9)
    # The in-memory action ledger is bounded (MAX_ACTIONS=200): reading it for a run returns an
    # empty proof once the run is older than the window, even though every action is appended to
    # the ledger on disk. That silent empty is the data loss issue #38 names. These two reads let
    # a caller resolve a run from the durable store, and say WHICH store answered, so "no proof
    # exists" (an unknown run) is never confused with "not in the last 200" (an old run).
    def actions_for_run(self, run_id: str, *, window: int = 200) -> "tuple[list[dict[str, Any]], str]":
        """Resolve one ``run_id``'s actions, preferring the in-memory window then the ledger.

        Returns ``(rows, source)`` where ``source`` is:

        * ``"window"`` - the run's actions are in the in-memory window (the fast path, unchanged);
        * ``"store"``  - the run is older than the window; its rows were read from the persistent
          actions ledger on disk (nothing is cached, so memory stays bounded);
        * ``"none"``   - no action for this run exists in the window OR the ledger: an absent run,
          distinct from an old one that lives only beyond the window.
        """
        rid = str(run_id or "")
        rows = [a for a in self.actions(limit=window) if str(a.get("run_id") or "") == rid]
        if rows:
            return rows, "window"
        older = self._actions_from_ledger(rid)
        if older:
            return older, "store"
        return [], "none"

    def _actions_from_ledger(self, run_id: str) -> list[dict[str, Any]]:
        """Read the persistent actions ledger for one run's rows.

        The ledger is the same ``actions.jsonl`` the mirror appends every action to; reading it
        here is what makes an older run's proof resolvable instead of silently empty. A missing
        or unreadable ledger is an empty list - an absent row is never invented (AGENTS.md D12).
        """
        path = getattr(self.proxy, "_actions_path", None) or str(
            self._state_dir() / "actions.jsonl")
        rows: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue  # a half-written last line is skipped, never raised
                    if str(row.get("run_id") or "") == str(run_id or ""):
                        rows.append(row)
        except OSError:
            return []
        return rows

    def registry_recent(self, limit: int = 60) -> list[dict[str, Any]]:
        return self.proxy.registry.recent(limit)

    def warrants(self) -> list[dict[str, Any]]:
        p = self.proxy
        out = []
        for w in p.warrants.values():
            out.append({
                "id": w.id, "agent": w.agent, "role": w.role, "scope": w.scope,
                "ttl": int(round(max(0.0, w.ttl - (p._now() - w.issued)))),
                "ttl0": w.ttl, "issuer": w.issuer,
                "state": _refresh(w, p._now()), "sig": w.sig,
                "sig_ok": p.issuer.signature_ok(w),
            })
        return out

    def agents(self, dev: bool = False) -> list[dict[str, Any]]:
        p = self.proxy
        out = []
        for a in p.agents.values():
            row = {"id": a.id, "role": a.role, "warrant": a.warrant,
                   "state": a.state, "last": a.last,
                   # ACT-2 §1/§2: the identity/delegation facts and the held entitlements, so
                   # the operator projection says who acts, for whom, and on what right - the
                   # same fields the node's own /api/agents serves.
                   "principal": getattr(a, "principal", ""),
                   "on_behalf_of": getattr(a, "on_behalf_of", ""),
                   "entitlements": list(getattr(a, "entitlements", []) or []),
                   "scope": list(getattr(a, "scope", []) or [])}
            if dev:
                row["token"] = a.token
            out.append(row)
        return out

    # ------------------------------------------------- ACT-2 §4: evidence, not assertion
    def upstream_log(self, limit: int = 200, tool: str = "") -> dict[str, Any]:
        """The real upstream's own access log, read from disk (the other side's record).

        Delegates to the node's one implementation of the read (``warrnt.api.upstream_log_path``
        + the same JSONL parse), so the control plane cannot show a different log than the
        node. When no log is configured the answer carries ``exists: false`` - never a fake
        empty proof (D12).
        """
        from warrnt.api import _sha256_of, upstream_log_path  # type: ignore import-not-found

        raw_path = upstream_log_path()
        entries: list[dict[str, Any]] = []
        if raw_path:
            path = Path(raw_path)
            if path.exists():
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if tool and row.get("tool") != tool:
                            continue
                        entries.append(row)
        exists = bool(raw_path) and Path(raw_path).exists()
        return {"path": raw_path, "exists": exists, "total": len(entries),
                "sha256": _sha256_of(raw_path),
                "entries": entries[-max(0, limit):] if limit else entries}

    def attest_non_contact(self, action_id: str) -> dict[str, Any]:
        """Prove from the record that an action did NOT reach the upstream (ACT-2 §4).

        Assembled from facts the kernel already holds: the action's ``upstream_contacted``
        flag, its ``boundary_attempts`` counter, and the upstream's own access log read for
        the action's call_id. The result carries ``status`` (200 / 404 / 409) so the caller
        maps it without a second rule; the control plane never decides contact, it only
        reports what the record says.
        """
        p = self.proxy
        action = p.actions.get(action_id) if action_id else None
        if action is None:
            return {"status": 404, "error": f"unknown action {action_id}",
                    "hint": "GET /api/actions lists the ledger"}
        if action.upstream_contacted:
            return {"status": 409, "contacted": True, "action_id": action.action_id,
                    "boundary_attempts": action.boundary_attempts,
                    "note": "the record shows this action crossed the egress boundary - it may "
                            "not be attested as non-contact"}
        log = self.upstream_log(limit=0)
        entries = log.get("entries") or []
        count_before = len(entries)
        call_ids = {row.get("call_id") for row in entries if row.get("call_id")}
        count_after = count_before   # reading a file contacts nothing
        if action.action_id in call_ids:
            return {"status": 409, "contacted": True, "action_id": action.action_id,
                    "count_before": count_before, "count_after": count_after,
                    "boundary_attempts": action.boundary_attempts,
                    "note": "the upstream's own access log names this action's call_id"}
        return {"status": 200, "contacted": False, "action_id": action.action_id,
                "count_before": count_before, "count_after": count_after,
                "boundary_attempts": action.boundary_attempts,
                "upstream_contacted": action.upstream_contacted,
                "log_path": log.get("path", ""), "log_exists": log.get("exists", False),
                "note": ("the action's record shows upstream_contacted=false and the upstream's "
                         "own access log does not name it: nothing reached the far side")}

    def counts(self) -> dict[str, int]:
        return self.proxy.actions.counts()

    def chain(self) -> dict[str, Any]:
        return self.proxy.registry.verify()

    def proof(self, limit: int = 60) -> dict[str, Any]:
        """The PROOF panel's data, as a projection of kernel state and nothing more.

        Two questions the panel asks, answered only from what the kernel already holds:

        * which run asked for which call - the ``run_id <-> action_id`` correlation the kernel
          stamped at interception time (contract TASK.5: one id, two traces);
        * which receipt proves it - the receipt an action carries, matched against the
          receipts the chain actually holds. A receipt the registry does not carry is reported
          as ``None`` with ``receipt_in_chain: False`` - never a value this layer made up.

        Reads only. It never decides, never contacts an upstream, and never invents an id.
        """
        from collections import Counter

        receipts = self.registry_recent(limit)
        by_short: Counter = Counter((e.get("hash") or "")[:8] for e in receipts)
        actions = self.actions(limit)
        actions_by_run: dict[str, list[dict[str, Any]]] = {}
        for a in actions:
            if a.get("run_id"):
                actions_by_run.setdefault(a["run_id"], []).append(a)

        correlation: list[dict[str, Any]] = []
        for run_id, rows in actions_by_run.items():
            for a in rows:
                short = a.get("receipt") or ""
                correlation.append({
                    "run_id": run_id,
                    "action_id": a.get("action_id"),
                    "receipt": short or None,
                    "receipt_in_chain": bool(short) and by_short.get(short, 0) > 0,
                })
        for entry in receipts:
            run_id = entry.get("run_id")
            if run_id and run_id not in actions_by_run:
                correlation.append({
                    "run_id": run_id,
                    "action_id": entry.get("action_id") or None,
                    "receipt": (entry.get("hash") or "")[:8] or None,
                    "receipt_in_chain": True,
                })

        seen: set[tuple[Any, Any, Any]] = set()
        unique: list[dict[str, Any]] = []
        for row in correlation:
            key = (row["run_id"], row["action_id"], row["receipt"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        unique.sort(key=lambda r: (r.get("action_id") or "", r.get("run_id") or ""), reverse=True)

        return {
            "correlation": unique[: max(1, min(limit, 200))],
            "receipts": [{
                "receipt": (e.get("hash") or "")[:8],
                "decision": e.get("decision"),
                "agent": e.get("agent"),
                "tool": e.get("tool"),
                "warrant": e.get("warrant"),
                "run_id": e.get("run_id"),
                "action_id": e.get("action_id"),
                "ts": e.get("ts"),
            } for e in receipts],
        }

    # ------------------------------------------------------------------- read API
    @staticmethod
    def _route(path: str) -> tuple[str, dict[str, list[str]]]:
        """Split a read path into a **clean route** and its query parameters.

        The registry below is keyed by the clean route, so ``/api/activity?limit=10`` must
        look up ``/api/activity`` - with ``limit`` handed on as an explicit kwarg. Stripping
        the query here, exactly once, is what keeps a caller that builds its path *with* a
        query string from turning into ``KeyError: no kernel read`` and a model answer of
        "unreadable". The caller-facing signature of :meth:`read` is unchanged: a path and
        nothing else.
        """
        from urllib.parse import parse_qs, urlparse

        u = urlparse(path or "")
        route = u.path.rstrip("/") or "/"
        return route, parse_qs(u.query)

    def read(self, path: str) -> dict[str, Any]:
        """Resolve one kernel-backed API path in-process.

        The specialist tools and the evidence floor read kernel state through the *same paths*
        the HTTP routes expose, so there is exactly one read implementation and no chance of a
        tool reading a different projection than the operator's UI. This reads only - it never
        decides. ``/api/ask`` is deliberately not resolvable here: the assistance surface is not
        kernel state, and a tool must never recurse into it.
        """
        route, q = self._route(path)

        def limit(default: int = 60) -> int:
            try:
                return max(1, min(int(q.get("limit", [default])[0]), 200))
            except (TypeError, ValueError):
                return default

        if route == "/api/overview":
            return self.overview()
        if route == "/api/state":
            return self.state(limit=limit())
        if route == "/api/actions":
            return {"actions": self.actions(limit=limit()), "counts": self.counts()}
        if route == "/api/actions/pending":
            return {"pending": self.pending(limit=limit())}
        if route == "/api/activity":
            return self.activity(limit=limit())
        if route == "/api/agents":
            return {"agents": self.agents()}
        if route == "/api/warrants":
            return {"warrants": self.warrants()}
        if route.startswith("/api/actions/"):
            row = self.action(route.rsplit("/", 1)[-1])
            return row if row is not None else {"error": "unknown action", "path": path}
        raise KeyError(f"no kernel read for {path!r}")

    def activity(self, limit: int = 50) -> dict[str, Any]:
        """The unified activity projection: the SAME event shape ``/api/activity`` serves.

        Newest-first, real receipts and real actions only - the one implementation the HTTP
        route and the specialist tool share, so a tool can never read a different feed than
        the operator. It reads kernel state; it decides nothing. Fixtures are **not** merged
        here: the demo feed belongs to the HTTP surface (``TENET_MODE=demo``), never to a
        kernel-backed tool result.
        """
        events: list[dict[str, Any]] = []
        for entry in self.registry_recent(limit):
            events.append({
                "kind": "receipt",
                "ts": entry.get("ts"),
                "decision": entry.get("decision"),
                "agent": entry.get("agent"),
                "tool": entry.get("tool"),
                "warrant": entry.get("warrant"),
                "receipt": (entry.get("hash") or "")[:8],
                "run_id": entry.get("run_id"),
                "action_id": entry.get("action_id"),
            })
        for a in self.actions(limit):
            events.append({
                "kind": "action",
                "ts": a.get("ts"),
                "action_id": a.get("action_id"),
                "run_id": a.get("run_id"),
                "agent": a.get("agent"),
                "tool": a.get("tool"),
                "state": a.get("state"),
                "decision": a.get("decision"),
                "receipt": a.get("receipt"),
                "upstream_contacted": a.get("upstream_contacted"),
            })
        events.sort(key=lambda ev: (ev.get("ts") or 0.0, ev.get("action_id") or ""), reverse=True)
        return {"count": len(events[:limit]), "events": events[:limit]}

    def overview(self) -> dict[str, Any]:
        """The authority picture: agents, warrants, counts, chain - reads only."""
        counts = self.counts()
        warrants = self.warrants()
        states: dict[str, int] = {}
        for w in warrants:
            states[w["state"]] = states.get(w["state"], 0) + 1
        agents = self.agents()
        return {
            "node": "TENET",
            "counts": {
                "agents": len(agents),
                "agents_halted": sum(1 for a in agents if a["state"] == "halted"),
                "warrants": len(warrants),
                "receipts": counts.get("total", 0),
                "actions": counts.get("total", 0),
                "pending": counts.get("pending", 0),
            },
            "authority": {
                "issuer": warrants[0]["issuer"] if warrants else "",
                "warrant_states": states,
                "actors": sorted({w["agent"] for w in warrants}),
            },
            "chain": self.chain(),
        }

    # ------------------------------------------------- ACT-4: security decision projection
    # ``security_events`` is a READ-ONLY projection: it joins records the kernel already holds
    # (canonical actions + their receipts) with the persisted provider evidence, so the first
    # screen of the Control Room can answer, in plain language, what an agent tried to do, why
    # TENET allowed or blocked it, and whether data actually left the boundary. It decides
    # nothing, contacts nothing and invents nothing: an absent field is ``null``, never a
    # default that reads as success (AGENTS.md D5/D12; diagnosis §5).
    #
    # The vocabulary is fixed by ``docs/act-3-causal-graph.md``: ``upstream_call_id`` (``U-…``)
    # is minted at the boundary and is not available in this slice, so it is rendered ``null``
    # - never ``action_id`` relabelled (constraint 5). The id that answers "who allowed this"
    # is the kernel's action, and it stays separate from every other id.

    def _provider_events_by_run(self) -> dict[str, list[dict[str, Any]]]:
        """Provider evidence, grouped by the run the orchestrator stamped it with.

        Reads the assistance surface's own provider journal - a persisted record of real
        requests - through its one reader. A missing or unreadable journal is an empty map: an
        absent model trace is reported as absent, never filled in (D12). This is a read; it
        never calls the provider.
        """
        try:
            from control_room import provider as provider_module

            events = provider_module.read_events()
        except Exception:  # noqa: BLE001 - a missing journal is an absent step, not a failure
            return {}
        by_run: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            run_id = str(event.get("run_id") or "")
            if run_id:
                by_run.setdefault(run_id, []).append(event)
        return by_run

    @staticmethod
    def _model_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
        """Project the model-trace facts from a run's provider events.

        ``model_trace_id`` is the provider's own request id (``x-ds-trace-id``); it is the only
        thing that proves THIS run reached the model. Tokens/latency are reported only when the
        provider actually returned them - a rejected call leaves them ``null``, never ``0``.
        """
        completed = [e for e in events if e.get("event") == "deepseek.request.completed"]
        started = [e for e in events if e.get("event") == "deepseek.request.started"]
        failed = [e for e in events if e.get("event") == "deepseek.request.failed"]
        trace_ids = [e.get("request_id") for e in completed if e.get("request_id")]
        served = sorted({e.get("model_served") for e in completed if e.get("model_served")})
        requesters = [e.get("model_requested") for e in events if e.get("model_requested")]
        latencies = [int(e["latency_ms"]) for e in completed if e.get("latency_ms") is not None]
        statuses = [int(e["status"]) for e in completed if e.get("status") is not None]
        in_tokens = [int(e["input_tokens"]) for e in completed if e.get("input_tokens") is not None]
        out_tokens = [int(e["output_tokens"]) for e in completed if e.get("output_tokens") is not None]
        # ``request_id`` is the provider's own ``x-ds-trace-id``, so it is a real trace id ONLY
        # when the provider actually answered. A transport failure that never reached the
        # provider leaves the local id in the journal with no response id behind it: showing
        # that as a model trace would present a local id as proof the model was reached (D12).
        # So the trace id is withheld unless a completed response carried a provider id.
        responded = any(e.get("provider_response_id") for e in completed)
        # The HTTP status is the honest "did the model answer" signal: a 401 is a real response
        # carrying a real trace id, but it is NOT a successful reasoning step - the UI says so.
        ok = bool(statuses) and all(200 <= s < 300 for s in statuses)
        trace_id = trace_ids[0] if (trace_ids and responded) else None
        return {
            "model_trace_id": trace_id,
            "model_requested": requesters[0] if requesters else None,
            "model_served": served[0] if len(served) == 1 else (served or None),
            "model_calls_started": len(started),
            "model_calls_completed": len(completed),
            "model_calls_failed": len(failed),
            "provider_status": statuses[-1] if statuses else None,
            "provider_reached": bool(completed) and responded,
            "provider_ok": ok,
            "latency_ms": max(latencies) if latencies else None,
            "tokens": ({"input": sum(in_tokens), "output": sum(out_tokens)}
                       if in_tokens or out_tokens else None),
        }

    @staticmethod
    def _intent(tool: str, params: dict[str, Any] | None) -> Optional[str]:
        """A short, plain-language reading of what the call wants, from its own arguments.

        Built from the arguments the action actually carried - never a canned sentence. When
        the arguments do not describe a human-readable intent, the answer is ``null`` rather
        than a generic string that would read like a claim.
        """
        params = params or {}
        values = params.get("values") if isinstance(params.get("values"), dict) else params
        base = values.get("base")
        symbols = values.get("symbols")
        if tool == "fx.read_rate" and base and symbols:
            return f"{base} → {symbols} market rate"
        if tool == "equity.read_snapshot" and symbols:
            sym = symbols if isinstance(symbols, str) else ",".join(map(str, symbols))
            return f"equity snapshot for {sym}"
        table = values.get("table")
        if table:
            return f"read from {table}"
        return None

    def _receipt_index(self, limit: int = 200) -> dict[str, dict[str, Any]]:
        """Short-hash -> receipt row, so an action's ``boundary_attempts`` can be found.

        ``boundary_attempts`` lives on the receipt in some mirrors and on the action in
        others; the projection reads both and reports ``null`` when neither carries it.
        """
        out: dict[str, dict[str, Any]] = {}
        try:
            for entry in self.registry_recent(limit):
                short = (entry.get("hash") or "")[:8]
                if short:
                    out[short] = entry
        except Exception:  # noqa: BLE001 - a missing receipt index is an absent field, not a crash
            return {}
        return out

    # ------------------------------------------- ACT-5: the live security trace composition
    def record_origin(self, action_id: str, origin: str) -> None:
        """File WHY an action exists (``operator self-check`` / ``startup self-check``).

        The mirror's ``Action`` is frozen (AGENTS.md); an unknown keyword would break its own
        reload. So the origin label - a control-plane fact about who asked the kernel to run
        this scenario, not a decision - is journaled beside the kernel store, exactly as the
        provider's evidence journal is. Read back by :meth:`live_trace`. Best-effort: a failure
        here never breaks a decided call.
        """
        if not action_id or not origin:
            return
        try:
            path = self._origin_journal_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"action_id": action_id, "origin": origin},
                                    sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:  # noqa: BLE001 - recording never breaks the enforcement path
            pass

    @staticmethod
    def _state_dir() -> Path:
        return Path(os.environ.get("TENET_STATE_DIR")
                    or os.environ.get("WARRNT_HOME")
                    or (REPO_ROOT / "state"))

    def _origin_journal_path(self) -> Path:
        return self._state_dir() / "control-plane" / "origins.jsonl"

    def _origin_index(self) -> dict[str, str]:
        """``action_id -> origin`` from the control plane's own journal. Absent = empty map."""
        out: dict[str, str] = {}
        try:
            path = self._origin_journal_path()
            if not path.exists():
                return out
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    aid = str(row.get("action_id") or "")
                    if aid:
                        out[aid] = str(row.get("origin") or "")
        except Exception:  # noqa: BLE001 - an unreadable journal is an absent field, not a crash
            return {}
        return out

    def live_trace(self, action_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """The live ``trace`` object: one action, composed with its authority evidence (ACT-5 AC1).

        This is a read-only join over records the kernel already holds: the action ledger
        (what was asked and what it decided), the agent register (identity + delegation), the
        warrant register (the authority's own signature state) and the provider journal (the
        model-trace evidence). It decides nothing and mints nothing; every field whose
        evidence is missing is ``null`` **and named in ``incomplete``** - no field is rounded
        up to look like a permission (``authority_source`` is always ``tenet-kernel``).

        ``action_id`` is optional and read-only (ACT-6 AC1/AC2): omitted, the LAST real action
        is composed, exactly as before. When given, THAT action is composed through the same
        :meth:`_trace_from` composer - there is one composer, not two. An ``action_id`` the
        ledger does not hold yields ``None`` (the caller answers 404), never a fabricated trace.

        ``None`` when the kernel holds no action at all: an empty kernel yields ``trace: null``
        and nothing else is invented.
        """
        if action_id:
            row = self.action(str(action_id))
            if row is None:
                return None
            # ``action()`` returns the ledger row plus the agent-level identity fields; the
            # composer reads only the ledger keys, so the same body serves both cases.
            return self._trace_from(row)
        actions = self.actions(200)
        if not actions:
            return None
        # Newest first: the ledger lists newest first, but sort defensively by timestamp then id.
        latest = max(actions, key=lambda a: (float(a.get("ts") or 0.0),
                                             str(a.get("action_id") or "")))
        return self._trace_from(latest)

    def _trace_from(self, action: dict[str, Any]) -> dict[str, Any]:
        """Compose one AC1 ``trace`` object from a single action row + surrounding evidence."""
        incomplete: list[str] = []
        action_id = str(action.get("action_id") or "") or None
        run_id = str(action.get("run_id") or "") or None
        agent_id = str(action.get("agent") or "")
        tool = str(action.get("tool") or "")

        # ---- identity + delegation: read from the agent the order was issued to (never guessed)
        agent_row: dict[str, Any] = {}
        try:
            for row in self.agents(dev=False):
                if str(row.get("id")) == agent_id:
                    agent_row = row
                    break
        except Exception:  # noqa: BLE001
            agent_row = {}
        agent_role = agent_row.get("role") or None
        principal = agent_row.get("principal") or None
        on_behalf_of = agent_row.get("on_behalf_of") or None
        entitlements = list(agent_row.get("entitlements") or [])
        scope = list(agent_row.get("scope") or [])
        for name, value in (("agent_role", agent_role), ("principal", principal),
                            ("on_behalf_of", on_behalf_of), ("entitlements", entitlements),
                            ("scope", scope)):
            if not value:
                incomplete.append(name)

        origin = self._origin_index().get(str(action_id or "")) or None
        if not origin:
            incomplete.append("origin")

        # ---- the requested action, in the agent's own words
        intent = self._intent(tool, action.get("parameters"))
        if not intent:
            incomplete.append("action.intent")
        # ---- the action's class: one fact, one source. The DECISION's own evaluation is the
        # ``reason`` string (its ``class <name>`` phrase is exactly what the why-line renders),
        # so the class is read from there whenever the row does not carry one. Reading the row's
        # field alone left the reaches line saying "no class recorded" beside a why-line that
        # named the class; the row's own field, when present, still wins (it is the same fact
        # the evaluation wrote). Only when NO evidence carries a class is it null and NAMED.
        action_class = action.get("action_class") or _class_from_reason(action.get("reason"))
        if not action_class:
            incomplete.append("action.class")
        args = dict(action.get("parameters") or {})

        # ---- TENET checks: identity / entitlement / warrant / policy, each ok|false|None
        identity_ok: Optional[bool] = True if (agent_id and principal) else None
        if identity_ok is None:
            incomplete.append("checks.identity")
        right = ENTITLEMENT_OF_TOOL.get(tool, "")
        if right:
            entitled: Optional[bool] = right in ENTITLEMENTS.get(agent_id, set())
        else:
            # the register holds no opinion about this tool: honestly unknown, never a grant
            entitled = None
            incomplete.append("checks.entitlement")

        # ---- warrant: the authority's own signature state, from the register
        w_id = str(action.get("warrant") or "") or None
        warrant_obj: dict[str, Any] = {"id": w_id, "state": None, "sig_ok": None,
                                       "ttl_remaining": None}
        try:
            for w in self.warrants():
                if str(w.get("id")) == str(w_id or ""):
                    warrant_obj = {"id": w_id, "state": w.get("state"),
                                   "sig_ok": w.get("sig_ok"),
                                   "ttl_remaining": w.get("ttl")}
                    break
        except Exception:  # noqa: BLE001
            pass
        for key in ("state", "sig_ok", "ttl_remaining"):
            if warrant_obj.get(key) is None:
                incomplete.append(f"checks.warrant.{key}")

        policy_result = action.get("policy_result") or None
        if policy_result is None:
            incomplete.append("checks.policy")

        decision = action.get("decision") or None
        reason = action.get("reason") or None

        # ---- who decided: a person-resolved hold keeps the name it was decided by; where the
        # kernel alone decided (allow/deny/redact/revoked with no hold) the kernel names itself.
        # The row's own ``decided_by`` carries the real resolver - the approve/deny path records
        # the person there - so a human decision must never be re-attributed to the kernel, and
        # the kernel must never borrow a person's name it did not receive. No name is invented:
        # an empty resolver on a human-resolved row is the empty string ruled out below.
        resolver = str(action.get("decided_by") or "").strip()
        decided_by = resolver if (resolver and decision == "human") else "tenet-kernel"

        # ---- boundary crossing: honest rule (AC2). "contacted" is TRUE only when the action
        # carries an execution result with an http_status - a decision of "allow" alone proves
        # nothing, and a deny with no attempt yields contacted:false and no http_status. The
        # EXECUTION RESULT is what proves contact, never the decision label: a person-resolved
        # hold carries decision == "human" (or the release stays "human" after the call), and
        # the far side still recorded a real status - so the label must not gate the evidence.
        crossing = action.get("execution_result") or {}
        http_status = crossing.get("http_status")
        contact_proven = bool(http_status)
        upstream_obj = {
            "contacted": contact_proven,
            "http_status": http_status if contact_proven else None,
            "endpoint": crossing.get("endpoint") if contact_proven else None,
            "value": crossing.get("value") if contact_proven else None,
            "response_sha256": crossing.get("response_sha256") if contact_proven else None,
            "latency_ms": crossing.get("latency_ms") if contact_proven else None,
        }
        if decision in ("allow", "redact") and not contact_proven:
            # A permitted call with no proof of contact is an INCOMPLETE crossing, named - never
            # assumed to have reached the far side.
            incomplete.append("upstream.http_status")

        # ---- the action's OWN resolved lifecycle state, verbatim (never mapped or renamed). A
        # human hold reads "pending" until a person resolves it, then the row records "approved"
        # or "denied"; the console needs the row's own word to tell "still waiting" from resolved.
        state = action.get("state") or None
        if state is None:
            incomplete.append("state")

        # ---- WHEN the state was reached: the row's own resolution timestamp. The resolve path stamps
        # `decided_ts` when a person decides (proxy.resolve_hold, approve and deny alike) and the brake
        # stamps it when the kernel expires a hold of a halted agent, so one clock covers all four
        # states. A row that carries none reports null, and for a RESOLVED hold (approved / denied /
        # expired) that absence is missing evidence, so it is NAMED. It is never back-filled with the
        # interception time: that is when the action was ASKED, not when it was resolved.
        decided_ts = action.get("decided_ts") or None
        if decided_ts is None and state in ("approved", "denied", "expired"):
            incomplete.append("decided_ts")

        # ---- execution: the SAME evidence the crossing is proven from, plus the negative proof.
        #   True  - the row carries an execution result with a real http_status (the call ran);
        #   False - the row proves it did NOT run: it carries an execution result (even empty, as a
        #           denial files) or an explicit ``upstream_contacted`` of false - the record says so;
        #   None  - the row says nothing (no execution result AND no ``upstream_contacted``), so the
        #           field is NAMED in incomplete rather than guessed.
        claims_execution = "execution_result" in action or action.get("upstream_contacted") is not None
        executed: Optional[bool] = True if contact_proven else (False if claims_execution else None)
        if executed is None:
            incomplete.append("executed")

        receipt_id = action.get("receipt") or None
        if not receipt_id:
            incomplete.append("receipt_id")

        # ---- model evidence for this run (null when the run has no provider trace)
        model = self._model_evidence(self._provider_events_by_run().get(str(run_id or ""), []))
        model_block = {
            "provider": "deepseek",
            "model_served": model.get("model_served"),
            "trace_id": model.get("model_trace_id"),
            "calls": model.get("model_calls_completed"),
            "tokens": model.get("tokens"),
        }

        return {
            "run_id": run_id,
            "action_id": action_id,
            "timestamp": action.get("ts") or None,
            "origin": origin,
            "agent": agent_id or None,
            "agent_role": agent_role,
            "principal": principal,
            "on_behalf_of": on_behalf_of,
            "entitlements": entitlements,
            "scope": scope,
            "action": {"tool": tool or None, "intent": intent,
                       "class": action_class, "args": args},
            "checks": {
                "identity": {"ok": identity_ok, "detail": principal},
                "entitlement": {"ok": entitled, "right": right or None},
                "warrant": warrant_obj,
                "policy": {"ok": bool(policy_result) if policy_result else None,
                           "detail": policy_result},
            },
            "decision": decision,
            "reason": reason,
            "decided_by": decided_by,
            "state": state,
            "decided_ts": decided_ts,
            "executed": executed,
            "upstream": upstream_obj,
            "receipt_id": receipt_id,
            "model": model_block,
            "incomplete": sorted(set(incomplete)),
        }

    def security_events(self, limit: int = 60) -> dict[str, Any]:
        """The security-decision feed: one ``SecurityEvent`` per canonical action, newest first.

        A read-only projection of kernel state (actions + receipts) joined with persisted
        provider evidence. It carries authority only in the sense that it *reports* the
        kernel's verdict - it makes none: ``llm_authority`` is always ``false`` and the model
        trace is evidence, never a permission.
        """
        limit = max(1, min(int(limit or 60), 200))
        actions = self.actions(limit)
        by_run = self._provider_events_by_run()
        receipts = self._receipt_index()
        events = [self._security_event_from(a, by_run, receipts) for a in actions]
        events.sort(key=lambda e: (e.get("timestamp") or 0.0, e.get("action_id") or ""),
                    reverse=True)
        return {
            "count": len(events[:limit]),
            "authority_source": "tenet-kernel",
            "llm_authority": False,
            "events": events[:limit],
        }

    def _security_event_from(self, action: dict[str, Any],
                             by_run: dict[str, list[dict[str, Any]]],
                             receipts: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Project one ``SecurityEvent`` from an Action row + the surrounding evidence."""
        run_id = str(action.get("run_id") or "")
        action_id = str(action.get("action_id") or "")
        receipt_id = action.get("receipt") or None
        crossing = action.get("execution_result") or {}
        receipt_row = receipts.get(str(receipt_id or "")[:8], {}) if receipt_id else {}
        attempts = action.get("boundary_attempts")
        if attempts is None:
            attempts = receipt_row.get("boundary_attempts")
        contacted = bool(action.get("upstream_contacted"))
        model = self._model_evidence(by_run.get(run_id, []))
        return {
            "event_id": action_id or run_id or None,
            "run_id": run_id or None,
            "timestamp": action.get("ts") or None,
            "agent": action.get("agent") or None,
            "actor": action.get("actor") or None,
            "intent": self._intent(str(action.get("tool") or ""), action.get("parameters")),
            "resource": action.get("tool") or None,
            "tool": action.get("tool") or None,
            "action_class": action.get("action_class") or None,
            "warrant": action.get("warrant") or None,
            "warrant_state": action.get("warrant_state") or None,
            "policy": action.get("policy_result") or None,
            "decision": action.get("decision") or None,
            "decision_id": None,   # slice B mints D-…; the kernel-owned unit today is the action
            "state": action.get("state") or None,
            "reason": action.get("reason") or None,
            "upstream_contacted": contacted,
            # U-… is minted at the boundary in slice B; until then it is honestly null -
            # ``action_id`` is NOT a call id and must never be shown as one (constraint 5).
            "upstream_call_id": None,
            "execution_result": crossing or None,
            "receipt_id": receipt_id,
            "model_trace_id": model["model_trace_id"],
            "model_requested": model["model_requested"],
            "model_served": model["model_served"],
            "latency_ms": model["latency_ms"],
            "tokens": model["tokens"],
            "boundary_attempts": attempts,
            "attempts": attempts,
            "authority_source": "tenet-kernel",
            "llm_authority": False,
        }

    def security_event(self, run_id: str) -> Optional[dict[str, Any]]:
        """One run's ``SecurityEvent``(s) plus the causal graph, read from records only.

        The graph is the chain ``run_id → model_trace_id → action_id → decision →
        upstream_call_id → receipt_id`` (``docs/act-3-causal-graph.md``) and it is **not an
        authority chain**: the model trace proves the request reached the model, the action is
        the unit of enforcement, the decision is authority, the receipt is a record. A missing
        node is reported as ``null`` and named in ``missing`` - a partial chain is never rounded
        up to PASS (rule 5). ``None`` means the run is unknown to the kernel.
        """
        run_id = str(run_id or "")
        if not run_id:
            return None
        actions = [a for a in self.actions(200) if str(a.get("run_id") or "") == run_id]
        by_run = self._provider_events_by_run()
        receipts = self._receipt_index()
        provider_events = by_run.get(run_id, [])
        if not actions and not provider_events:
            return None
        events = [self._security_event_from(a, by_run, receipts) for a in actions]
        events.sort(key=lambda e: e.get("action_id") or "")
        model = self._model_evidence(provider_events)
        nodes: list[dict[str, Any]] = []
        missing: list[str] = []
        nodes.append({"step": "run_id", "id": run_id, "proves": "the agent run"})
        nodes.append({"step": "model_trace_id", "id": model["model_trace_id"],
                      "proves": "the request reached the model"})
        if not model["model_trace_id"]:
            missing.append("model_trace_id")
        for event in events:
            nodes.append({"step": "action_id", "id": event["event_id"],
                          "proves": "the unit of enforcement"})
            nodes.append({"step": "decision", "id": event.get("decision"),
                          "proves": "authority (allow / deny / redact / human / revoked)"})
            if not event.get("decision"):
                missing.append("decision")
            nodes.append({"step": "upstream_call_id", "id": event.get("upstream_call_id"),
                          "proves": "a real contact left the boundary"})
            nodes.append({"step": "receipt_id", "id": event.get("receipt_id"),
                          "proves": "the recorded outcome"})
            if not event.get("receipt_id"):
                missing.append("receipt_id")
        # A permitted call with no proof of contact is an incomplete chain, named - never
        # assumed to have reached the far side (absence is a result, rule 4).
        no_contact = [e["event_id"] for e in events
                      if e.get("decision") in ("allow", "redact") and not e.get("upstream_contacted")]
        if no_contact:
            missing.append("upstream contact for a permitted call: " + ", ".join(no_contact))
        return {
            "run_id": run_id,
            "authority_source": "tenet-kernel",
            "llm_authority": False,
            "status": "COMPLETE" if not missing else "INCOMPLETE",
            "missing": sorted(set(missing)),
            "model": model,
            "causal_graph": {
                "chain": "run_id → model_trace_id → action_id → decision → "
                         "upstream_call_id → receipt_id",
                "nodes": nodes,
                "authority_lives_here": "decision",
                "note": "authority = kernel.decision, never the model trace",
            },
            "events": events,
        }

    # ---------------------------------------------------------------- decisions
    def intercept(self, agent_id: str, token: str, tool: str,
                  params: dict[str, Any] | None,
                  run_id: str = "") -> tuple[Any, str, dict[str, Any], dict, bool]:
        """Ask the kernel for a decision. The only caller of the gate.

        The decision itself is untouched: this passes the call through and, when the kernel
        executed it, copies the crossing facts the kernel returned onto the kernel's own
        Action record (see :meth:`_record_crossing`). It never alters a verdict and never
        contacts anything by itself.
        """
        right = missing_entitlement(agent_id, tool)
        if right:
            # The gate runs before the order is priced: authority to act is not the right to
            # this data, and a held right is refused whichever way the warrant would go.
            reason = f"no entitlement to {right}"
            action_id, receipt_id = self._record_refusal(
                agent_id=agent_id, tool=tool, reason=reason, entitlement=right)
            detail = {"action_id": action_id, "receipt": receipt_id, "gate": "entitlement",
                      "entitlement": right, "upstream_contacted": False,
                      "boundary_attempts": 0}
            return "deny", reason, detail, {"hash": receipt_id}, False

        decision, reason, detail, receipt, executed = self.proxy.intercept(
            agent_id, token, tool, params, run_id=run_id)
        self._record_crossing(tool, detail, executed)
        return decision, reason, detail, receipt, executed

    def _record_refusal(self, *, agent_id: str, tool: str, reason: str,
                        entitlement: str = "", action_id: str = "") -> tuple[str, str]:
        """File a refusal this control plane's own gate made, in the node's ledger and chain.

        The refusal is an event like any other (D5): it gets an action, a receipt and a chain
        entry, so a reader sees the same shape whether the kernel refused the call or the
        register did. Nothing is contacted and nothing is decided twice - the record states
        the fact of the refusal, not a second verdict.

        With ``action_id`` the receipt is filed against an act that already exists (the hold a
        person may not decide); the act itself is left exactly as it was.
        """
        from warrnt.proxy import _clock  # type: ignore import-not-found

        p = self.proxy
        if action_id:
            held = p.actions.get(action_id)
        else:
            agent = p.agents.get(agent_id)
            held = p.actions.record(
                run_id="", agent=agent_id, tool=tool, actor=agent_id,
                warrant=getattr(agent, "warrant", "-"), parameters={}, decision="deny",
                reason=reason, upstream_contacted=False, boundary_attempts=0, ts=p._now())
        receipt = p.registry.append(
            t=_clock(), decision="deny", agent=(held.agent if held else agent_id), tool=tool,
            warrant=(held.warrant if held else "-"), reason=reason, params="", rows_after=0,
            ts=p._now())
        if held is not None and not action_id:
            held.receipt, held.state = receipt["hash"][:8], "decided"
            p.actions.save(held)
        return (held.action_id if held is not None else ""), receipt["hash"][:8]

    def resolve_hold(self, action_id: str, approve: bool, by: str) -> dict[str, Any]:
        """A named person releases or refuses a held action; the kernel runs the call.

        Separation of duties is checked here, before the kernel is asked: the person who
        releases a hold must not be the actor who requested it. The refusal is raised, not
        softened into an allow, and it applies to a deny as well as an approve - a decision
        made by the party under decision is not a decision either way.
        """
        held = self.proxy.actions.get(action_id)
        actor = str(getattr(held, "actor", "") or getattr(held, "agent", "") or "").strip()
        if held is not None and actor and by.strip().lower() == actor.lower():
            # D5: a refusal is an event. The chain records who tried to decide an act they
            # requested, before the caller is told no - the hold itself is left pending.
            self._record_refusal(
                agent_id=str(getattr(held, "agent", "") or ""),
                tool=str(getattr(held, "tool", "") or ""),
                reason=f"separation of duties · {by} requested {action_id} and may not decide it",
                action_id=action_id)
            raise SeparationOfDutiesRefused(
                f"{by} is the actor of {action_id} and may not also decide it")
        out = self.proxy.resolve_hold(action_id, approve, by)
        if isinstance(out, dict) and out.get("executed"):
            tool = str((out.get("action") or {}).get("tool") or "")
            self._record_crossing(tool, {**out, "action_id": action_id}, True)
        return out

    def _record_crossing(self, tool: str, detail: dict[str, Any], executed: bool) -> None:
        """Copy the crossing facts the kernel returned onto the kernel's own Action record.

        The truth here is the *upstream's* reply, which the mirror's proxy already carried
        back on ``detail['result']`` after it executed the call. This method only files that
        reply under the action the kernel created - it decides nothing, drops nothing, and
        invents nothing: a field the upstream did not send is simply absent, and the receipt
        is left exactly as the kernel wrote it. Guarded so a missing/short payload can never
        raise on the enforcement path (the decision has already been made and recorded by
        the time we get here).
        """
        if not executed or tool not in LIVE_BOUNDARY:
            return
        action_id = str((detail or {}).get("action_id")
                        or ((detail or {}).get("action") or {}).get("id") or "")
        result = (detail or {}).get("result")
        if not action_id or not isinstance(result, dict):
            return
        try:
            action = self.proxy.actions.get(action_id)
            if action is None:
                return
            crossing = {
                "endpoint": result.get("endpoint") or result.get("source"),
                "http_status": result.get("http_status"),
                "response_sha256": result.get("response_sha256"),
                "value": result.get("value"),
                # When the question asked for a symbol the reply does not carry, the value
                # is simply absent - and an absent value with no explanation reads as a
                # broken tool. So the crossing also files which symbol was answered and
                # which symbols the upstream actually returned; nothing is derived.
                "value_symbol": result.get("symbol"),
                "rates_returned": (sorted(str(k) for k in result["rates"])
                                   if isinstance(result.get("rates"), dict) else None),
                # The map itself, verbatim: the summary above says which symbols came back,
                # this says what they are worth. A multi-symbol read has no single ``value``
                # field, so without this the numbers would exist only in the model's
                # arithmetic instead of in the record the receipt points at.
                "rates": (dict(result["rates"]) if isinstance(result.get("rates"), dict) else None),
                "latency_ms": result.get("latency_ms"),
                "boundary": LIVE_BOUNDARY.get(tool, ""),
            }
            action.execution_result = {**action.execution_result,
                                       **{k: v for k, v in crossing.items() if v is not None}}
            self.proxy.actions.save(action)
        except Exception:  # noqa: BLE001 - recording must never break a decided call
            pass

    def revoke(self, agent_id: str):
        return self.proxy.revoke(agent_id)

    # ------------------------------------------------------------ live upstream warrants (T1)
    def issue_live_warrants(self) -> list[str]:
        """Register the live-upstream warrants the real Frankfurter tool runs under (T1).

        The kernel still does all the work: this only hands it a :class:`WarrantSpec` exactly
        as ``SEED_SPECS`` does, and the kernel's own issuer signs it and mints the agent token.
        No control-plane code signs, allows or decides anything - it supplies a spec, the
        authority turns it into a signed, TTL-bounded order. Idempotent: a warrant already
        present is left untouched, so the call is safe on every boot.

        Returns the ids actually issued on this call (empty on a re-issue, and empty when no
        real upstream is configured - see :func:`live_upstream_configured`).
        """
        from warrnt.models import Rule, WarrantSpec  # type: ignore import-not-found

        if not live_upstream_configured():
            return []

        issued: list[str] = []
        for spec in _live_warrants():
            if spec.id in self.proxy.warrants:
                continue
            warrant = self.proxy.issuer.issue(spec)
            self.proxy.warrants[warrant.id] = warrant
            self.proxy.agents[warrant.agent] = _agent_state(self.proxy, warrant)
            issued.append(warrant.id)
        return issued


def _agent_state(proxy: Any, warrant: Any) -> Any:
    """Build the agent identity the kernel keeps for a freshly issued warrant.

    Delegates to the proxy's own builder so a live-warrant agent carries the same ACT-2
    identity facts (``principal``, ``on_behalf_of``, ``entitlements``, ``scope``) as a seeded
    one. If an older mirror has no such helper, the plain AgentState is the fallback - the
    live path must never fail open, but it also must never fail *loud* over a missing feature.
    """
    builder = getattr(proxy, "_new_agent", None)
    if callable(builder):
        return builder(warrant)
    from warrnt.models import AgentState  # type: ignore import-not-found

    return AgentState(id=warrant.agent, role=warrant.role, warrant=warrant.id,
                      token=proxy.issuer.token_for(warrant.agent, warrant.id))


# ---------------------------------------------------------------- live upstream warrants (T1)
# The real Frankfurter upstream is reached through the tool ``fx.read_rate``. Warrants are
# registered so the whole decision vocabulary is exercised against a REAL external service:
#  * ``fx-trader`` reads the live reference rate (allow, in scope);
#  * ``fx-auditor`` prices a live read with a person's decision (human hold);
#  * ``support-copilot`` has an mcp-supplier warrant that does not cover ``fx.read_rate``
#    (deny) - an agent CAN be stopped from reaching the real upstream even though the tool
#    exists on the far side.
# The specs are declared here, in the control plane, but the kernel's own issuer signs them
# and mints the tokens: this module never decides.
def _live_warrants() -> list[Any]:
    from warrnt.models import Rule, WarrantSpec  # type: ignore import-not-found

    return [
        WarrantSpec(
            id="W-9001", agent="fx-trader", role="Treasury",
            scope="fx.read_rate · live ECB reference rates · read-only", ttl=3600.0,
            rules=[
                Rule(tool="fx.read_rate", effect="allow",
                     reason="read-only · live reference rate · in scope"),
                Rule(tool="fx.audit_note", effect="allow",
                     reason="read-only · attach a desk note to the audit trail · PII stripped",
                     redact=["fields"]),
                Rule(tool="fx.last", effect="allow", reason="read-only · last fetched rate"),
                # ACT-2 §2 (T7): the warrant ALLOWS this read - the authority gate passes it -
                # but the entitlement register does not grant fx-trader the equity right, so
                # the entitlement gate denies it before the warrant is ever priced. This is the
                # one place a valid order and a held right disagree on purpose: it makes
                # "a warrant is not a grant of data" a distinction the test suite can execute.
                Rule(tool="equity.read_snapshot", effect="allow",
                     reason="read-only · equity snapshot · authority granted, entitlement required"),
            ],
        ),
        WarrantSpec(
            id="W-9003", agent="fx-auditor", role="Compliance",
            scope="fx.read_rate ⇒ require-human · a live rate read is a person's decision",
            ttl=1800.0,
            rules=[
                Rule(tool="fx.read_rate", effect="human",
                     reason="this order prices a live read with a person's decision"),
            ],
        ),
    ]


# The egress boundary the live tools sit on, and whether the tool may cross it. This is a
# *description* of the upstream, not a permission: the kernel's class ladder and the signed
# warrant remain the only things that decide. It is recorded on the receipt so a reader sees
# "outbound" without the frozen mirror taxonomy having to grow a new member.
LIVE_BOUNDARY: dict[str, str] = {
    "fx.read_rate": "outbound",   # performs one real HTTPS GET to the ECB reference rates
    "fx.audit_note": "internal",  # travels to the upstream but never leaves the box
    "fx.last": "internal",        # served from the upstream's own cache, no egress
    "equity.read_snapshot": "internal",  # ACT-2 §2 (T7): the second resource, same egress path
}

LIVE_WARRANTS: list[Any] = []

# The action class of each live-upstream tool (T1). The kernel's taxonomy is the ONLY
# taxonomy (AGENTS.md / F8 R5); this does not add one - it files the new tool into the
# kernel's existing ladder. A live reference-rate read is an ``observe``: read-only, and no
# personal data leaves, so the frozen ladder already has the right rung for it. Filing it
# here keeps the mirror byte-identical while the classification still lives in one place:
# the kernel's ``CLASS_OF_TOOL`` table, extended at build time.
LIVE_TOOL_CLASSES: dict[str, str] = {
    "fx.read_rate": "observe",
    "fx.audit_note": "draft",
    "fx.last": "observe",
    # ACT-2 §2 (T7): a second resource, so entitlement is a real distinction and not a
    # synonym for the warrant. ``equity.read_snapshot`` is an ``observe`` too, but it reads a
    # *different* resource than the FX tools - and the two are entitled separately.
    "equity.read_snapshot": "observe",
}


def live_upstream_configured() -> bool:
    """True when this process was pointed at a real MCP upstream (``WARRNT_UPSTREAM``).

    The live warrants are issued only then. Without an upstream the node fronts its
    in-process sandbox and ``fx.read_rate`` has nothing real behind it - warranting a
    remote order for a service that is not there would be a claim, not a control (D12).
    It also keeps the enforced agent set an exact function of the deployment, so the
    seed-only process still shows the four seeded agents and nothing more.
    """
    return bool(os.environ.get("WARRNT_UPSTREAM", "").strip())


def _register_live_tool_classes() -> None:
    """File the live-upstream tools into the kernel's existing taxonomy (idempotent)."""
    from warrnt import actions as kernel_actions  # type: ignore import-not-found

    for tool, cls_name in LIVE_TOOL_CLASSES.items():
        kernel_actions.CLASS_OF_TOOL[tool] = kernel_actions.ActionClass(cls_name)


def build_kernel(*, state_dir: "str | os.PathLike | None" = None) -> Kernel:
    """Build the enforcement kernel proxy from the mirror.

    ``state_dir`` (TENET_STATE_DIR) is honoured by the mirror's own ``Settings.load``; passing
    it explicitly keeps the control plane's store next to the directory the kernel uses.
    """
    mods = load_kernel()
    _register_live_tool_classes()
    Settings = mods["Settings"]
    build_proxy = mods["build_proxy"]
    settings = Settings.load(state_dir) if state_dir else Settings.load()
    try:
        proxy = build_proxy(settings)
    except Exception as exc:  # noqa: BLE001
        raise KernelUnavailable(
            f"kernel proxy failed to build: {type(exc).__name__}: {exc}") from exc
    return Kernel(proxy)
