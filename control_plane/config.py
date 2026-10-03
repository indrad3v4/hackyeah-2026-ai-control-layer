"""Control-plane configuration: mode flag, provider names and process identity.

Everything here reads the environment by NAME. No value is a secret, and no secret is read
here beyond the boolean question "is the provider key present?" (answered elsewhere, and
never echoed).
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

LIVE = "LIVE"
DEGRADED = "DEGRADED"
DEMO = "DEMO"

# The provider is *named* here so /health can report it without ever reading the key value.
# The base URL is deliberately NOT here: the enforcement path must not reach a paid host at
# all (AGENTS.md D6). The one place a paid endpoint is named is control_room/provider.py,
# on the assistance surface, which holds no authority over any decision.
PROVIDER = "deepseek"
MODEL = os.environ.get("TENET_MODEL", "deepseek-chat")
KEY_ENV = "DEEPSEEK_API_KEY"


def mode() -> str:
    """``TENET_MODE`` - ``live`` (default) or ``demo``.

    Anything that is not an explicit ``demo`` is treated as ``live``: a production instance
    must never render fixtures because an operator mistyped a flag.
    """
    return DEMO.lower() if os.environ.get("TENET_MODE", "live").strip().lower() == "demo" else "live"


def is_demo() -> bool:
    return mode() == "demo"


def provider_key_present() -> bool:
    """PRESENT / ABSENT - the only admissible statement about the key. Never its value."""
    return bool(os.environ.get(KEY_ENV, "").strip())


def dev() -> bool:
    """``WARRNT_DEV=1`` - the node's own dev switch, mirrored here.

    In dev the agent tokens are returned by ``/api/agents`` (the node does the same) so a demo
    can drive ``/mcp`` without an out-of-band token. This is a demo convenience, never a
    production behaviour: unset, the tokens are not returned at all.
    """
    return os.environ.get("WARRNT_DEV", "").strip() in ("1", "true", "yes")


def commit() -> str:
    """The commit the running process was built from, best-effort, never fatal."""
    for var in ("TENET_COMMIT", "RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT"):
        value = os.environ.get(var, "").strip()
        if value:
            return value[:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             capture_output=True, text=True, timeout=2)
        if out.returncode == 0:
            return out.stdout.strip()[:12]
    except Exception:  # noqa: BLE001 - identity is nice-to-have, never a reason to crash
        pass
    return "unknown"


@dataclass(frozen=True)
class Identity:
    """Process identity for /health: commit + a monotonic uptime."""

    commit: str
    started: float

    @classmethod
    def now(cls) -> "Identity":
        return cls(commit=commit(), started=time.monotonic())

    def uptime_s(self) -> int:
        return int(max(0.0, time.monotonic() - self.started))
