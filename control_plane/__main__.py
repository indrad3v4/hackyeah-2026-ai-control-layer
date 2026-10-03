"""``python -m control_plane`` - the run command the deployment targets use.

One process serving the Control Room, the Control Plane API and the mirrored Enforcement
Kernel (contract TASK.1). ``PORT`` is honoured because Railway/Render inject it; the default
matches the contract's ``http://127.0.0.1:8080``.
"""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("PORT", "8080"))
    # The app object, not an import string: one import, one module instance, and the lifespan
    # that seeds the kernel and binds the assistance surface is guaranteed to run on this
    # process. A second import could hand out a different ``app`` than the one served.
    from .app import app

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
