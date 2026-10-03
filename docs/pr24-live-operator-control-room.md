# PR24 — Live Operator Control Room: design note

## Decision
PR24 changes the Control Room from a static security dashboard into a live operator surface.
The primary object is an action. The UI now has three connected responsibilities: watch the live action, understand the enforcement path, and control the selected action.

## Evidence model
The UI polls the existing security-event projection at 1 second and uses /api/ask to start a real orchestrator run. While the request is executing, the browser continues polling the kernel-backed projection. New events are rendered when they actually exist.
No simulated event lifecycle is generated in the browser. Missing evidence remains unknown.

## Operator journey
1. Ask the orchestrator for a real task.
2. Watch the real security event arrive.
3. Inspect agent, actor, action class, warrant, policy, decision and boundary state.
4. Inspect the causal proof and provider evidence.
5. Use the authenticated deny/revoke paths when available.

## Experience lenses
Essential Experience: the operator should feel that she can see and control AI action before data moves.
Control: actions are contextual to the selected event and never presented as anonymous global switches.
Virtual Interface: the UI exposes security facts that are otherwise distributed across orchestrator, kernel, upstream and receipt records.
Transparency: the operator can explain the decision without reading source code.
Feedback: controls report the actual backend result rather than optimistic UI state.
Channels and Dimensions: lifecycle is spatial, decisions are typographic/status signals, and motion is reserved for real changes.
Modes: LIVE, INVESTIGATE and CONTROL are represented without creating separate technical subsystem screens.

## Research implications
Public Goldman Sachs material emphasizes AI governance, risk management, data lineage, auditability and improved interfaces. NIST emphasizes human roles, auditability, operator explanations and measurable oversight. SOC research emphasizes structured analysis and high-quality contextual signals over alert volume.

Sources:
- https://www.goldmansachs.com/disclosures/client-security-statement.pdf
- https://www.goldmansachs.com/investor-relations/financials/8k/2026/8k-01-15-26.pdf
- https://airc.nist.gov/airmf-resources/playbook/measure/
- https://airc.nist.gov/airmf-resources/playbook/govern/
- https://airc.nist.gov/airmf-resources/playbook/map/
- https://www.usenix.org/conference/soups2023/presentation/kersten
- https://www.usenix.org/conference/usenixsecurity22/presentation/alahmadi
- https://www.oreilly.com/library/view/the-art-of/9781466598645/K16148_C013.xhtml
