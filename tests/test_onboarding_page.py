"""The guided walkthrough (``/onboarding``) is a real surface, not a mock-up.

Why these assertions exist: the console explained the product in one paragraph and a first-time
operator still could not say what it does. The walkthrough is the answer - one action, narrated
step by step by a character who lives in the page, with the microphone transcribing what the
operator says and the live control plane answering at the step that matters.
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
    assert "TENET" in body and "walk with Nadia" in body


def test_the_character_lives_in_the_page_and_asks_for_the_sound():
    body = _page()
    assert "Nadia" in body, "the guide is a named character, not a bare voice"
    assert 'id="gate"' in body and "Turn on sound" in body, (
        "a browser needs one gesture before audio: the character asks for it")
    assert 'id="gateChar"' in body, "the character is shown in the sound gate, not just text"
    assert "charState" in body and "speak" in body and "listen" in body


def test_the_journey_map_shows_where_the_operator_is():
    body = _page()
    assert 'id="map"' in body and 'id="walker"' in body, "the character walks a visible map"
    assert body.count("node:") >= 5, "every step has its own node on the map"


def test_there_is_basic_gamification_that_rewards_real_control():
    body = _page()
    assert "control score" in body, "a score the operator can see"
    assert "receipt earned" in body and "You won" in body and "Copy the receipt" in body
    assert "Play again" in body, "the run can be replayed"


def test_it_speaks_every_step_listens_and_never_scripts_the_answer():
    body = _page()
    assert body.count("s:") >= 5, "every step carries its own spoken line"
    assert "webkitSpeechRecognition" in body or "SpeechRecognition" in body
    assert "Nadia heard:" in body, "the transcription is shown to the operator"
    assert "/api/ask" in body and "/api/actions" in body
    assert "real records, not a script" in body
    assert "this run" in body and "replace(/[^0-9]/g" in body, (
        "the evidence line names THIS run, not the oldest row of a newest-first list")


def test_the_operator_keeps_control_of_the_flow():
    body = _page()
    for control in ("Back", "Next", "Sound off", "Sound on", "Read instead"):
        assert control in body, f"{control} control missing"
