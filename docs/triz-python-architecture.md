# Why this architecture — the microkernel, checked against its canon

> **Provenance and scope.** The architecture record for the action-class work, produced with TRIZ
> as the lens. It is a **design record, not runtime**: nothing here is imported by the node. It
> answers the one question a jury asks — *why this architecture type and not another* — with the
> contradictions the design had to resolve, not with taste.
>
> Ties to the frozen decisions: D3 (one catalog, no hardcoding), D5 (decide before execution),
> D10 (the test suite is a deliverable).
>
> Every number below was **measured** against the mirrored node (`node/`, synchronised from
> `indrad3v4/warrnt`) at the commit the mirror names. Re-measure with
> [Verify it yourself](#verify-it-yourself); do not trust the digits.

## The canon check

Source: [Microkernel Architecture Pattern, GeeksforGeeks, 23.07.2025](https://www.geeksforgeeks.org/system-design/microkernel-architecture-pattern-system-design/).
The pattern keeps a **minimal core** that only coordinates, with every additional capability as a
module outside it, reached through a well-defined interface, so features are *added without
modifying the core*. Six components it names, and what we have:

| Canon component | What we have | Verdict |
|---|---|---|
| Minimal core, coordination only | `proxy.py` (~250 lines, ~11% of the package): recognise → ask the registry → execute → receipt. No rules inside it — they live in `seed.py` / `policy.py` / `actions.py` | holds |
| Services as separate modules outside the core | 17 modules: `policy`, `actions`, `actors`, `seed`, `registry`, `anchor`, `upstream`, `warrants`, `canonical`, `api`, `cli`, `demo`, `models`, `gates`, `breakglass`, `config`, plus `plugins/` | holds |
| A well-defined core/module boundary | Outer: HTTP + JSON-RPC (MCP). Inner: the `Gate` contract — name · order · `check(ctx) -> (decision, reason, detail) | None` — published as a type in `gates.py` | holds |
| IPC / system calls | Transport is HTTP + JSON-RPC; `upstream.py` is the adapter to MCP, and the core does not know what is on the other side | holds (as port/adapter) |
| Service management: load / unload / replace **without touching the core** | `gates.load()` discovers `warrnt/plugins/` with `pkgutil`; each module registers itself; `register(..., replace=True)` swaps and `unregister(name)` removes at runtime; the core only asks the registry | holds |
| Drivers outside the core | The upstream executor is built by the `build_upstream()` factory; the core knows nothing about it | holds |

**Verdict.** The claim closes — and it is checked, not promised. `proxy.py` contains **zero**
decision calls (`classify(`, `apply_class(`, `engine.evaluate(`, `actors.check(`): the grep in
[Verify it yourself](#verify-it-yourself) returns 0. The four gates live in four separate files
under `warrnt/plugins/`, discovery is `pkgutil`, and **"add a gate" is "add a file"**. The order is
declared rather than implied:

```
act_class (10) → actor_scope (20) → break_glass (25) → order_policy (30)
```

**What it cost, and what proves it:**

1. **`gates.py`** — the registry (name · order · `check`), with `load()` / `register()` /
   `unregister()` / `ordered()`. A pipeline that runs off the end **raises `RuntimeError`**: a
   silent default is forbidden, because a control layer that does nothing without saying so is
   worse than one that stops.
2. **`tests/test_gates.py`** (6 tests) — gate order; "the core contains no decision calls"; **a
   gate dropped into the package is picked up and stops the pipeline with the core unchanged**;
   replace and unregister at runtime; a duplicate name refused without `replace=True`.
3. **`tests/test_breakglass.py`** (19 tests) — the emergency path proves the boundary: the
   `break_glass` gate only *looks up* a live grant and puts it in `ctx.extra`; the decision stays
   with `order_policy`. A grant can never make anything happen by itself.
4. **Behaviour did not change under the refactor** — the suite green, `console-check` 35/35,
   `upstream` 18/18, `security` 29/29, `verify_live` 20/20.

**The cost the canon names, which we accept:** communication overhead, harder debugging and testing
of the cross-module seams, and integration cost for each new module. Our counter-argument is that
the boundary is thin — one facade (`MCPProxy`) plus adapters — so the suite still runs **without a
server**.

## Why these types — the contradictions that pick them

- **Policy inside a framework** (a DI container, pydantic models as the domain) is convenient,
  **but** the core can no longer be tested without a running server and the proof starts depending
  on someone else's middleware → **move the decision out**; one thin line stays in the call path.
- **One element must be both inside and outside.** A gate **must** sit *inside* the call path to
  stop execution before it happens, **and** *outside* every framework to be provable → a **pure
  decision function** plus a thin adapter in the path.
- **One process is cheap and auditable, but does not scale to N teams**; microservices scale, but
  the hash chain breaks between processes and "one truth" disappears → one decision core, each
  upstream behind its own adapter.

## What this rules out — cost without function

An ORM or database under the receipts (mutable tables make the record rewriteable), a DI container,
a shared "security manager" singleton, splitting the gates across deployments, deep policy
inheritance instead of a table, and async everywhere.

## Verify it yourself

```bash
cd node
# 1. the core decides nothing (expect: 0)
grep -cE "classify\(|apply_class\(|engine\.evaluate\(|actors\.check\(" warrnt/proxy.py

# 2. the registry, the gates and their order
grep -n "register(Gate(" warrnt/plugins/*.py
python3 -c "from warrnt import gates; gates.load(); print([(g.name, g.order) for g in gates.ordered()])"

# 3. the suite and the live checks
python3 -m pytest -q --collect-only | tail -1
make console-check && make upstream-check
```

## Dependencies

- **External** — the canon article linked above (a live URL; it blocks bare `curl`, so open it in a
  browser). Kukalev, *ТРИЗ*, 2014 supplies the method, not the vocabulary: **the numbered
  40-principles list is not in that book** — the author removed it from his edition — so no
  principle number is cited here. Nothing in this document rests on a source we cannot point at.
- **Internal** — the mirrored node (`node/`) and its tests under `node/tests/`. The counts quoted
  are that node's, measured at the mirrored commit.
- **Runtime** — **none.** Nothing imports this file; it is documentation. Its only real dependency
  is that its claims stay true, which is why the verification block exists and why
  `scripts/doc_qa.py` in the submission repo checks this document's vocabulary and counts
  automatically.

## The design decision this record produced

Break-glass, the emergency route, **must not be a flag inside `PolicyEngine`** — a flag couples the
exception to the rule table it is meant to bypass. The right type is a **short-lived permit
object**: a separate entity with a TTL, signed and receipted, that *this* call passes through and
that closes itself. That is what shipped — `warrnt/breakglass.py` with the `break_glass` gate and
`tests/test_breakglass.py`. The record's reasoning and the code agree.
