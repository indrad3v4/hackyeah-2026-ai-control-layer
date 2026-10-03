# This is a mirror, not the source of truth

`node/` is a verbatim copy of **https://github.com/indrad3v4/warrnt** at the commit pinned in
`scripts/sync-node.sh`. Why it is here: a reviewer should be able to read this submission — the
site, the documents **and the running code with its tests** — without leaving the package. The
mirror exists so the Python is in this repository; it does not move the source of truth.

- **Canonical repository:** https://github.com/indrad3v4/warrnt — every change lands there, each
  through a pull request that the Prelint review app comments on (`AGENTS.md` there carries the
  frozen decisions D1–D13).
- **Do not edit `node/` here.** An edit here is invisible to the node's own tests and will be
  overwritten by the next sync.
- **Regenerate / verify:** `bash scripts/sync-node.sh` · `bash scripts/sync-node.sh --check`.

Contents: the whole node (`warrnt/` — kernel, registry, plugins, policy, receipts, anchor),
`tests/` (86 tests), `scripts/` (the four proof runs) and its own README.
