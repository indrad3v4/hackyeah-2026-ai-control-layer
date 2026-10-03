# Design references for this console

**Surface commitment: Monitor over Dashboard.** This screen is watched while something is
happening and read afterwards by someone who was not there. It is not a product page and not
a report; it is a cockpit with four instruments and one legend. Composition: four tiles
(`01 Agents`, `02 Warrants`, `03 The brake`, `04 Proof — receipts`), the class strip
(`05 Six kinds of act`), a 30 px status bar. The page is viewport-locked: `?qa=1` prints a
report proving `scrollH == innerH` and that all four tiles sit inside the viewport.

## Reference models — what we take, what we leave

| Reference | What it is | What we take | What we leave |
|---|---|---|---|
| [Grafana](https://grafana.com/) | Monitoring reference for chart-dense views | Dark, tabular numerals, thin scrollbars, density that survives 20 panels | Panels you can drag; we have four and they are fixed |
| [Stripe Radar](https://stripe.com/radar) | Risk review where a machine decision and a human decision meet | A refusal shows its reason on the same line as the refusal | Queue/backlog metaphors — nothing here waits for us |
| [Linear](https://linear.app/) | Restrained chrome, dense rows | Two accent hues, no gradients, no icon soup | Sidebar and navigation — there is nothing to navigate to |
| [Vercel](https://vercel.com/) | Progressive disclosure in deployment views | Hash and signature live in the row's meta line, not as columns | Summary pages, drill-down routes |
| [AWS CloudTrail](https://docs.aws.amazon.com/awscloudtrail/) | The event is the record | Every decision is an event, including the refusals | Volume as a virtue: 17 findings for one cause is noise, not evidence |
| [AWS IAM Access Analyzer](https://hidekazu-konishi.com/entry/aws_iam_access_analyzer_deep_dive.html) | Findings with a lifecycle; "a rule that archives all findings of a resource type because there were too many of them is a decision to stop looking" | Reasoning before display; a finding means something | Archive/suppress — we never hide a decision |
| [Cerbos](https://cerbos.dev/) | Stateless policy decision point with a decision log | The decision log carries the *inputs*, not just the verdict | Policy languages of its own |
| [Permit.io](https://permit.io/) | Control plane with decision logs answering "why was this button hidden" | The same question, asked of calls: why was this stopped, why was this stripped | SaaS dependency, admin UX for policy authoring |
| [Sigstore Rekor](https://docs.sigstore.dev/rekor/CLI) | Append-only transparency log with inclusion proofs, verified by CLI | The shape: a head, a length, a `verify` you can run, and an anchor that judges the head | Merkle proofs, tiles, log monitoring at that scale |
| [Tailscale admin console](https://tailscale.com/docs/features/access-control/auth-keys) | Revocation that states its own limits ("revoking a key does not deauthorize nodes") | Honesty about revocation timing: the order is pulled, the agent stops on its next call | Dashboard-first admin console |

## Colour is a decision, not decoration

One hue per decision, and a hue means something:

| Decision | Hue | Meaning on screen |
|---|---|---|
| `allow` | green `--ok` | ran, inside the order |
| `redact` | cyan `--strip` | **ran, and the personal fields did not** |
| `human` | amber `--hum` | the machine refused to decide alone; a person decides |
| `deny` | red `--deny` | never reached the tool |
| `revoked` | red, struck through | the order is gone |

Amber is the only hue that means "waiting for a person", so it never appears on an executed
call.

## Slop audit of the previous version

1. **A decision existed on paper and not on screen.** The contract's vocabulary includes
   `redact`; the console had no pill for it, so a redact receipt would have rendered as a
   grey unknown. Any decision the screen cannot show is a decision the operator will miss.
2. **The answer to "who decides" was invisible.** `/api/state.actions` carries the six
   classes with their deciders; the screen showed agents, orders and receipts but never the
   taxonomy those decisions come from.
3. **The footer quoted numbers with nothing attached.** Percentages and latencies were
   rendered without saying which run they came from.

## What this change applies (each verifiable)

1. `redact` is a first-class pill (cyan), rendered from the live feed's own `decision` field.
2. Strip `05 Six kinds of act` — six classes, decider, one-line meaning, the tools each class
   covers — read from `state.actions`; the offline demo falls back to the same six rows.
3. The demo scenario now shows a redact before it shows the deny: the same copilot read that
   names `email` and `pesel` is allowed *with the fields stripped*, and the export attempt
   after it is still refused. Two different answers to two different questions.
4. The status bar prints the last run's numbers rather than a vibe:
   `80 pytest · 35/35 console · 18/18 upstream · 29/29 boundaries · 20/20 live`.
5. The QA hook additionally reports `cellSpills` and `cellClipped` for the class strip, so a
   clipped label is a check result, not an opinion.

**Evidence:** `warrnt-screen/shot-live-redact.png` — headless Chromium at 1600×1000 against
a *live* node (`warrnt serve`, one real `crm.read` call whose payload the upstream received as
`fields: ["subject"]`), taken with `?qa=1` so the no-scroll and no-spill assertions are part
of the artifact.

## Not wired here (and said so on the page)

The live feed needs the node. Opened as a plain static file — as on GitHub Pages — the console
falls back to its scripted scenario and says `demo feed`. The seam is one HTTP call wide:
`GET /api/state`.
