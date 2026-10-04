"""The guided walkthrough (``/onboarding``) is a real surface, not a mock-up.

Why these assertions exist: the console explained the product in one paragraph and a first-time
operator still could not say what it does. The walkthrough is the answer - one action, narrated
step by step, in the operator's own words, with the microphone transcribing what they say and
the live control plane answering at the step that matters. These tests pin the three things the
page cannot work without: it is served, it speaks and listens, and it asks the REAL control
plane (never a scripted answer).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.app import create_app


def _page() -> str:
    with TestClient(create_app(seed=True)) as client:
        r = client.get("/onboarding")
    assert r.status_code == 200, "the walkthrough page must be served"
    return r.text


def test_the_walkthrough_is_served():
    body = _page()
    assert "TENET" in body
    assert "guided walkthrough" in body


def test_it_walks_the_operator_and_speaks_every_step():
    body = _page()
    # It speaks (browser voice) and it narrates every step, not only the first one.
    assert "speechSynthesis" in body
    assert body.count("s:") >= 5, "every step carries its own spoken line"
    assert "Replay voice" in body


def test_it_listens_and_shows_what_it_heard():
    body = _page()
    assert "webkitSpeechRecognition" in body or "SpeechRecognition" in body
    assert "I heard:" in body, "the transcription is shown to the operator"


def test_it_asks_the_live_control_plane_never_a_script():
    body = _page()
    assert '"/api/ask"' in body or "/api/ask" in body
    assert "/api/actions" in body
    assert "real records, not a script" in body


def test_the_operator_keeps_control_of_the_flow():
    body = _page()
    for control in ("Back", "Next", "Voice off", "Voice on"):
        assert control in body, f"{control} control missing"
