"""TENET's own voice is a served artefact, not a claim.

Why these assertions exist: the walkthrough used to speak with whatever voice the visitor's
laptop happened to have, which meant the character in the film and the character in the product
were two different women. The journey now plays TENET's own locked clips (Grok Ara — the film's
character), one per line, served as files; there is no device fallback at all. These tests pin
that: the clips exist (beats AND narration), they are served as audio, the route refuses anything
that is not a clip, and the single page asks for TENET first — and only TENET.

Since the merge (04.10.2026) the map and the player live in ONE module (`/voice.js`): the guide
used to carry a second copy of both, which is how two voices got into one product.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
BEATS = ["gate", "say", "see", "understand", "decide", "witness", "prove", "win"]
# The narration lines, keyed exactly like voice.js's LINES/LINES-clip map (04.10.2026).
LINES = ["listen", "heard", "proposes", "check", "allow", "deny", "denyAfter", "wait",
         "waitDecision", "crossed", "nothingCrossed", "canCross", "proof", "win", "notEvaluated"]


def test_every_beat_has_its_own_clip_on_disk():
    for beat in BEATS:
        clip = REPO / "audio" / f"{beat}.mp3"
        assert clip.is_file(), f"the journey speaks {beat}, but {clip.name} is missing"
        assert clip.stat().st_size > 8000, f"{clip.name} is too small to be a spoken line"


def test_every_line_has_its_own_clip_on_disk():
    """One voice means every narration line is a studio clip, not a synthesised fallback."""
    for key in LINES:
        clip = REPO / "audio" / f"line-{key}.mp3"
        assert clip.is_file(), f"the character says {key}, but {clip.name} is missing"
        assert clip.stat().st_size > 5000, f"{clip.name} is too small to be a spoken line"


def test_the_clips_are_served_as_audio():
    with TestClient(create_app(seed=True)) as client:
        for beat in BEATS:
            r = client.get(f"/audio/{beat}.mp3")
            assert r.status_code == 200, f"/audio/{beat}.mp3 must be served"
            assert r.headers["content-type"].startswith("audio/mpeg")
            assert len(r.content) == (REPO / "audio" / f"{beat}.mp3").stat().st_size


def test_the_line_clips_are_served_as_audio():
    """Every narration clip is a real served artefact — the voice the page actually plays."""
    with TestClient(create_app(seed=True)) as client:
        for key in LINES:
            r = client.get(f"/audio/line-{key}.mp3")
            assert r.status_code == 200, f"/audio/line-{key}.mp3 must be served"
            assert r.headers["content-type"].startswith("audio/mpeg")
            assert len(r.content) == (REPO / "audio" / f"line-{key}.mp3").stat().st_size


def test_the_voice_route_refuses_anything_that_is_not_a_clip():
    with TestClient(create_app(seed=True)) as client:
        for bad in ["app.py", "say.wav", "say.mp3.bak", "..%2fapp.py", "unknown.mp3", ""]:
            assert client.get(f"/audio/{bad}").status_code == 404, f"/audio/{bad} must not be served"


def test_the_page_plays_tenet_first_and_only_tenet():
    """One voice: every line is TENET's own clip, and there is no second engine to fall back to."""
    with TestClient(create_app(seed=True)) as client:
        body = client.get("/").text
        module = client.get("/voice.js").text
    assert '<script src="voice.js"></script>' in body, (
        "the one page must load the one module — the voice engine lives in exactly one file")
    assert '"audio/gate.mp3"' in module and '"audio/win.mp3"' in module, (
        "the module must ask for TENET's clips — host-relative, so the Pages subpath resolves too"
    )
    assert '"audio/line-listen.mp3"' in module and '"audio/line-notEvaluated.mp3"' in module, (
        "the narration lines are TENET's clips too, not a synthesised fallback")
    assert "new Audio(clip)" in module, "a clip must be played, not just mapped"
    assert "greeting = true" in module, "the door line must be spoken before the first beat"
    # The whole point: no device synthesiser exists, so no code path can reach a second voice.
    for forbidden in ("speechSynthesis", "SpeechSynthesisUtterance", "pickVoice", "speakDevice"):
        assert forbidden not in module, (
            "a device engine is a second voice (%r): one product, one voice" % forbidden)
    # NEW-AC7 — the claim: "which voice speaks" is the chip that reports what actually PLAYED, not a
    # sentence at the foot of the page (see tests/test_new_ac7_the_claim.py for the choice recorded).
    assert 'id="voiceChip"' in body, "the page must not hide which voice speaks — the chip says so"
    assert 'lastOrigin = "locked-clip"' in module, "the chip reads the real playback origin, not a lookup"
