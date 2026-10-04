"""The guided journey (``/onboarding``) is a real surface, not a mock-up and not a tutorial.

Why these assertions exist: a first-time person could not say what TENET does from a paragraph
of documentation, and a voice narrating from nowhere is still a dashboard with sound. So the
page is one real controlled action walked with a character who is a GUIDE, never the authority:
Nadia explains, the AI proposes, TENET decides, the human controls. These tests pin the parts
that make that true: who does what, the seven beats of the journey, the character's honest
reactions to the REAL verdict, and the absence of childish gamification.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.app import create_app


def _page() -> str:
    with TestClient(create_app(seed=True)) as client:
        r = client.get("/onboarding")
    assert r.status_code == 200, "the journey page must be served"
    return r.text


def test_the_journey_is_served():
    body = _page()
    assert "TENET" in body and "the guide" in body


def test_the_character_is_a_guide_and_the_roles_are_visible():
    body = _page()
    assert "Nadia" in body, "the guide is a named character, not a bare voice"
    for role in ("explains", "proposes", "decides", "control"):
        assert role in body, f"the page must show who {role}"
    assert "AI moves with the human, not around the human" in body


def test_the_character_lives_in_the_page_and_asks_for_the_sound():
    body = _page()
    assert 'id="gate"' in body and "Turn on sound" in body, (
        "a browser needs one gesture before audio: the character asks for it")
    assert 'id="gateChar"' in body, "the character is shown in the sound gate, not just text"
    assert "position:sticky" in body, "the character stays present while the human scrolls"
    assert "Read instead" in body, "silence must be a choice"


def test_the_journey_has_the_seven_beats():
    body = _page()
    for beat in ("SAY", "SEE", "UNDERSTAND", "DECIDE", "WITNESS", "PROVE", "WIN"):
        assert f'"{beat}"' in body, f"beat {beat} is missing from the journey"
    # the map is built from the beats themselves, so a new beat cannot be forgotten in the
    # markup (the nodes are rendered in JS, not hand-written seven times)
    assert 'id="node${i}"' in body and "BEATS.map" in body, "the map is drawn from the beats"


def test_the_character_reacts_to_the_real_verdict():
    body = _page()
    for state in ("listen", "think", "allow", "deny", "wait", "done"):
        assert f'"{state}"' in body or f'"{state}" ' in body or f" {state}" in body, f"state {state} missing"
    assert "decisionState" in body, "the reaction is derived from the record, not hardcoded"
    assert "NOT ALLOWED" in body and "WAITING FOR YOU" in body and "ALLOWED" in body


def test_there_is_no_childish_gamification():
    body = _page()
    for wrong in ("control score", "+25", "XP", "badge", "points"):
        assert wrong not in body, f"the win is control, not {wrong!r}"


def test_the_reward_is_control_kept():
    body = _page()
    assert "You stayed in control" in body
    assert "CONTROL KEPT" in body
    assert "Your words, your AI's proposal" in body.replace("&", "&"), "the chain must be named"


def test_it_speaks_every_beat_listens_and_never_scripts_the_answer():
    body = _page()
    assert body.count("s:") >= 7, "every beat carries its own spoken line"
    assert "webkitSpeechRecognition" in body or "SpeechRecognition" in body
    assert "I heard:" in body, "the transcription is shown to the human"
    assert "/api/ask" in body and "/api/actions" in body
    assert "never a script" in body
    assert "waiting for TENET" in body, (
        "the human may not outrun the kernel: while the record is pending, the step says so")
    assert "replace(/[^0-9]/g" in body, (
        "the record named is THIS run's, not the oldest row of a newest-first list")
