#!/usr/bin/env python3
"""Deterministic frame renderer for the WARRNT 40 s demo.

Opens record.html in shot mode, then for every frame sets the virtual time
(window.__shot(vt)) and grabs a screenshot. The page state is a pure function
of vt, so the frames never drift the way a live screen capture would.

Run:
  CHROME=/path/to/chromium python render_demo.py [fps] [dur]
"""
import base64, json, os, random, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = os.environ.get("CHROME", "/usr/lib/chromium/chromium")
W, H = 1920, 1080
FPS = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 40.0
FRAMES = int(round(FPS * DUR)) + 1          # inclusive of t=0 .. t=DUR
OUTDIR = os.path.join(HERE, "frames")
os.makedirs(OUTDIR, exist_ok=True)
URL = "file://" + os.path.join(HERE, "record.html") + "?source=shot"

port = random.randint(9300, 9900)
prof = f"/tmp/cdp-warrnt-{port}"
proc = subprocess.Popen([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                         "--disable-dev-shm-usage", "--hide-scrollbars", "--no-first-run",
                         "--disable-extensions", "--force-device-scale-factor=1",
                         "--force-color-profile=srgb", "--font-render-hinting=none",
                         f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
                         f"--window-size={W},{H}", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    from websockets.sync.client import connect
    for _ in range(40):
        try:
            json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3)); break
        except Exception:
            time.sleep(0.4)
    else:
        raise SystemExit("chromium did not start")
    t = json.load(urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT"), timeout=15))
    if isinstance(t, list):
        t = t[0]
    sock = connect(t["webSocketDebuggerUrl"], max_size=200 * 1024 * 1024)
    _id = [0]

    def cmd(method, **params):
        _id[0] += 1
        sock.send(json.dumps({"id": _id[0], "method": method, "params": params}))
        while True:
            msg = json.loads(sock.recv(timeout=120))
            if msg.get("id") == _id[0]:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"])[:200])
                return msg.get("result", {})

    for m in ("Page.enable", "Runtime.enable"):
        cmd(m)
    cmd("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
    cmd("Page.navigate", url=URL)
    t0 = time.time()
    while time.time() - t0 < 25:
        try:
            if cmd("Runtime.evaluate", expression="document.readyState", returnByValue=True)["result"]["value"] == "complete":
                break
        except Exception:
            pass
        time.sleep(0.3)
    time.sleep(1.0)
    has = cmd("Runtime.evaluate", expression="typeof window.__shot", returnByValue=True)["result"]["value"]
    if has != "function":
        raise SystemExit("record.html did not expose __shot (got %r)" % has)
    print(f"chromium up · fps={FPS} dur={DUR}s frames={FRAMES}", flush=True)

    def shot(vt):
        return cmd("Runtime.evaluate", expression=f"window.__shot({vt:.3f})", returnByValue=True)["result"]["value"]

    def png(quality=92):
        return base64.b64decode(cmd("Page.captureScreenshot", format="jpeg", quality=quality)["data"])

    # sanity probe at key beats
    for vt in (1.5, 5.0, 12.0, 18.0, 22.0, 30.0, 38.0):
        note = shot(vt)
        probe = cmd("Runtime.evaluate", returnByValue=True, expression=(
            "JSON.stringify({cap:document.getElementById('capB').innerText.slice(0,90),"
            "badge:document.getElementById('modeBadge').innerText,"
            "receipts:document.getElementById('rCount').innerText,"
            "stop:document.getElementById('mStop').innerText,"
            "rev:document.getElementById('mRev').innerText,"
            "agHalt:document.getElementById('agHalt').innerText,"
            "top:document.querySelector('.rec .what')?document.querySelector('.rec .what').innerText.slice(0,80):'',"
            "card:getComputedStyle(document.getElementById('card')).display})"))["result"]["value"]
        print(f"probe vt={vt:<5} -> {note} | {probe}", flush=True)

    t0 = time.time()
    for i in range(FRAMES):
        vt = i / FPS
        shot(vt)
        data = png()
        with open(os.path.join(OUTDIR, f"f_{i:04d}.jpg"), "wb") as fh:
            fh.write(data)
        if i % 25 == 0:
            print(f"  frame {i:4d}/{FRAMES}  ({time.time()-t0:.0f}s)", flush=True)
    sock.close()
    print(f"done: {FRAMES} frames in {time.time()-t0:.0f}s -> {OUTDIR}", flush=True)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    subprocess.run(["rm", "-rf", prof], capture_output=True)
