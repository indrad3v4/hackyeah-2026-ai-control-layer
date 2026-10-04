"""The guide is one module, and it reports what it actually did.

Why these assertions exist: the onboarding taught the product a voice, and the pattern was then
asked to cover EVERY surface — but a second copy of the lines is a second source of truth, and a
chip that says "studio voice" while the device is speaking is exactly the class of untrue claim
TENET exists to prevent. So: one served module, the missing `notEvaluated` state in it, provenance
derived from playback and never from a static lookup, and the console actually loading it.

The merge (04.10.2026) finished the job the module started: the guide's inline copy of the engine is
gone, so the app now holds exactly ONE implementation of the voice — this file. `test_one_engine`
pins that, because a second copy is exactly what drifted before.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
VOICE = REPO / "voice.js"
CONSOLE = REPO / "index.html"
GUIDE_LAYER = REPO / "index.html"  # the guide is a layer of the console since 04.10.2026


def module_src(repo):
    """The one voice module's source, read once for the checks that must name it."""
    return (repo / "voice.js").read_text(encoding="utf-8")


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
    # Read the LINES entry (the character's words). CLIPS is a sibling map that now also carries a
    # `notEvaluated:` key pointing at the clip, so scope the read to the LINES block.
    lines = src.split("const LINES = {", 1)[1].split("};", 1)[0]
    line = lines.split("notEvaluated:", 1)[1].split("\n", 1)[0]
    assert "could not reach" in line.lower(), "the line must name what actually happened"
    assert "HTTP" not in line, "the spoken line must not dress a transport code as a verdict"


def test_provenance_comes_from_playback_not_from_a_static_lookup():
    src = VOICE.read_text(encoding="utf-8")
    assert "onplaying" in src, "the clip must report itself as played before it may be claimed"
    assert 'lastOrigin = "silent"' in src, "a clip that cannot play must relabel the origin silent"
    # selecting the clip must never be what names the origin
    assert 'lastOrigin = "locked-clip"; paintChip();' in src


def test_every_surface_loads_the_one_module():
    console = CONSOLE.read_text(encoding="utf-8")
    assert '<script src="voice.js"></script>' in console, "the console must load the module"
    assert 'id="voiceChip"' in console and 'id="voiceGate"' in console
    assert "Turn on the sound." in console, "the console carries the onboarding's gate copy"
    assert "notEvaluated" in module_src(REPO), (
        "the state the surfaces report must have a line in the one module"
    )


def test_one_engine_the_guide_keeps_no_copy_of_the_voice():
    """The merge's whole point: a second implementation of the voice is what drifted, so there is none.

    The console may only CONSUME the module. If `speechSynthesis`, `pickVoice` or `clipFor` appears in
    index.html again, a second engine has been reintroduced and the two will disagree.
    """
    console = CONSOLE.read_text(encoding="utf-8")
    for forbidden in ("speechSynthesis", "function pickVoice", "function clipFor(", "new Audio("):
        assert forbidden not in console, (
            "index.html carries a second voice engine (%r) — the app must hold exactly one" % forbidden)
    assert 'src="voice.js"' in console, "the console must consume the one module"


def test_both_surfaces_claim_the_same_sound_label_vocabulary():
    """One vocabulary, two consumers: the module owns the labels, the page only consumes them."""
    module = VOICE.read_text(encoding="utf-8")
    assert "TENET · studio voice" in module, "the module owns the studio-voice label"
    # ONE voice, structurally: the labels the module may show are the studio clip, muted and silent.
    # There is no "device voice" label, because there is no device voice to fall back to.
    assert "sound — " in module
    assert "device voice" not in module, (
        "a device-voice label would name a second voice that must not be reachable")
    console = CONSOLE.read_text(encoding="utf-8")
    assert "TENET · studio voice" not in console, (
        "the page must not restate the label: the module owns the vocabulary")
    assert "sound — " in console, "the chip is the page's element, filled by the module"
