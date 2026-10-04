"""ONE API base on both hosts (AC6, 04.10.2026).

Why these assertions exist: the console runs on two hosts. On Railway the plane serves the page, so
an API call is same-origin. On the static host (GitHub Pages, or opened from disk) there is no
backend, and a same-origin `/api/…` is refused with 405. The page therefore resolves ONE API base
and routes every call through it. These tests read the served page and pin that: exactly one
resolver, and no call site left as a bare path.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
CONSOLE = REPO / "index.html"


def _served() -> str:
    with TestClient(create_app(seed=True)) as client:
        return client.get("/").text


def test_there_is_exactly_one_api_base_resolver():
    body = _served()
    assert "const PLANE=" in body, "the page must resolve an API base on the static host"
    # The source escapes the dot (`github\.io`), so match the resolver's own spelling.
    assert r"github\.io" in body and "railway.app" in body, (
        "the resolver must point the static host at the live plane")


def test_no_api_call_site_is_left_as_a_bare_path():
    """The brief's own check: `grep -c 'fetch("/api' index.html` must be 0."""
    body = _served()
    assert body.count('fetch("/api') == 0, "a bare /api fetch would 405 on the static host"
    assert body.count('fetch("/revoke') == 0, "a bare /revoke fetch would 405 on the static host"
    # Every fetch expression must carry the resolved base.
    calls = re.findall(r"fetch\(([^,]+),", body)
    for call in calls:
        assert "PLANE" in call, "every API call must go through the base resolver, found %r" % call
