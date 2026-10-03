"""TENET Control Plane - the single user-facing runtime of the AI control layer.

One FastAPI process hosts the three logical boundaries, but the *code* boundary is explicit:

    TENET Control Room (index.html / Reflex)  ->  TENET Control Plane (this package)
        ->  TENET Enforcement Kernel (node/warrnt, a mirrored library)  ->  upstream

No route here decides, allows, redacts or contacts an upstream: every decision is delegated
to the kernel (``control_plane.kernel``). If the kernel cannot answer, the control plane
refuses - it never silently allows (contract TASK.2).
"""
from __future__ import annotations

__all__ = ["app", "create_app"]


def __getattr__(name: str):
    # Lazy so importing the package does not import FastAPI/uvicorn at collection time.
    if name in __all__:
        from .app import app, create_app

        return {"app": app, "create_app": create_app}[name]
    raise AttributeError(name)
