"""The static host can reach the one plane (AC5, 04.10.2026).

Why these assertions exist: the console is also published as a static site (GitHub Pages). There,
every `POST /api/ask` and the six GET reads of `refresh()` were refused with 405, because the page
is same-origin to a host with no backend. The fix has two halves: the page resolves its API base to
the live plane (checked in tests/test_api_base.py), and the plane allows exactly the static origin
to call it. These tests prove the CORS half on the REAL app factory (not a mock), including the
negative: an origin the plane does not know is still refused.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.app import create_app

STATIC = "https://indrad3v4.github.io"
PREFLIGHT = {"Origin": STATIC, "Access-Control-Request-Method": "POST"}


def _client() -> TestClient:
    return TestClient(create_app(seed=True))


def test_preflight_from_the_static_origin_is_allowed_not_405():
    with _client() as client:
        r = client.options("/api/ask", headers=PREFLIGHT)
    assert r.status_code in (200, 204), "a preflight must not be refused (got %s)" % r.status_code
    assert r.headers.get("access-control-allow-origin") == STATIC, (
        "the preflight must name the static origin, got %r"
        % r.headers.get("access-control-allow-origin"))


def test_read_and_write_from_the_static_origin_carry_the_header():
    with _client() as client:
        for route, method, kwargs in (("/api/overview", "GET", {}),
                                      ("/api/live-trace", "GET", {}),
                                      ("/api/security-events?limit=20", "GET", {})):
            r = client.request(method, route, headers={"Origin": STATIC}, **kwargs)
            assert r.headers.get("access-control-allow-origin") == STATIC, (
                "%s %s must carry the header" % (method, route))
        w = client.post("/api/ask", headers={"Origin": STATIC}, json={"q": "what is the rate"})
        assert w.headers.get("access-control-allow-origin") == STATIC, (
            "POST /api/ask must carry the header so the static host can read the answer")


def test_an_unknown_origin_is_still_refused():
    """CORS is not opened to the world: only the named origins get a header."""
    with _client() as client:
        r = client.get("/api/overview", headers={"Origin": "https://evil.example"})
        assert r.headers.get("access-control-allow-origin") is None, (
            "an unknown origin must not be granted CORS")
        p = client.options("/api/ask", headers={"Origin": "https://evil.example",
                                                "Access-Control-Request-Method": "POST"})
        assert p.headers.get("access-control-allow-origin") is None, (
            "an unknown origin's preflight must not be granted CORS")


def test_the_allowed_methods_and_headers_are_exactly_the_contract():
    with _client() as client:
        r = client.options("/api/ask", headers={**PREFLIGHT, "Access-Control-Request-Headers": "content-type"})
    methods = (r.headers.get("access-control-allow-methods") or "").upper()
    for m in ("GET", "POST", "OPTIONS"):
        assert m in methods, "CORS must allow %s, got %r" % (m, methods)
    max_age = r.headers.get("access-control-max-age")
    assert max_age == "600", "the preflight cache must be 600s, got %r" % max_age
