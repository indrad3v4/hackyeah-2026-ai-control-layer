"""AC: a crossing whose reply carries no value for the asked symbol names what it did carry.

Before the change ``_record_crossing`` filed ``value`` and, when the upstream answered with
symbols the caller had not asked for, the record went silent: no value, no reason - and the
assistant could only say "the result block carries no rate". The honest fix names the symbol
the reply answered and the symbols it actually returned. Nothing is derived or invented.

No network: the kernel is driven in-process and the "result" is the upstream's own reply
shape, handed in exactly as the proxy carries it.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.app import create_app


def _kernel(tmp_path, monkeypatch):
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("WARRNT_UPSTREAM", "http://127.0.0.1:9/mcp")
    return create_app(seed=True)


def _crossing(kernel, action_id, result):
    kernel.proxy.actions.record(action_id=action_id, run_id="t-missing-symbol",
                                agent="fx-trader", tool="fx.read_rate")
    kernel._record_crossing("fx.read_rate", {"action_id": action_id, "result": result}, True)
    return kernel.proxy.actions.get(action_id).execution_result


def test_a_reply_without_the_asked_symbol_names_the_symbols_it_did_return(tmp_path, monkeypatch):
    app = _kernel(tmp_path, monkeypatch)
    with TestClient(app):
        kernel = app.state.kernel
        asked_for_eur = {"ok": True, "endpoint": "https://api.frankfurter.dev/v1/latest",
                         "http_status": 200, "response_sha256": "a" * 64, "latency_ms": 12.0,
                         "symbol": None, "rates": {"CHF": 0.93, "USD": 1.09}}
        xr = _crossing(kernel, "A-missing-1", asked_for_eur)
        assert xr.get("http_status") == 200                      # the crossing is still filed
        assert xr.get("value") is None                            # no value for the asked symbol
        assert xr.get("rates_returned") == ["CHF", "USD"]         # ...and the record says what came
        assert xr.get("value_symbol") is None   # absent, not guessed

        answered = {"ok": True, "endpoint": "https://api.frankfurter.dev/v1/latest",
                    "http_status": 200, "response_sha256": "b" * 64, "latency_ms": 9.0,
                    "symbol": "EUR", "value": 0.22844, "rates": {"EUR": 0.22844}}
        xr2 = _crossing(kernel, "A-missing-2", answered)
        assert xr2.get("value") == 0.22844                        # the ask WAS answerable
        assert xr2.get("value_symbol") == "EUR"
        assert xr2.get("rates_returned") == ["EUR"]

        multi = {"ok": True, "endpoint": "https://api.frankfurter.dev/v1/latest",
                 "http_status": 200, "response_sha256": "c" * 64, "latency_ms": 18.0,
                 "symbol": "EUR,USD", "rates": {"EUR": 0.22844, "USD": 0.25636}}
        xr3 = _crossing(kernel, "A-missing-3", multi)
        assert xr3.get("value") is None                     # no single value for two symbols
        assert xr3.get("rates") == {"EUR": 0.22844, "USD": 0.25636}   # the map itself is filed
        assert xr3.get("rates_returned") == ["EUR", "USD"]
