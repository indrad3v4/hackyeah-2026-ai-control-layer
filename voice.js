/* voice.js — TENET's guide, ONE source of truth for every surface.
 *
 * The onboarding defined the pattern; this module carries it to the whole app. Contract:
 *
 *  1. The voice is a RENDERING of a record, never a source of authority (D5/D11/D12).
 *  2. Provenance is reported, never assumed: the chip says what ACTUALLY played
 *     (locked-clip | muted | silent), so it can never claim a studio voice while
 *     something else is speaking.
 *  3. LINES is keyed to the REAL journey state, never a script read aloud.
 *  4. `notEvaluated` exists: a transport failure (405 / 5xx / dead network) leaves no
 *     kernel record, so the character must say that it could not reach its own decision
 *     path — never that something was authorized or refused. Nothing came back is not a
 *     verdict.
 *  5. No beat may depend on an audio event: a failed voice never stalls the surface.
 *  6. ONE voice, structurally. Every line — beat and narration — is a locked studio clip
 *     (Grok Ara, the film's character). There is no device synthesiser anywhere in this
 *     module: if a clip is missing or cannot play the character is SILENT, and the chip
 *     says `silent`. A second voice is impossible by construction, not by luck.
 */
(function () {
  // Beat clips: one per journey beat (the studio voice). Narration clips: one per LINES
  // key, `audio/line-<key>.mp3`. Both are host-relative so the Pages subpath resolves too.
  const CLIPS = {
    gate: "audio/gate.mp3", SAY: "audio/say.mp3", SEE: "audio/see.mp3",
    UNDERSTAND: "audio/understand.mp3", DECIDE: "audio/decide.mp3",
    WITNESS: "audio/witness.mp3", PROVE: "audio/prove.mp3", WIN: "audio/win.mp3",
    // The 15 narration clips, keyed exactly like LINES below.
    listen: "audio/line-listen.mp3", heard: "audio/line-heard.mp3",
    proposes: "audio/line-proposes.mp3", check: "audio/line-check.mp3",
    allow: "audio/line-allow.mp3", deny: "audio/line-deny.mp3",
    denyAfter: "audio/line-denyAfter.mp3", wait: "audio/line-wait.mp3",
    waitDecision: "audio/line-waitDecision.mp3", crossed: "audio/line-crossed.mp3",
    nothingCrossed: "audio/line-nothingCrossed.mp3", canCross: "audio/line-canCross.mp3",
    proof: "audio/line-proof.mp3", win: "audio/line-win.mp3",
    notEvaluated: "audio/line-notEvaluated.mp3"
  };
  // The character's own lines, keyed to the real state.
  const LINES = {
    listen: "Tell me what you want your AI to do.",
    heard: "I heard you.",
    proposes: "Your AI wants to do this.",
    check: "Let me check.",
    allow: "Allowed.",
    deny: "No.",
    denyAfter: "Nothing left TENET.",
    wait: "I'm waiting for you.",
    waitDecision: "Your decision.",
    crossed: "It crossed.",
    nothingCrossed: "Nothing crossed.",
    canCross: "Now it can cross.",
    proof: "Here is what happened.",
    win: "You stayed in control.",
    // The state the loop was missing: no record exists, so no verdict may be spoken.
    notEvaluated: "I could not reach my own decision path. Nothing was decided — and nothing was authorized, because nothing was asked."
  };
  // The gate clip and the beat clips use upper-case map keys that mirror `say()`'s beat keys;
  // `clipFor()` resolves both the beat keys and the LINES keys against this one map.

  let soundOn = true, greeting = false, pendingLine = null, lastLine = null,
      lastClipKey = null, voiceAudio = null, lastOrigin = "silent", els = {};

  function $(id) { return typeof document !== "undefined" ? document.getElementById(id) : null; }
  function label() {
    if (!soundOn) return "muted";
    return lastOrigin === "locked-clip" ? "TENET · studio voice"
      : lastOrigin === "muted" ? "muted" : "silent";
  }
  function paintChip() {
    if (els.chip) els.chip.textContent = "sound — " + label();
    if (els.names) els.names.textContent = "";
  }
  function stop() { if (voiceAudio) { try { voiceAudio.pause(); } catch (e) {} voiceAudio = null; } }
  // The ONE player. There is no second engine to fall back to: a clip that is missing or
  // cannot play leaves the character SILENT and the chip says so (`silent`), never
  // `locked-clip` and never a device synthesiser.
  function playClip(clip, onDone) {
    // A new line invalidates the previous proof: until THIS clip is proven playing (onplaying),
    // the chip must not claim the studio voice. So the origin drops to silent up front.
    lastOrigin = "silent"; paintChip();
    if (!clip) { if (onDone) onDone(); return; }
    try {
      stop();
      const a = new Audio(clip); voiceAudio = a;
      // "locked-clip" is claimed only once the clip is actually PLAYING.
      a.onplaying = () => { lastOrigin = "locked-clip"; paintChip(); };
      a.onended = () => { voiceAudio = null; if (els.loading) els.loading.style.display = "none"; if (onDone) onDone(); };
      // A clip that cannot play is not replaced by a second voice: the character stays silent.
      a.onerror = () => { voiceAudio = null; lastOrigin = "silent"; paintChip();
        if (els.loading) els.loading.style.display = "none"; if (onDone) onDone(); };
      const pr = a.play();
      if (pr && pr.catch) pr.catch(() => { voiceAudio = null; lastOrigin = "silent"; paintChip();
        if (els.loading) els.loading.style.display = "none"; if (onDone) onDone(); });
    } catch (e) { voiceAudio = null; lastOrigin = "silent"; paintChip(); if (onDone) onDone(); }
  }
  function speak() {
    if (els.loading) els.loading.style.display = "";
    if (!soundOn) { lastOrigin = "muted"; paintChip(); if (els.loading) els.loading.style.display = "none"; return; }
    if (greeting) { pendingLine = lastClipKey; return; }
    playClip(lastClipKey);
  }
  const api = {
    LINES, CLIPS,
    init(o) {
      o = o || {};
      els = { chip: $(o.chip), names: $(o.voiceName), loading: $(o.loading) };
      soundOn = o.soundOn !== false;
      paintChip();
      return this;
    },
    // The clip for a line: the beat clip for a beat key, the line clip for a LINES key, and
    // NO clip (→ silence) for anything else. One lookup, one voice, no second engine.
    clipFor(state) {
      const k = (state || "").trim();
      if (CLIPS[k]) return CLIPS[k];
      const upper = k.toUpperCase();
      return CLIPS[upper] || (LINES[k] ? CLIPS[k] : null) || null;
    },
    say(state, overrideText) {
      const line = overrideText || LINES[state];
      const clip = api.clipFor(state);
      if (!line && !clip) return false;
      lastLine = state;
      lastClipKey = clip;
      speak();
      return true;
    },
    // The gate: the browser needs one tap before any voice can play. Both buttons dismiss it;
    // only the sound button arms the voice. The gate plays the studio gate clip; if it cannot
    // play, the character is silent — there is no second engine to fall back to.
    gate(onStart) {
      const g = $("voiceGate"); if (!g) return;
      const arm = (on) => {
        g.style.display = "none";
        if (on) { greeting = true; soundOn = true; paintChip();
          playClip(CLIPS.gate, () => { greeting = false;
            if (pendingLine) { const c = pendingLine; pendingLine = null; lastClipKey = c; speak(); } });
        } else { soundOn = false; lastOrigin = "silent"; paintChip(); }
        if (typeof onStart === "function") onStart(on);
      };
      const b1 = $("gateSound"), b2 = $("gateSilent");
      if (b1) b1.onclick = () => arm(true);
      if (b2) b2.onclick = () => arm(false);
    },
    toggle() { soundOn = !soundOn; if (!soundOn) stop(); paintChip(); return soundOn; },
    replay() { if (lastLine) api.say(lastLine); },
    isOn() { return soundOn; },
    lastOrigin() { return lastOrigin; }
  };
  if (typeof window !== "undefined") window.TENETVoice = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
