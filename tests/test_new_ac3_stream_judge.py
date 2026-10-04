"""NEW-AC3 — the judge over the STREAM (brief 2026-10-04).

The kernel already held both halves and handed out neither joined: every action on the record
carries the class the kernel decided it under, and the taxonomy says who decides that class - but
nothing on the way out put the two together, so a person reading the ledger had to know the table
by heart. ``GET /api/stream`` is that join, read-only, and this module pins it.

Three tests, one per clause of the criterion:

* the view reports EXACTLY the classes of the rows it is given, and no class outside the closed
  set ``{observe, read_personal, draft, write_reversible, irreversible, authorize}``;
* an unclassified tool is answered with R1's refusal sentence, verbatim - not a blank;
* the endpoint the view reads is read-only and judges every real row it publishes.

The closed set and the decider lines are never re-typed here: they are read from ``/api/state``
(the node's own ``class_listing()``), which is the point of the criterion.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app
from control_plane.kernel import R1_REFUSAL, stream_row

# The ladder, from the brief and from node/warrnt/actions.py - named here only to assert that the
# view adds nothing of its own. The view itself reads this set from the kernel.
CLOSED_SET = ("observe", "read_personal", "draft", "write_reversible", "irreversible", "authorize")


@pytest.fixture()
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A live instance with a real URL on a dead port: a genuine attempted crossing."""
    monkeypatch.setenv("TENET_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TENET_MODE", "live")
    monkeypatch.setenv("WARRNT_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("WARRNT_DEV", "1")
    monkeypatch.setenv("WARRNT_UPSTREAM", "http://127.0.0.1:9/mcp")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with TestClient(create_app(seed=True)) as c:
        yield c


def _taxonomy(client) -> dict[str, dict]:
    """The node's own taxonomy, keyed by class - the same listing /api/state publishes."""
    listing = client.get("/api/state").json()["actions"]
    return {str(c["class"]): c for c in listing}


def _row(index: int, cls: str, tool: str) -> dict:
    """One action row in the shape the kernel records (the fields the view reads, nothing more)."""
    return {"action_id": f"A-90{index:02d}", "run_id": f"run-{index}", "ts": 1759420000 + index,
            "agent": "report-bot", "tool": tool, "action_class": cls, "decision": "allow",
            "state": "approved", "reason": f"class {cls} · whatever the kernel said"}


def test_new_ac3_the_view_reports_the_classes_of_the_rows_it_is_given(client):
    """Feed 3 rows -> the view reports 3 classes, all inside the closed set, and no other."""
    taxonomy = _taxonomy(client)
    fed = [_row(1, "observe", "infra.plan"),
           _row(2, "read_personal", "crm.read"),
           _row(3, "irreversible", "payments.transfer")]
    rows = [stream_row(r, taxonomy) for r in fed]
    assert len(rows) == 3, "the view must report one row per fed action, and it did not"
    reported = [r["class"] for r in rows]
    assert reported == ["observe", "read_personal", "irreversible"], reported
    assert set(reported) <= set(CLOSED_SET), "the view reported a class outside the closed set"
    # The decider line is the taxonomy's own, not a paraphrase, and nothing is unclassified here.
    for row in rows:
        assert row["decider_text"] == taxonomy[row["class"]]["decider_text"]
        assert row["unclassified"] is False


def test_new_ac3_an_unclassified_tool_shows_r1s_refusal_not_a_blank():
    """A tool the layer never classified is REFUSED with R1's sentence - never a blank class."""
    taxonomy = {"observe": {"class": "observe", "decider": "machine",
                            "decider_text": "the node decides", "meaning": "read-only"}}
    row = stream_row({"action_id": "A-999", "tool": "unknown.tool", "action_class": "",
                      "decision": "deny", "reason": R1_REFUSAL}, taxonomy)
    assert row["class"] is None, "an unclassified act must not be given a class"
    assert row["unclassified"] is True
    assert row["decider_text"] == R1_REFUSAL, (
        "the view must quote R1 word for word, not leave a blank: %r" % row["decider_text"])
    assert "no action class for this tool" in row["decider_text"]
    assert "refuses what it cannot classify" in row["decider_text"]


def test_new_ac3_endpoint_the_view_reads_is_read_only_and_judges_every_row(client):
    """The endpoint the view reads: real rows, each judged, and no way to act through it."""
    assert client.post("/api/scenario/journey").status_code == 200
    r = client.get("/api/stream?limit=10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["closed_set"] == list(CLOSED_SET), body["closed_set"]
    assert body["refusal"] == R1_REFUSAL
    assert body["authority_source"] == "tenet-kernel" and body["llm_authority"] is False
    assert body["count"] == len(body["stream"]) > 0, "the journey committed four real actions"
    for row in body["stream"]:
        assert row["decider_text"], "every row carries a decider line, including a refusal"
        assert row["class"] in CLOSED_SET or (row["class"] is None
                                             and row["decider_text"] == R1_REFUSAL)
        if row["class"] in CLOSED_SET:
            assert row["decider_text"] == body["deciders"][row["class"]]
    # The view can only be read: no write, no allow, no deny anywhere on this path.
    assert client.post("/api/stream").status_code == 405
    # The counts the observer's fourth state renders are the SAME projections /api/state publishes.
    state = client.get("/api/state").json()["control"]
    assert body["counts"] == state["counts"] and body["pending"] == state["pending"]

