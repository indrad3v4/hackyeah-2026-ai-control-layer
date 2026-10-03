# The demo video — reproducible, not screen-captured

`warrnt-demo-40s.mp4` (in the repository root) is the 40-second demo: 1920×1080, 25 fps,
H.264, no audio. It runs the 3:47 scenario end to end — an agent asks for 12 000 rows of
customer PII, the layer **denies the call before it runs**, the denial is written to the
hash-chained receipt log, and a single `/revoke` halts the agent in 0.8 s.

Nothing here is captured from a live screen. `record.html` is the console (`../index.html`)
with a `?source=shot` mode added: page state is a **pure function of virtual time**, so
`window.__shot(vt)` renders any frame on demand and the take is identical on every machine —
frames cannot drift the way a hand screen-capture does.

## Rebuild it

Needs Chromium and the `websockets` package (`pip install websockets`).

```bash
python render_demo.py 10 40        # 401 JPEG frames -> ./frames
ffmpeg -y -framerate 10 -start_number 0 -i frames/f_%04d.jpg \
  -vf "fps=25,fade=t=in:st=0:d=0.4,fade=t=out:st=39.4:d=0.6,format=yuv420p" \
  -c:v libx264 -preset slow -crf 18 -movflags +faststart -t 40.0 \
  warrnt-demo-40s.mp4
```

`CHROME=/path/to/chromium python render_demo.py` if your Chromium is not at
`/usr/lib/chromium/chromium`.

`narration.txt` holds the voice-over script with its timing marks; the video itself is silent.
