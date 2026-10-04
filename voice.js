/* voice.js — TENET's guide, ONE source of truth for every surface.
 *
 * The onboarding defined the pattern; this module carries it to the whole app. Contract:
 *
 *  1. The voice is a RENDERING of a record, never a source of authority (D5/D11/D12).
 *  2. Provenance is reported, never assumed: the chip says what ACTUALLY played
 *     (locked-clip | device | muted | silent), so it can never claim a studio voice
 *     while the device is speaking.
 *  3. LINES is keyed to the REAL journey state, never a script read aloud.
 *  4. `notEvaluated` exists: a transport failure (405 / 5xx / dead network) leaves no
 *     kernel record, so the character must say that it could not reach its own decision
 *     path — never that something was authorized or refused. Nothing came back is not a
 *     verdict.
 *  5. No beat may depend on an audio event: a failed voice never stalls the surface.
 */
(function () {
  const CLIPS = {
    gate: "audio/gate.mp3", SAY: "audio/say.mp3", SEE: "audio/see.mp3",
    UNDERSTAND: "audio/understand.mp3", DECIDE: "audio/decide.mp3",
    WITNESS: "audio/witness.mp3", PROVE: "audio/prove.mp3", WIN: "audio/win.mp3"
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
  // Journey beats: the clip that belongs to each beat key (the studio voice).
  const BEAT_CLIP = { SAY: "SAY", SEE: "SEE", UNDERSTAND: "UNDERSTAND", DECIDE: "DECIDE", WITNESS: "WITNESS", PROVE: "PROVE", WIN: "WIN" };

  let soundOn = true, greeting = false, pendingLine = null, lastLine = null,
      voiceAudio = null, lastOrigin = "silent", els = {};

  function $(id) { return typeof document !== "undefined" ? document.getElementById(id) : null; }
  function label() {
    if (!soundOn) return "muted";
    return lastOrigin === "locked-clip" ? "TENET · studio voice"
      : lastOrigin === "device" ? "device voice — no studio clip for this line"
      : lastOrigin === "muted" ? "muted" : "silent";
  }
  function paintChip() {
    if (els.chip) els.chip.textContent = "sound — " + label();
    if (els.names) { const v = pickVoice(); els.names.textContent = v ? v.name : ""; }
  }
  function pickVoice() {
    try {
      if (!("speechSynthesis" in window)) return null;
      const vs = speechSynthesis.getVoices(); if (!vs.length) return null;
      const pref = ["Jenny", "Sonia", "Michelle", "Clara", "Aria", "Emma", "Samantha", "Ava", "Serena", "Zira", "Google US English", "Victoria", "Karen", "Moira"];
      for (const p of pref) { const f = vs.find(v => (v.name || "").includes(p)); if (f) return f; }
      const f2 = vs.find(v => (v.lang || "").toLowerCase().startsWith("en")); return f2 || vs[0];
    } catch (e) { return null; }
  }
  function speakDevice(txt) {
    if (els.loading) els.loading.style.display = "none";
    if (!("speechSynthesis" in window)) { lastOrigin = "silent"; paintChip(); return; }
    const v = pickVoice(); if (!v) { lastOrigin = "silent"; paintChip(); return; }
    try {
      const u = new SpeechSynthesisUtterance(txt); u.voice = v; u.rate = 0.94; u.pitch = 0.92;
      u.onstart = () => { lastOrigin = "device"; paintChip(); };
      u.onend = u.onerror = () => { if (els.loading) els.loading.style.display = "none"; };
      speechSynthesis.cancel(); speechSynthesis.speak(u);
    } catch (e) { lastOrigin = "silent"; paintChip(); }
  }
  function stop() { if (voiceAudio) { try { voiceAudio.pause(); } catch (e) {} voiceAudio = null; } }
  function speak(txt) {
    if (els.loading) els.loading.style.display = "";
    if (!soundOn) { lastOrigin = "muted"; paintChip(); if (els.loading) els.loading.style.display = "none"; return; }
    if (greeting) { pendingLine = txt; return; }
    const clip = els.clipKey ? CLIPS[els.clipKey] : null;
    if (clip) {
      try {
        stop();
        const a = new Audio(clip); voiceAudio = a;
        // "locked-clip" is claimed only once the clip is actually PLAYING.
        a.onplaying = () => { lastOrigin = "locked-clip"; paintChip(); };
        a.onended = () => { voiceAudio = null; if (els.loading) els.loading.style.display = "none"; };
        // A clip that cannot play falls back — and the chip says so, never "studio voice".
        a.onerror = () => { voiceAudio = null; speakDevice(txt); };
        const pr = a.play();
        if (pr && pr.catch) pr.catch(() => { voiceAudio = null; speakDevice(txt); });
        return;
      } catch (e) { voiceAudio = null; }
    }
    speakDevice(txt);
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
    say(state, overrideText) {
      const line = overrideText || LINES[state];
      if (!line) return false;
      lastLine = state;
      els.clipKey = BEAT_CLIP[(state || "").toUpperCase()] || null;
      speak(line);
      return true;
    },
    // The gate: the browser needs one tap before any voice can play. Both buttons dismiss it;
    // only the sound button arms the voice.
    gate(onStart) {
      const g = $("voiceGate"); if (!g) return;
      const onArmFail = () => { lastOrigin = soundOn ? "device" : "muted"; paintChip();
        if (pendingLine) { const t = pendingLine; pendingLine = null; speakDevice(t); } };
      const arm = (on) => {
        g.style.display = "none";
        if (on) { greeting = true; soundOn = true; paintChip();
          const a = new Audio(CLIPS.gate); voiceAudio = a;
          a.onended = () => { voiceAudio = null; greeting = false; if (pendingLine) { const t = pendingLine; pendingLine = null; speak(t); } };
          a.onerror = () => { voiceAudio = null; greeting = false; onArmFail(); };
          a.onplaying = () => { lastOrigin = "locked-clip"; paintChip(); };
          const pr = a.play(); if (pr && pr.catch) pr.catch(() => { voiceAudio = null; greeting = false; onArmFail(); });
        } else { soundOn = false; lastOrigin = "silent"; paintChip(); }
        if (typeof onStart === "function") onStart(on);
      };
      const b1 = $("gateSound"), b2 = $("gateSilent");
      if (b1) b1.onclick = () => arm(true);
      if (b2) b2.onclick = () => arm(false);
    },
    toggle() { soundOn = !soundOn; if (!soundOn) { stop(); try { speechSynthesis.cancel(); } catch (e) {} } paintChip(); return soundOn; },
    replay() { if (lastLine) speak(LINES[lastLine]); },
    isOn() { return soundOn; },
    lastOrigin() { return lastOrigin; },
    pickVoice
  };
  if (typeof window !== "undefined") window.TENETVoice = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
