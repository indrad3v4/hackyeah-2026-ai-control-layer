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

import os
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_DIR = REPO_ROOT / "node"


class KernelUnavailable(RuntimeError):
    """The enforcement kernel could not produce a decision. Callers must fail closed."""


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

    def action(self, action_id: str) -> Optional[dict[str, Any]]:
        a = self.proxy.actions.get(action_id)
        return a.public() if a is not None else None

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
                   "state": a.state, "last": a.last}
            if dev:
                row["token"] = a.token
            out.append(row)
        return out

    def counts(self) -> dict[str, int]:
        return self.proxy.actions.counts()

    def chain(self) -> dict[str, Any]:
        return self.proxy.registry.verify()

    # ------------------------------------------------------------------- read API
    def read(self, path: str) -> dict[str, Any]:
        """Resolve one kernel-backed API path in-process.

        The specialist tools and the evidence floor read kernel state through the *same paths*
        the HTTP routes expose, so there is exactly one read implementation and no chance of a
        tool reading a different projection than the operator's UI. This reads only - it never
        decides. ``/api/ask`` is deliberately not resolvable here: the assistance surface is not
        kernel state, and a tool must never recurse into it.
        """
        from urllib.parse import parse_qs, urlparse

        u = urlparse(path)
        route, q = u.path.rstrip("/") or "/", parse_qs(u.query)

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
        if route == "/api/agents":
            return {"agents": self.agents()}
        if route == "/api/warrants":
            return {"warrants": self.warrants()}
        if route.startswith("/api/actions/"):
            row = self.action(route.rsplit("/", 1)[-1])
            return row if row is not None else {"error": "unknown action", "path": path}
        raise KeyError(f"no kernel read for {path!r}")

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

    # ---------------------------------------------------------------- decisions
    def intercept(self, agent_id: str, token: str, tool: str,
                  params: dict[str, Any] | None,
                  run_id: str = "") -> tuple[Any, str, dict[str, Any], dict, bool]:
        """Ask the kernel for a decision. The only caller of the gate."""
        return self.proxy.intercept(agent_id, token, tool, params, run_id=run_id)

    def resolve_hold(self, action_id: str, approve: bool, by: str) -> dict[str, Any]:
        """A named person releases or refuses a held action; the kernel runs the call."""
        return self.proxy.resolve_hold(action_id, approve, by)

    def revoke(self, agent_id: str):
        return self.proxy.revoke(agent_id)


def build_kernel(*, state_dir: "str | os.PathLike | None" = None) -> Kernel:
    """Build the enforcement kernel proxy from the mirror.

    ``state_dir`` (TENET_STATE_DIR) is honoured by the mirror's own ``Settings.load``; passing
    it explicitly keeps the control plane's store next to the directory the kernel uses.
    """
    mods = load_kernel()
    Settings = mods["Settings"]
    build_proxy = mods["build_proxy"]
    settings = Settings.load(state_dir) if state_dir else Settings.load()
    try:
        proxy = build_proxy(settings)
    except Exception as exc:  # noqa: BLE001
        raise KernelUnavailable(
            f"kernel proxy failed to build: {type(exc).__name__}: {exc}") from exc
    return Kernel(proxy)
