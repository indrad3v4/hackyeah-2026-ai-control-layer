"""The guide is one module, and it reports what it actually did.

Why these assertions exist: the onboarding taught the product a voice, and the pattern was then
asked to cover EVERY surface — but a second copy of the lines is a second source of truth, and a
chip that says "studio voice" while the device is speaking is exactly the class of untrue claim
TENET exists to prevent. So: one served module, the missing `notEvaluated` state in it, provenance
derived from playback and never from a static lookup, and the console actually loading it.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
VOICE = REPO / "voice.js"
CONSOLE = REPO / "index.html"
ONBOARDING = REPO / "onboarding.html"


def test_the_voice_module_is_served_as_javascript():
    with TestClient(create_app(seed=True)) as client:
        r = client.get("/voice.js")
        assert r.status_code == 200, "/voice.js must be served"
        assert r.headers["content-type"].startswith("application/javascript")
        assert r.content == VOICE.read_bytes(), "the route must serve the file, not a paraphrase"


def test_assets_are_host_relative():
    """Railway serves at /, GitHub Pages at /<repo>/ — an absolute path breaks one of them."""
    module = VOICE.read_text(encoding="utf-8")
    assert '"/audio/' not in module, "the clip paths must resolve on both hosts"
    assert 'audio/gate.mp3' in module
    console = CONSOLE.read_text(encoding="utf-8")
    assert 'src="voice.js"' in console


def test_the_loop_carries_the_state_it_was_missing():
    """A transport failure leaves no kernel record, so the character may not speak a verdict."""
    src = VOICE.read_text(encoding="utf-8")
    assert "notEvaluated:" in src, "the guide has no line for the state the surfaces report"
    line = src.split("notEvaluated:", 1)[1].split("\n", 1)[0]
    assert "could not reach" in line.lower(), "the line must name what actually happened"
    assert "HTTP" not in line, "the spoken line must not dress a transport code as a verdict"


def test_provenance_comes_from_playback_not_from_a_static_lookup():
    src = VOICE.read_text(encoding="utf-8")
    assert "onplaying" in src, "the clip must report itself as played before it may be claimed"
    assert 'lastOrigin = "device"' in src, "a fallback must relabel the origin"
    # selecting the clip must never be what names the origin
    assert 'const clip = els.clipKey ? CLIPS[els.clipKey] : null;' in src


def test_every_surface_loads_the_one_module():
    console = CONSOLE.read_text(encoding="utf-8")
    assert '<script src="voice.js"></script>' in console, "the console must load the module"
    assert 'id="voiceChip"' in console and 'id="voiceGate"' in console
    assert "Turn on the sound." in console, "the console carries the onboarding's gate copy"
    assert "notEvaluated" in ONBOARDING.read_text(encoding="utf-8"), (
        "the walkthrough keeps its own line map and must carry the same missing state"
    )


def test_both_surfaces_claim_the_same_sound_label_vocabulary():
    """One vocabulary, two consumers: the module owns the labels, the walkthrough keeps its map."""
    module = VOICE.read_text(encoding="utf-8")
    assert "TENET · studio voice" in module, "the module owns the studio-voice label"
    assert "sound — " in module and "device voice" in module
    onboard = ONBOARDING.read_text(encoding="utf-8")
    assert "TENET · studio voice" in onboard
    assert 'playedOrigin==="locked-clip"' in onboard, (
        "the walkthrough's chip must read the playback origin, not clipFor()"
    )
