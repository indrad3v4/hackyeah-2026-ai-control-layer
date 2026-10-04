#!/usr/bin/env python
"""Enforce AGENTS.md D6 (Amendment 1): the enforcement path imports no paid provider.

The decision path - the layer that classifies the action, scopes the actor, holds warrant
state, applies policy and reaches the verdict - must run on local models only. The agentic
assistance surface (``control_room/``) is the ONE place that may call a paid provider.

This script parses every module on the enforcement path and fails if any of them imports a
paid-SDK or reaches a paid host. It is a static check on purpose: it runs in CI without a
network and without a key, so a regression is caught the moment it is committed.

Exit code 0 when the enforcement path is clean, 1 otherwise (with the offending imports).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Modules that make up the decision path, plus the control-plane read/IPC surface.
ENFORCEMENT_MODULES = [
    "control_plane/__init__.py",
    "control_plane/app.py",
    "control_plane/config.py",
    "control_plane/kernel.py",
    "control_plane/fixtures.py",
]

# Import roots that would put a paid provider on the enforcement path.
PAID_IMPORT_ROOTS = {
    "openai", "anthropic", "litellm", "cohere", "mistralai", "google",
    "vertexai", "boto3", "botocore", "azure", "langchain", "dspy",
}

# Paid hosts that must never appear as a literal on the enforcement path.
PAID_HOSTS = ("api.deepseek.com", "api.openai.com", "anthropic.com",
              "generativelanguage.googleapis.com")

ALLOWED_LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0")


def _import_roots(src: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def main() -> int:
    problems: list[str] = []
    for rel in ENFORCEMENT_MODULES:
        path = REPO_ROOT / rel
        if not path.exists():
            problems.append(f"{rel}: missing (the enforcement path must ship)")
            continue
        src = path.read_text(encoding="utf-8")
        paid = _import_roots(src) & PAID_IMPORT_ROOTS
        if paid:
            problems.append(f"{rel}: imports a paid provider on the enforcement path: "
                            f"{sorted(paid)}")
        for host in PAID_HOSTS:
            if host in src:
                problems.append(f"{rel}: references the paid host {host!r}")

    if problems:
        print("FAIL - the enforcement path is not local-only (AGENTS.md D6, Amendment 1):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"OK - {len(ENFORCEMENT_MODULES)} enforcement modules import no paid provider "
          f"(AGENTS.md D6)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
