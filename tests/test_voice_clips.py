"""TENET's own voice is a served artefact, not a claim.

Why these assertions exist: the walkthrough used to speak with whatever voice the visitor's
laptop happened to have, which meant the character in the film and the character in the product
were two different women. The journey now plays TENET's own locked clips (Grok Ara — the film's
character), one per beat, served as files; the device voice survives only as the fallback for a
browser that refuses to play audio. These tests pin that: the clips exist, they are served as
audio, the route refuses anything that is not a clip, and the page asks for TENET first.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
BEATS = ["gate", "say", "see", "understand", "decide", "witness", "prove", "win"]


def test_every_beat_has_its_own_clip_on_disk():
    for beat in BEATS:
        clip = REPO / "audio" / f"{beat}.mp3"
        assert clip.is_file(), f"the journey speaks {beat}, but {clip.name} is missing"
        assert clip.stat().st_size > 8000, f"{clip.name} is too small to be a spoken line"


def test_the_clips_are_served_as_audio():
    with TestClient(create_app(seed=True)) as client:
        for beat in BEATS:
            r = client.get(f"/audio/{beat}.mp3")
            assert r.status_code == 200, f"/audio/{beat}.mp3 must be served"
            assert r.headers["content-type"].startswith("audio/mpeg")
            assert len(r.content) == (REPO / "audio" / f"{beat}.mp3").stat().st_size


def test_the_voice_route_refuses_anything_that_is_not_a_clip():
    with TestClient(create_app(seed=True)) as client:
        for bad in ["app.py", "say.wav", "say.mp3.bak", "..%2fapp.py", "unknown.mp3", ""]:
            assert client.get(f"/audio/{bad}").status_code == 404, f"/audio/{bad} must not be served"


def test_the_page_plays_tenet_first_and_keeps_the_device_voice_as_a_fallback():
    with TestClient(create_app(seed=True)) as client:
        body = client.get("/onboarding").text
    assert '"/audio/gate.mp3"' in body and '"/audio/win.mp3"' in body, "the page must ask for TENET's clips"
    assert "new Audio(clip)" in body, "a clip must be played, not just mapped"
    assert "greeting=true" in body, "the door line must be spoken before the first beat"
    assert "function speakDevice(" in body, "the device voice must survive as the fallback"
    assert "u.rate=0.94" in body and "u.pitch=0.85" in body, "the fallback keeps the character direction"
    assert "the same character direction as the film" in body, "the page must not hide which voice speaks"
