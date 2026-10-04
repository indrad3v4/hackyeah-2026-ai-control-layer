# NEW-AC8 — the report

Brief: `TENET-ENGINEER-brief-NEW-AC-2026-10-04.txt`, section 2, NEW-AC8 —
«pytest count, the commit sha, and the 4 curl checks of NEW-AC6 — verbatim output, no summary».

Branch: `ac-surface-kernel`. Raw logs: `docs/evidence/new-ac8-pytest.out`,
`docs/evidence/new-ac8-door-checks-branch-hosts.out`,
`docs/evidence/new-ac8-door-checks-public-hosts.out`.

## 1 · the commits (verbatim)

```
$ git --no-pager log --oneline origin/main..ac-surface-kernel
306ae8d NEW-AC7: the claim — two sentences a visitor could not check, and the chip that replaces them
180a87c NEW-AC6: the door — one plain link each way between the two rooms
50b3745 NEW-AC5: the fourth state reaches the human (expired, with its clock)
3404245 NEW-AC4: the observer's room — the record, read-only
e25331e NEW-AC3: read-only view of the stream, judged (class + decider line per row)
780dfb4 test(console): lock the agent register's five keys (NEW-AC2)
9d31371 feat(console): the two gates, shown apart (NEW-AC1)

$ git rev-parse HEAD
306ae8d008694a8b62d5c3a9b0762659ea15a080

$ git rev-parse origin/main
c3704f8317fd8ce21edfd6c41a2863b4915291f7

$ git status -sb
## ac-surface-kernel...origin/main [ahead 7]
$ git rev-parse --quiet --verify origin/ac-surface-kernel || echo 'no remote branch ac-surface-kernel'
no remote branch ac-surface-kernel
```

Seven commits, local only: the branch tracks `origin/main` and is seven ahead of it, and no
`origin/ac-surface-kernel` exists on the remote. (Measured before this report's own commit, which
makes the count eight.) NEW-AC8 is this file's own commit — the branch head after it, which cannot
appear inside it.

## 2 · pytest (verbatim)

```
$ python -m pytest -q -s
# ... 111 lines, all of them in docs/evidence/new-ac8-pytest.out ...
[tenet] WARRNT_ADMIN_TOKEN is unset - generated for this process only:
[tenet]   <process-local dev token, masked>
[tenet] mutating routes need the header x-warrnt-admin: <token>
......
337 passed in 36.80s
```

337 is the whole suite on this branch, measured in one run above. The stored log is the run
verbatim, with the 33 per-process development admin tokens the app prints when
`WARRNT_ADMIN_TOKEN` is unset replaced by `<process-local dev token, masked>` — every line of
measurement, no credential of any kind in the evidence.

The same command against `origin/main`, in a clean worktree of it:

```
$ cd /tmp/ac8-main   # git worktree add /tmp/ac8-main origin/main
$ python -m pytest -q
...............................                                          [100%]
319 passed in 34.22s
```

## 3 · the 4 curl checks of NEW-AC6 (verbatim)

The brief's check, character for character: `curl -s <url> | grep -c 'href="'`, on both pages of both
hosts. Run twice — first against the two public hosts as the brief asks, then against two local hosts
that serve this branch (the control plane under `uvicorn control_plane.app:app`, the same object the
`Procfile` runs; and a static host that resolves extensionless paths the way Pages does).

### 3a · the two public hosts

```
# the two PUBLIC hosts, measured 2026-10-04
$ curl -s https://hackyeah-2026-ai-control-layer-production.up.railway.app/ | grep -c 'href="'
0
$ curl -s https://hackyeah-2026-ai-control-layer-production.up.railway.app/ | grep -o 'href="[^"]*"' | sort -u | tr '\n' ' '


$ curl -s https://hackyeah-2026-ai-control-layer-production.up.railway.app/onboarding | grep -c 'href="'
0
$ curl -s https://hackyeah-2026-ai-control-layer-production.up.railway.app/onboarding | grep -o 'href="[^"]*"' | sort -u | tr '\n' ' '


$ curl -s https://indrad3v4.github.io/hackyeah-2026-ai-control-layer/ | grep -c 'href="'
0
$ curl -s https://indrad3v4.github.io/hackyeah-2026-ai-control-layer/ | grep -o 'href="[^"]*"' | sort -u | tr '\n' ' '


$ curl -s https://indrad3v4.github.io/hackyeah-2026-ai-control-layer/onboarding | grep -c 'href="'
0
$ curl -s https://indrad3v4.github.io/hackyeah-2026-ai-control-layer/onboarding | grep -o 'href="[^"]*"' | sort -u | tr '\n' ' '

```

The same run, the pages and their sizes:

```
# the two PUBLIC hosts, this run
https://hackyeah-2026-ai-control-layer-production.up.railway.app/ -> HTTP 200 bytes 54031
https://hackyeah-2026-ai-control-layer-production.up.railway.app/onboarding -> HTTP 200 bytes 27598
https://hackyeah-2026-ai-control-layer-production.up.railway.app/observer -> HTTP 404 bytes 22
https://indrad3v4.github.io/hackyeah-2026-ai-control-layer/ -> HTTP 200 bytes 54031
https://indrad3v4.github.io/hackyeah-2026-ai-control-layer/onboarding -> HTTP 200 bytes 27598
https://indrad3v4.github.io/hackyeah-2026-ai-control-layer/observer -> HTTP 404 bytes 9379
```

Read plainly: the public hosts answer with the tree of `origin/main` (`c3704f8`), seven commits
behind this branch — no door (`0` in all four checks) and no observer room (`/observer` is 404 there
and 200 here). Landing the branch on `main` is the step that republishes them, and it was not taken:
no merge, no push and no redeploy was executed from this working copy, so nothing here claims the
public hosts carry the door yet.

### 3b · hosts serving this branch

```
# hosts serving THIS branch (control-plane host = Procfile shape, local uvicorn; static host = Pages-shaped resolver)
$ curl -s http://127.0.0.1:8111/ | grep -c 'href="'
1
$ curl -s http://127.0.0.1:8111/ | grep -o 'href="[^"]*"' | sort -u | tr '\n' ' '
href="/onboarding" 

$ curl -s http://127.0.0.1:8111/onboarding | grep -c 'href="'
1
$ curl -s http://127.0.0.1:8111/onboarding | grep -o 'href="[^"]*"' | sort -u | tr '\n' ' '
href="/" 

$ curl -s http://127.0.0.1:8112/ | grep -c 'href="'
1
$ curl -s http://127.0.0.1:8112/ | grep -o 'href="[^"]*"' | sort -u | tr '\n' ' '
href="/onboarding" 

$ curl -s http://127.0.0.1:8112/onboarding | grep -c 'href="'
1
$ curl -s http://127.0.0.1:8112/onboarding | grep -o 'href="[^"]*"' | sort -u | tr '\n' ' '
href="/" 

```

```
# hosts serving this branch, this run
http://127.0.0.1:8111/ -> HTTP 200 bytes 60368
http://127.0.0.1:8111/onboarding -> HTTP 200 bytes 27479
http://127.0.0.1:8111/observer -> HTTP 200 bytes 6866
http://127.0.0.1:8112/ -> HTTP 200 bytes 60368
http://127.0.0.1:8112/onboarding -> HTTP 200 bytes 27479
http://127.0.0.1:8112/observer -> HTTP 200 bytes 6866

# the same files on disk
$ wc -c index.html onboarding.html observer.html
60368 index.html
27479 onboarding.html
 6866 observer.html
94713 total
```

Four checks, four `1`s, and each page links to the other: `/` carries `href="/onboarding"`,
`/onboarding` carries `href="/"`. Nothing else on either page is a link.

### 3c · the same four checks inside the test run

`tests/test_new_ac6_the_door.py` runs the brief's check itself, against two real HTTP hosts it
starts (the control plane on one port, the Pages-shaped static host on another) and prints each
result. From the full `-s` run above:

```
curl -s http://127.0.0.1:34825/ | grep -c 'href="' -> 1
curl -s http://127.0.0.1:34825/onboarding | grep -c 'href="' -> 1
curl -s http://127.0.0.1:34645/ | grep -c 'href="' -> 1
curl -s http://127.0.0.1:34645/onboarding | grep -c 'href="' -> 1
```

## 4 · what this report does and does not claim (D12)

Runs today, executed in this report: the 337-test suite; the four checks against two hosts serving
this branch; the AC6 test's own four checks; `pytest -q` on `origin/main` in a separate worktree
(319 passed).

Not run: any merge into `main`, any push, any redeploy. The four checks against the public hosts
were run and returned `0` — that is the honest number until this branch lands on `main`. The exact
commands that would land it, for whoever owns that decision, are:

```
$ git push -u origin ac-surface-kernel                  # the branch on the remote
$ git switch main && git merge --ff-only ac-surface-kernel && git push origin main
# Pages republishes from main; the Railway service deploys from main; then re-run the four curl
# checks above against the two public hosts and expect 1, 1, 1, 1
```

To reproduce:

```
$ python -m pytest -q -s                                   # 337 passed
$ TENET_STATE_DIR=/tmp/ac8state python -m uvicorn control_plane.app:app \
      --host 127.0.0.1 --port 8111 --workers 1             # the control-plane host
$ python -m pytest tests/test_new_ac6_the_door.py -q -s    # the four checks, on two real hosts
$ curl -s http://127.0.0.1:8111/ | grep -c 'href="'        # 1
```
