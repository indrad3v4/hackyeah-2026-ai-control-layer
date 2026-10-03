# Where the control layer can stand — six variants, read against our case

Written 2026-10-03 for the Goldman Sachs Partner Task *AI Control Layer*. Every claim below
comes from a source fetched and stored in our research vault the same day; the URL is given so
the next reader (human or agent) can re-fetch rather than trust this summary.

## The six variants

| # | Where the check sits | What it sees | What it cannot see | Source |
|---|---|---|---|---|
| 1 | **In-process middleware / SDK** (`LangChain` callbacks, `CrewAI` decorators, ADK plugins) | every tool call in the host process, sub-millisecond | anything not routed through the host's own client — another MCP client, a subprocess, raw `curl` from the model's own credentials | [flux7.art](https://flux7.art/blog/middleware-vs-sidecar), [Microsoft AGT Integration Tiers](https://microsoft.github.io/agent-governance-toolkit/integration-tiers/) |
| 2 | **Sidecar / out-of-process proxy** | every call that crosses the process boundary, language-agnostic, works for a fleet you do not control | nothing inside the process before the call leaves it; adds a hop and needs the agent to actually point at it | [flux7.art](https://flux7.art/blog/middleware-vs-sidecar) |
| 3 | **Gateway at the tool edge (MCP gateway)** — our node | the request, its parameters and the caller's identity *before* the tool runs | intent that never becomes a call | [trussed.ai](https://trussed.ai/resources/ai-runtime-enforcement-points-gateway-vs-sidecar-vs-sdk) |
| 4 | **Policy Decision Point (PDP) + PEP** — OPA/Rego, AWS Cedar, XACML lineage | the question "given this principal, this tool, these arguments, this context — allowed?" and nothing about how the caller feels about it | the decision itself unless the PEP records it: the pattern externalises *logic*, not evidence | [tianpan.co](https://tianpan.co/blog/2026-04-25-policy-as-code-agent-permissions-opa-rego) |
| 5 | **Five-plane reference architecture** (reasoning plane + network / identity / endpoint / data enforcement planes), with *stop-anywhere mediation* and a *composite principal* | intent adjudicated against a principal that is agent + user + session, then realised in four infrastructure planes | it is a decomposition, not a product: it tells you where to put things, not what to refuse | [arXiv 2606.12320](https://arxiv.org/abs/2606.12320) |
| 6 | **Aggregate-constraint layer** (governance above the per-call checks) | the *distribution* of outcomes across agents and populations | — and it is the variant nobody builds, which is the point of the finding it comes from | [arXiv 2609.27994](https://arxiv.org/abs/2609.27994) |

## What this means for our case

1. **Variants 1 and 2 are not competitors of 3 — they are different coverage.** Microsoft's own
   tiering says it out loud: Tier 1 is a thin in-process wrapper, Tier 2 is deep runtime
   integration. Both live inside the agent's process. A layer that must hold for *any* agent,
   including the one whose credentials the model already has, cannot be in-process. That is why
   our check sits at the tool edge (variant 3).
2. **Variant 4 is where our vocabulary comes from, and where we deliberately differ.** The PDP
   pattern says the engine answers *allowed / not allowed*. Our receipt says
   `allow | deny | redact | human | revoked` — the frozen `/api/state` contract (README) — so the
   decision space is a record, not a boolean, and the interesting value is `human`. "The agent
   runtime never gets to vote" is the right instinct; "the answer is a boolean" is the part we
   refuse. The runtime contract is now aligned: an expired warrant is refused as `deny` with
   `warrant_state: expired`, while `redact` is implemented and recorded.
3. **Variant 5 gives us the shape we lack.** A reasoning plane that adjudicates *intent* against
   a composite principal is exactly the gap left after today's work: our node sees calls, not
   campaigns. Recorded as the honest next layer, not claimed as built.
4. **Variant 6 is the intellectual trap worth naming in the pitch.** In regulated finance, each
   agent can be locally compliant while the fleet is collectively discriminatory: the paper's
   result is that a local equal-treatment check on imperfect, group-dependent measurements can be
   *incompatible* with an aggregate disparity constraint. No amount of per-call policy fixes
   that — it needs a layer above the calls. We state it as a limit of our own design, which is
   stronger than pretending the per-call checks are sufficient.
5. **Coverage we are not buying:** network-plane enforcement (egress filtering) and endpoint-plane
   enforcement (what runs on the host) are outside this node. We say so instead of implying the
   node covers them.

## Sources in the vault

All six were fetched 2026-10-03 into `/root/.hermes/hpr-vault/research/notes/` under the run tag
`t-hackyeah-2026-10-03` and are readable offline.
