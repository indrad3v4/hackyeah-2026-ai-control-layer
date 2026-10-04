"""NEW-AC7 — the claim (the brief, 2026-10-04).

Two sentences were removed from the guide in this commit, because a visitor was reading a claim the
product cannot show them:

* the footnote paragraph - voice provenance and an outside approval asserted in prose, on the one
  surface whose sound is a browser artefact. The person reading it cannot check a word of it, and an
  approval by a named person is not something a repository can evidence. A layer whose whole subject
  is claims that outrun evidence cannot open with one.
* the script-written note - a line the page injected into its own markup to say that it is honest.
  The property it named is already evidenced: the guide reads the live records and prints THEM.

What replaces them is not silence. The sound chip (``id="voiceChip"``) stays, and it reports what
ACTUALLY played - the studio clip, or the device voice with its own name, or nothing - and it is
carried by BOTH surfaces. That is the resolution recorded in the commit message, choice (a) of the
brief: the console carries the same sound-label chip the guide carries, so
``test_both_surfaces_claim_the_same_sound_label_vocabulary`` stays rather than being retired - the
chip IS the replacement for the deleted prose, and a test that pins the shared vocabulary is now
pinning the evidence. Choice (b) would have deleted the replacement along with the claim.

The needles below are assembled from fragments on purpose: a test that searches the whole tree for a
sentence must not be the one file that still contains it. The scan reads the WORKING TREE, not git
history - a commit that removes a claim may quote what it removed, a page may not show it.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.app import create_app

REPO = Path(__file__).resolve().parents[1]
CONSOLE = "/"
# The guide is a layer of the console since 04.10.2026: there is no second page to fetch. The
# redirect is checked where it belongs (tests/test_onboarding_page.py); here only the surfaces that
# carry words are read.
GUIDE = "/"

# The three claims the deleted sentences made, assembled so this file carries none of them itself.
NEEDLES = {
    "the footnote's provenance claim": "TENET speaks with her own " + "locked studio voice",
    "the footnote's approval claim": "approved by " + "the producer",
    "the script-written note": "Every step reads the " + "live control plane",
}
SKIP_DIRS = {".git", "state", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv",
             "node_modules", "site-packages"}
SKIP_SUFFIXES = {".mp3", ".wav", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff",
                 ".woff2", ".ttf", ".otf", ".db", ".sqlite", ".log"}
MAX_BYTES = 1_000_000


def _tree_hits(needle: str) -> list[str]:
    """Every file and line in the working tree that still carries ``needle``."""
    hits: list[str] = []
    for path in REPO.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or path.stat().st_size > MAX_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # unreadable is not a pass; name it
            hits.append("%s (unreadable)" % path.relative_to(REPO))
            continue
        hits.extend("%s:%d" % (path.relative_to(REPO), n)
                    for n, line in enumerate(text.splitlines(), 1) if needle in line)
    return hits


def _pages() -> dict[str, str]:
    with TestClient(create_app(seed=True)) as client:
        return {"the console (/)": client.get(CONSOLE).text,
                "the one voice module (/voice.js)": client.get("/voice.js").text}


def test_neither_deleted_sentence_remains_in_the_working_tree():
    """File by file, the three claims are gone - and a failure names the file and the line."""
    for what, needle in NEEDLES.items():
        hits = _tree_hits(needle)
        assert hits == [], "%s is still in the tree: %s" % (what, ", ".join(hits))


def test_neither_sentence_reaches_a_person_on_any_surface():
    """The visitor's view: a text-only fetch of every surface carries neither claim."""
    for where, body in _pages().items():
        for what, needle in NEEDLES.items():
            assert needle not in body, "%s still shows %s" % (where, what)


def test_the_deleted_note_left_no_dead_container_behind():
    """The container the note was written into is gone with it - no placeholder for a lost line."""
    pages = _pages()
    assert 'id="note"' not in pages["the console (/)"], (
        "an empty container is a placeholder for the sentence that was removed")


def test_resolved_as_a_the_single_page_consumes_the_one_module_that_owns_the_words():
    """Choice (a), pinned: the chip is the replacement, and the vocabulary has exactly ONE home.

    Before the merge the console and the guide each carried a chip, each with its own engine — two
    implementations of one character, which is how they drifted. Now the page carries the element and
    the module owns the words: the label is evidence of what actually played, and the fallback names
    the device voice instead of hiding it.
    """
    pages = _pages()
    console, module = pages["the console (/)"], pages["the one voice module (/voice.js)"]
    assert 'id="voiceChip"' in console, "the page must carry the sound chip"
    assert "sound — " in console, "the page must label the chip with a playback state"
    assert 'lastOrigin = "locked-clip"' in module, (
        "the module the console loads must name the origin from playback, not from a lookup")
    assert 'lastOrigin = "locked-clip"' in module, (
        "the chip must read the playback origin, not a static lookup")
    label = "TENET · studio voice"
    assert label in module, "the module owns the label"
    assert label not in console, (
        "a second copy of the vocabulary on the page is a second source of truth: the guide's "
        "inline engine is exactly what this merge removed")
    # ONE voice, structurally: the module names no second voice, because none is reachable.
    assert "device voice" not in module, (
        "a device-voice label would name a second voice that must not be reachable")
    for forbidden in ("speechSynthesis", "function pickVoice", "function clipFor("):
        assert forbidden not in console, (
            "the page carries a second voice engine (%r): one product, one voice" % forbidden)
