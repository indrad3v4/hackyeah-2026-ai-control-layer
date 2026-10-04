"""``python -m control_plane`` - the run command the deployment targets use.

One process serving the Control Room, the Control Plane API and the mirrored Enforcement
Kernel (contract TASK.1). ``PORT`` and ``HOST`` are honoured because Railway/Render inject
``PORT``; the host default is ``0.0.0.0`` on purpose - a containerised platform routes inbound
traffic to the container's public interface, so binding the loopback default would make the
process unreachable and fail the platform health check even though the app is healthy. Local
development is unaffected: Uvicorn serves ``0.0.0.0`` there too, and the contract's
``http://127.0.0.1:8080`` still answers.
"""
from __future__ import annotations

import os

import uvicorn


def _host() -> str:
    """The bind address. ``0.0.0.0`` unless the operator overrides ``HOST`` explicitly.

    A platform (Railway, Render, Fly) injects ``PORT`` but not ``HOST``. Defaulting to the
    loopback would leave the container listening where the edge cannot reach it - the exact
    "static/Caddy-looking" failure this fixes: the process runs, the health check never passes.
    """
    return os.environ.get("HOST", "").strip() or "0.0.0.0"


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    # The app object, not an import string: one import, one module instance, and the lifespan
    # that seeds the kernel and binds the assistance surface is guaranteed to run on this
    # process. A second import could hand out a different ``app`` than the one served.
    from .app import app

    uvicorn.run(app, host=_host(), port=port, log_level="info")


if __name__ == "__main__":
    main()
