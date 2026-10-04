"""The guided journey lives INSIDE the control room (``/``) — one path, not two.

Why these assertions exist: a first-time person could not say what TENET does from a paragraph
of documentation, and a voice narrating from nowhere is still a dashboard with sound. So the
surface is one real controlled action walked with a character who is a GUIDE, never the authority:
TENET is the ONE character, continuous from the film into the live journey: she explains, the AI
proposes, the kernel decides, the human controls. These tests pin the parts that make that true on
the single path: who does what, the seven beats of the journey, the character's honest reactions to
the REAL verdict, and the absence of childish gamification.

The journey used to be a second page (``/onboarding``) with its own copy of the character's voice
engine — which is how one product ended up speaking with two voices. It is now a layer of the
console over the SAME rail (04.10.2026): ``GET /onboarding`` is a redirect, not a surface.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from pathlib import Path

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]


def _page() -> str:
    """The one surface the journey lives on: the console."""
    with TestClient(create_app(seed=True)) as client:
        r = client.get("/")
    assert r.status_code == 200, "the console (which carries the guide) must be served"
    return r.text


def test_there_is_no_second_path_to_the_guide():
    """One path in the app: /onboarding resolves to the console instead of serving a second page."""
    with TestClient(create_app(seed=True)) as client:
        r = client.get("/onboarding", follow_redirects=False)
    assert r.status_code == 307, "GET /onboarding must redirect, not serve a surface: %s" % r.status_code
    assert r.headers.get("location") == "/", "the redirect must land on the one path: %r" % (
        r.headers.get("location"),)
    assert not (REPO / "onboarding.html").exists(), (
        "a second guide page on disk is a second path — the merge removed the file")


def test_the_journey_is_served():
    body = _page()
    assert "TENET" in body and "the guide" in body


def test_the_character_is_a_guide_and_the_roles_are_visible():
    body = _page()
    assert "TENET · your guide" in body, "the guide is the named character, not a bare voice"
    low = body.lower()
    for role in ("proposes", "decides", "control"):
        assert role in low, f"the page must show who {role}"
    # the character is not the authority: the kernel decides, and the page says so
    for claim in ("Your AI proposes", "the kernel's decision", "holds no authority",
                  "You keep the controls"):
        assert claim in body, (
            "the split must be stated where the visitor reads it, missing: %r" % claim)


def test_there_is_one_character_from_the_film_to_the_journey():
    """One identity across film, journey and proof. A second guide would break the recognition."""
    body = _page()
    assert "Nadia" not in body, "one character: the film's TENET, not a second guide"
    assert "I'm TENET." in body and "Turn on the sound." in body, (
        "the live journey answers the film's last line and ties the character to the idea")
    assert "I'll stay with you while your AI acts" in body, (
        "the character stays with the human through the action, she does not narrate from off-stage")
    assert "I'll stay with you while your AI acts" in body
    assert "🔈 TENET, again" in body, "the guide may always be asked to say it again"
    # NEW-AC7 — the claim: which voice speaks is no longer a sentence about a producer's approval
    # (a person cannot check it, and no repository can evidence it). It is the chip, and the chip
    # reports what ACTUALLY played.
    assert 'id="voiceChip"' in body, "the journey carries the sound chip that reports what played"
    assert '<script src="voice.js"></script>' in body, (
        "the chip is filled by the one module that owns the vocabulary, not a page-local engine")
    for forbidden in ("speechSynthesis", "function pickVoice", "function clipFor("):
        assert forbidden not in body, (
            "a page-local engine is a second voice (%r): one product, one voice" % forbidden)


def test_the_character_speaks_the_state_not_a_script():
    """Every line the character says is keyed to a real journey state (film copy, verbatim)."""
    body = _page()
    for line in ("Tell me what you want your AI to do.", "I heard you.",
                 "This is what your AI wants to do.", "TENET decides — before anything runs.",
"It really happened.", "And here is the receipt.", "You stayed in control."):
        assert line in body, f"missing the character's line: {line}"
    assert "function journeyBeats(" in body, (
        "the line the guide says is derived from the record, not hardcoded per render")
    with TestClient(create_app(seed=True)) as client:
        module = client.get("/voice.js").text
    # One voice: no device synthesiser survives anywhere, so the film's character is the only
    # voice the visitor can hear (the beat clips and the narration clips are both hers).
    for forbidden in ("speechSynthesis", "SpeechSynthesisUtterance", "pickVoice", "speakDevice"):
        assert forbidden not in module, (
            "a device engine is a second voice (%r): one product, one voice" % forbidden)
    assert 'audio/line-listen.mp3' in module, (
        "the character's narration lines are her own clips too")
    assert "V.say(" in body, "the page speaks the state's line through the one voice module"


def test_the_character_lives_in_the_page_and_asks_for_the_sound():
    body = _page()
    assert 'id="voiceGate"' in body and "Turn on the sound." in body, (
        "a browser needs one gesture before audio: the character asks for it")
    assert "I'm TENET." in body, "the character speaks the gate, not a bare button"
    assert 'id="gChar"' in body, "the character is drawn, not only narrated"
    assert "Read instead" in body, "silence must be a choice"


def test_the_journey_has_the_seven_beats():
    body = _page()
    for beat in ("SAY", "SEE", "UNDERSTAND", "DECIDE", "WITNESS", "PROVE", "WIN"):
        assert f'"{beat}"' in body, f"beat {beat} is missing from the journey"
    # the map is built from the beats themselves, so a new beat cannot be forgotten in the
    # markup (the nodes are rendered in JS, not hand-written seven times)
    assert body.count("BEAT_ORDER") >= 2, (
        "the map and the guide read the same beat list: a new beat cannot be forgotten in markup")


def test_the_character_reacts_to_the_real_verdict():
    body = _page()
    for verdict in ("not allowed", "denied", "refused", "waiting for you"):
        assert verdict in body, "the page must show the kernel's real outcome, missing: %r" % verdict
    assert "function journeyBeats(" in body and "function outcomeOf(" in body, (
        "the reaction is derived from the record, not hardcoded")


def test_there_is_no_childish_gamification():
    """Read the VISIBLE text: comments and CSS inside <script>/<style> are not what a person sees."""
    import re as _re
    body = _page()
    seen = _re.sub(r"<(script|style)\b[\s\S]*?</\1>", " ", body)
    seen = _re.sub(r"<[^>]+>", " ", seen)
    for wrong in ("control score", "+25", "XP", "badge", "points"):
        assert wrong not in seen, f"the win is control, not {wrong!r}"


def test_the_reward_is_control_kept():
    body = _page()
    assert "You stayed in control" in body
    assert "You keep the controls." in body and "you stay in control" in body, (
        "the reward is control kept, and the page says so in its own voice")
    assert "your words, your AI's proposal" in body, "the chain must be named"


def test_it_speaks_every_beat_listens_and_never_scripts_the_answer():
    body = _page()
    assert body.count("s:") >= 7, "every beat carries its own spoken line"
    assert "webkitSpeechRecognition" in body or "SpeechRecognition" in body
    assert "I heard:" in body, "the transcription is shown to the human"
    assert "/api/ask" in body and "/api/actions" in body
    assert "TENET's answer is the one that counts" in body, (
        "the page must say whose word is the answer")
    assert "A transport failure is not a verdict" in body, (
        "the human may not outrun the kernel: an unread record is not a verdict")
    assert "e.event_id===selected" in body, (
        "the record named is THIS run's, not the oldest row of a newest-first list")
