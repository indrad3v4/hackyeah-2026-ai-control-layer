"""ONE voice across the whole journey (04.10.2026).

Why these assertions exist: `/voice.js` used to carry a per-beat clip map plus 15 narration LINES
with no clip of their own, so those lines fell back to the visitor's own device voice — the film's
character on the beats, a stranger on every narration line. The fix is structural, not a patch:
every line is now a locked studio clip (Grok Ara), and the module has NO device synthesiser at all,
so a second voice is impossible by construction. These tests pin that by walking the real CLIPS map
against the real LINES keys, and by driving the real module with a stubbed `Audio` — the only way to
prove a code path cannot reach a device synth is to run the code with none present.

The module is CommonJS-loadable (`module.exports`), so it can be required under node here; node is
available on this machine and the check skips cleanly if it is not, rather than passing vacuously.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
VOICE = REPO / "voice.js"
NODE = shutil.which("node")

# The seven beats the journey speaks, plus the door, exactly as `say()` is called.
BEAT_KEYS = ["gate", "SAY", "SEE", "UNDERSTAND", "DECIDE", "WITNESS", "PROVE", "WIN"]
# The narration lines that must each resolve to a clip (the 15 LINES keys).
LINE_KEYS = ["listen", "heard", "proposes", "check", "allow", "deny", "denyAfter", "wait",
             "waitDecision", "crossed", "nothingCrossed", "canCross", "proof", "win", "notEvaluated"]


def _clips_map() -> dict:
    """Read the REAL CLIPS map out of the served module (not a paraphrase)."""
    src = VOICE.read_text(encoding="utf-8")
    body = src.split("const CLIPS = {", 1)[1].split("};", 1)[0]
    return dict(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*"([^"]+)"', body))


def _lines_keys() -> set:
    src = VOICE.read_text(encoding="utf-8")
    body = src.split("const LINES = {", 1)[1].split("};", 1)[0]
    return set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", body, re.M))


def test_every_beat_key_resolves_to_a_clip():
    clips = _clips_map()
    for key in BEAT_KEYS:
        assert key in clips, f"the beat {key!r} has no clip in the CLIPS map"
        assert clips[key].endswith(".mp3"), f"{key} maps to {clips[key]!r}, not an mp3"


def test_every_lines_key_resolves_to_its_own_clip():
    """AC3: the real CLIPS map covers every LINES key with `audio/line-<key>.mp3`."""
    clips = _clips_map()
    lines = _lines_keys()
    assert len(lines) == 15, "the module must still carry exactly the 15 narration lines"
    for key in sorted(lines):
        assert key in clips, f"the line {key!r} has no clip — it would fall silent or to a device"
        assert clips[key] == f"audio/line-{key}.mp3", (
            f"the line {key!r} must map to its own clip, found {clips[key]!r}")
        assert (REPO / clips[key]).is_file(), f"{clips[key]} is not on disk"


def test_the_clip_is_the_only_voice_and_a_failed_clip_leaves_the_chip_silent():
    """AC4: run the REAL module under node with a stubbed `Audio` and no device synthesiser.

    The stub proves two things at once: that a line plays its clip (`locked-clip`), and that when
    the clip cannot play the character is SILENT — never a device synth (there is none in the file)
    and never a false `locked-clip`.
    """
    if NODE is None:
        pytest.skip("node is required to execute the module's own player")
    harness = r"""
const path = require('path');

// No device synthesiser exists in this realm at all: if the module reached for one it would throw.
global.window = {};
global.document = {
  _els: {},
  getElementById(id){ return this._els[id] || (this._els[id] = { textContent: "", style: {} }); }
};

let failNext = false;
global.Audio = function(src){
  this.src = src; this.onplaying = null; this.onended = null; this.onerror = null;
  this.play = function(){
    if (failNext) { failNext = false; const self = this;
      return Promise.resolve().then(() => { if (self.onerror) self.onerror(); }); }
    if (this.onplaying) this.onplaying();
    return Promise.resolve();
  };
  this.pause = function(){};
};
global.__setFail = v => { failNext = v; };

const mod = require(path.resolve(__dirname, '..', 'voice.js'));
mod.init({ chip: "voiceChip" });

const outcome = {};
for (const key of Object.keys(mod.LINES)) {
  mod.say(key);
  outcome[key] = { origin: mod.lastOrigin(), resolved: mod.clipFor(key) };
}
for (const key of ["gate","SAY","SEE","UNDERSTAND","DECIDE","WITNESS","PROVE","WIN"]) {
  mod.say(key);
  outcome[key] = { origin: mod.lastOrigin(), resolved: mod.clipFor(key) };
}

global.__setFail(true);
mod.say("listen");
outcome["__failed"] = { origin: mod.lastOrigin() };

process.stdout.write(JSON.stringify(outcome));
"""
    harness_path = REPO / "tests" / "_one_voice_harness.js"
    harness_path.write_text(harness, encoding="utf-8")
    try:
        proc = subprocess.run([NODE, str(harness_path)], capture_output=True, text=True, cwd=str(REPO))
        assert proc.returncode == 0, "the module failed to run under node: %s" % proc.stderr
        data = json.loads(proc.stdout)
    finally:
        harness_path.unlink(missing_ok=True)

    # Every LINES key played its own clip and reported the studio origin.
    for key in LINE_KEYS:
        assert data[key]["resolved"] == f"audio/line-{key}.mp3", (
            f"{key} resolved to {data[key]['resolved']!r}")
        assert data[key]["origin"] == "locked-clip", (
            f"{key} played but the chip said {data[key]['origin']!r}")
    # Every beat key played a clip too (the film's own 8).
    for key in BEAT_KEYS:
        assert data[key]["resolved"], f"beat {key} resolved to no clip"
        assert data[key]["origin"] == "locked-clip", f"beat {key} said {data[key]['origin']!r}"
    # The failure path: silent, never a device voice and never a false studio claim.
    assert data["__failed"]["origin"] == "silent", (
        "a clip that cannot play must leave the chip at 'silent', found %r" % data["__failed"]["origin"])


def test_the_module_carries_no_device_engine_symbol():
    """A second voice must be impossible by construction: name every symbol that would be one."""
    src = VOICE.read_text(encoding="utf-8")
    for forbidden in ("speechSynthesis", "SpeechSynthesisUtterance", "pickVoice", "speakDevice"):
        assert forbidden not in src, f"the module still carries a device engine ({forbidden!r})"
