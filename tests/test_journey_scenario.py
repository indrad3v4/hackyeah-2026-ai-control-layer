"""Tests for the credential-free JOURNEY (``POST /api/scenario/journey``).

The page promises: one control plane, four real requests, four verdicts - an allow that
crosses, a redaction, a denial that never reaches the far side, and a hold that waits for a
person. Before this endpoint existed the only button on the page ran the allow half and the
copy claimed two verdicts it did not produce.

Each test is one acceptance criterion and fails on the code before the change:

* AC1 - the journey runs in-process with NO credential: four beats, four real kernel
        decisions, four distinct verdicts, each with its own record;
* AC2 - the DENY beat leaves the far side untouched (``executed`` and ``upstream_contacted``
        both false) - the boundary's own counters, not a promise;
* AC3 - the HOLD beat is a hold: decision ``human``, nothing executed, so a person still has
        to decide;
* AC4 - no upstream configured -> 503 and no record invented; a second immediate call is
        rate limited (429 with a real ``retry_after_s``).

No network: ``TestClient`` drives the app in-process against a dead upstream port, and the
kernel is the repository's own, never a stub.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app, JOURNEY_STEPS, JOURNEY_RUN_PREFIX


def _client(tmp_path, monkeypatch, upstream: str | None) -> TestClient:
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    if upstream is None:
        monkeypatch.delenv("WARRNT_UPSTREAM", raising=False)
    else:
        monkeypatch.setenv("WARRNT_UPSTREAM", upstream)
    return TestClient(create_app(seed=True))


@pytest.fixture()
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A live instance with a real URL on a dead port: a genuine attempted crossing."""
    with _client(tmp_path, monkeypatch, "http://127.0.0.1:9/mcp") as c:
        yield c


def test_ac1_journey_is_credential_free_and_reaches_four_verdicts(client):
    """AC1 - no credential goes in, four real verdicts come out, each with its own record."""
    r = client.post("/api/scenario/journey")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"].startswith(JOURNEY_RUN_PREFIX)
    steps = body["steps"]
    assert len(steps) == len(JOURNEY_STEPS) == 4, steps
    assert [s["beat"] for s in steps] == [beat for beat, _, _, _ in JOURNEY_STEPS]
    verdicts = [s["decision"] for s in steps]
    assert len(set(verdicts)) == 4, f"the four beats collapsed to {verdicts}"
    for s in steps:
        assert s["action_id"], f"the {s['beat']} beat wrote no record: {s}"
        assert s["decision"] in {"allow", "redact", "deny", "human"}, s
        assert isinstance(s["executed"], bool), s
    summary = body["summary"]
    assert summary["distinct_verdicts"] == 4, summary
    assert summary["verdicts"] == verdicts, summary
    # The response must carry no credential of any kind.
    assert "token" not in r.text.lower().replace("tokens", ""), "a token reached the browser"


def test_ac2_the_denied_beat_leaves_the_far_side_untouched(client):
    """AC2 - the deny beat is a real denial: nothing executed, no upstream contact."""
    steps = client.post("/api/scenario/journey").json()["steps"]
    deny = next(s for s in steps if s["beat"] == "deny")
    assert deny["decision"] == "deny", deny
    assert deny["executed"] is False, f"a denied call executed: {deny}"
    assert deny["upstream_contacted"] is False, f"a denied call reached the far side: {deny}"
    assert client.post("/api/scenario/journey").status_code == 429  # keeps the store quiet
    actions = client.get("/api/actions").json()["actions"]
    denied = [a for a in actions if str(a.get("action_id")) == str(deny["action_id"])]
    assert denied, f"the denied action is not on the record: {deny['action_id']}"


def test_ac3_the_hold_waits_for_a_person(client):
    """AC3 - the hold beat is held: decision human, nothing executed, a person must decide."""
    steps = client.post("/api/scenario/journey").json()["steps"]
    hold = next(s for s in steps if s["beat"] == "hold")
    assert hold["decision"] == "human", hold
    assert hold["executed"] is False, f"a held call executed: {hold}"
    assert hold["action_id"], hold


def test_ac4_no_upstream_refuses_and_rate_limits_honestly(tmp_path, monkeypatch):
    """AC4 - no upstream -> 503 with no record; a second immediate call is a real 429."""
    with _client(tmp_path, monkeypatch, None) as c:
        before = c.get("/api/actions").json()["actions"]
        r = c.post("/api/scenario/journey")
        assert r.status_code == 503, r.text
        assert c.get("/api/actions").json()["actions"] == before, "a record was invented"
    with _client(tmp_path, monkeypatch, "http://127.0.0.1:9/mcp") as c:
        assert c.post("/api/scenario/journey").status_code == 200
        second = c.post("/api/scenario/journey")
        assert second.status_code == 429, second.text
        assert second.json()["retry_after_s"] >= 1, second.text
