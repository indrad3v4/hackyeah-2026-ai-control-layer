# The architecture, as a microkernel

The brief asks for exactly one thing here, in §3.1(b): *"You should provide a simple
diagram presenting the architecture of your solution."* This directory is that diagram,
plus the three that keep it honest — and the plugin map that says which parts exist today
and which are slots.

Every file is source: the `.puml` renders the `.png` next to it with one `curl` (see
[Re-rendering](#re-rendering)), so a reader can change the picture instead of trusting it.

## The four diagrams

| File | What it shows |
|---|---|
| `kernel-components.png` | Where the check sits, and the kernel/plugin split: adapters → kernel → control plugins → catalog, receipt store, upstream. |
| `kernel-classes.png` | The Python model: `ActionRequest`, `Verdict`, `Decision`, the enums (`Effect`, `Outcome`, `ActionClass`, `Decider`), and the `Control` port every plugin realises. |
| `pipeline-sequence.png` | One destructive tool call end to end: classified, refused by a non-delegable constraint, receipts written, upstream never reached. |
| `decision-ladder.png` | The decision ladder — the raise-only rule, and which phase can refuse at all. |

## The shape: a kernel with no control logic

The layer is split so that **adding a control family never edits the kernel**.

- **Kernel** — `pipeline executor` (fixed phase chain, per-step timeout, fail-closed),
  `plugin registry` (load · order · enable · hot reload from the catalog),
  `decision algebra` (combine verdicts, apply the class floor), `receipt chain`
  (hash chain + signed anchor). Four parts, none of which knows what PII is, what
  destructive means, or which model is local.
- **Adapters** — MCP edge, OpenAI-compatible HTTP, in-process SDK. Swappable, decide nothing.
  A check that must hold for *any* agent, including one whose credentials the model already
  holds, cannot live in the agent's process; that is why the edge is a separate component.
- **Control plugins** — one file per control family. Each implements one port, reads its
  settings from the single catalog, and returns a `Verdict`, never a decision.

**The microkernel test:** delete every plugin and the program is still coherent — it starts,
it has a chain, it refuses everything (fail-closed). That is the property that makes the
six unbuilt controls in the table below *additions* rather than a rewrite.

## The phase chain

```
preflight → classify → constrain → inspect → judge → decide → emit
```

`preflight` (identity, actor class, warrant signature + TTL) and `classify` (what kind of act
is this) run before anything expensive. `constrain` holds the non-delegable rules — the flat
forbid on destructive acts and the budgets. `inspect` is the deterministic half of the hybrid
(PII, secrets, injection markers, external attack signatures). `judge` is the semantic half,
a locally served model. `decide` is the algebra; `emit` is the receipt.

Deterministic before semantic is the fixed order of rule D4, and it is what the plugin
ordering encodes: a cheap filter is never paid for with a model call.

## The four invariants the kernel owns — not the plugins

1. **Forbid overrides permit.** `DENY > HOLD > REDACT > ALLOW`. A plugin can raise the
   outcome, never lower it. This is the reason a compromised agent cannot argue its way
   through: it never gets a vote on the combination.
2. **A class may raise a decision, never lower it.** The class floor is applied *after* the
   verdicts are combined, so no signed order talks an irreversible act back down to a
   machine decision, and a revocation stays a revocation with its reason intact.
3. **Fail-closed on doubt.** Plugin exception, plugin timeout, unclassified tool, unparsable
   parameters → `DENY`. Skipping a control that failed is not an option; the refusal names
   the control that could not answer.
4. **Degradation is per-plugin, not global.** The semantic judge timing out must not switch
   off the deterministic half. Each plugin carries its own timeout and its own failure mode.

## The plugin inventory — and what is actually built

Honest split, per rule D12. "Built" means code in the node repository
([indrad3v4/warrnt](https://github.com/indrad3v4/warrnt)) with tests that ran.

| Phase | Plugin | Status | Where / why not |
|---|---|---|---|
| preflight | `actor_registry` | **built** | `warrnt/actors.py`, `GET /actors` — what this *class* of actor may never call |
| preflight | `warrant_verify` | **built** | `warrnt/warrants.py` — scope · TTL · signature, verified before the rules are read |
| preflight | `param_policy` | **built** | `warrnt/policy.py` + `warrnt/seed.py` — guards on the call's parameters |
| classify | `action_taxonomy` | **built** (node PR #2) | `warrnt/actions.py`, `GET /state → actions` |
| emit | `receipt_chain` + `anchor` | **built** | `warrnt/registry.py`, `warrnt/anchor.py` — hash chain, `fsync`ed, signed head |
| constrain | `destructive_forbid` | **not built** | the flat, non-delegable refusal. Today destructiveness is folded into `irreversible`, whose decider is a human — the opposite of a flat deny |
| constrain | `egress_volume` | **not built** | bulk export of personal data is classified `read_personal` ("the machine decides"), so 12 000 rows and one row are the same class |
| constrain | `budget_governor` | **not built** | no occurrence of "budget" in the node package at all — token, cost and compute ceilings are required by the brief §4.3 and rule D7 |
| inspect | `pattern_inspector` | **not built** | the node records *which* personal fields a call names (`warrnt/actions.py`), but there is no content scanner for PII, secrets or injection markers |
| inspect | `signature_feed` | **not built** | no externally managed feed of known exploits (brief §4.4, rule D8); the only "attack" in the node is the receipt-rewrite red team |
| judge | `semantic_judge` | **not built** | no local-model control anywhere in the package — the semantic half of the hybrid, brief §4.2 |
| decide | `redactor` | **built** (node PR #2) | `Decision.redact` + `warrnt/policy.py:strip_pii` — the call is executed with the personal fields stripped before upstream sees them, and the receipt names the fields; live: `crm.read{fields:[subject,email,pesel]}` → `redact`, upstream saw `["subject"]` |

Five of eleven are slots. The diagrams are drawn for the shape they go into, not for the
shape that exists — the difference is this table.

**The registry itself — as built vs. as drawn.** The core no longer names a gate: `warrnt/gates.py`
is a registry (name · order · `check(ctx)`), every gate is a file under `warrnt/plugins/`
(`act_class` → `actor_scope` → `order_policy`, by `order`) that registers itself on import, and the
first gate that answers decides. `register(..., replace=True)` and `unregister(name)` swap or pull
one while the node runs, and `tests/test_gates.py` proves a gate dropped into the package stops the
pipeline without a kernel line changing. Not built, and therefore not implied by the diagrams'
`PluginRegistry`: discovery through `importlib.metadata.entry_points` (we use `pkgutil` over the
package), order and enable/disable read from the catalog, and `watch()` hot reload.

## Contract drift — closed

The frozen `/api/state` contract carries **five** receipt decisions:
`allow | deny | redact | human | revoked`, and the node's `Decision` enum now carries exactly
those five. The sixth value, `expired`, is gone (node PR #2): a TTL that has elapsed is a
`deny`, and the receipt keeps `warrant_state: "expired"` as the reason. An expired order is a
refused order — it does not get a decision of its own.

The diagrams therefore keep the contract at five values. TTL is drawn as `WarrantState`
(`active` / `revoked` / `expired`), a **lifecycle**, not a receipt value. Emitting `expired`
into a receipt is an extension of a frozen interface, and per rule D13 that needs its own
recorded unfreeze — the reason, the exact field, and the matching update in every consumer —
before it can appear in a diagram of the contract. Fixing the vocabulary first is the rule;
drawing past it is not an option.

## Relation to the node as it stands

The node today wires its four controls directly into the proxy: `proxy.py` calls the actor
register, the warrant check, the parameter policy and (on the next merge) the taxonomy in
sequence. That is correct at ten rules and is what shipped for the checkpoint. The kernel
boundary in these diagrams is the **target** — the refactor that makes the six unbuilt
controls additions rather than edits to `proxy.py`. Nothing here claims that refactor has
happened.

## Re-rendering

Rendered with [Kroki](https://kroki.io) — no local Java, no PlantUML install:

```bash
curl -s -o docs/uml/kernel-components.png \
  -X POST -H "Content-Type: text/plain" \
  --data-binary @docs/uml/kernel-components.puml \
  https://kroki.io/plantuml/png
```

## Sources

- The brief: *AI Control Layer*, HackYeah 2026 Partner Task (Goldman Sachs) — §3.1(b) for the
  diagram, §4.1–4.6 for the control families, §6 for how the submission is evaluated.
- **OWASP Top 10 for Agentic Applications 2026** (ASI01–ASI10), OWASP GenAI Security Project,
  9 December 2025 — ASI02 "Tool Misuse and Exploitation" is the risk a destructive-act class
  answers; "Least Agency" is the principle behind the decision ladder.
- **Cedar / Amazon Bedrock AgentCore Policy** — *default deny, `forbid` overrides `permit`*,
  evaluated at the gateway boundary outside the agent's process. The algebra in
  `kernel-classes.png` follows that precedence.
- **AWS Organizations service control policies** — an explicit deny that no identity policy
  can override, which is the shape `destructive_forbid` needs.
