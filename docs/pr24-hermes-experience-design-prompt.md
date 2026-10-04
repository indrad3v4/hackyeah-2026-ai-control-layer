# PR24 — Hermes / Experience Design prompt

## Mission
Redesign the current TENET Control Room as a live security-operator control surface, not a static dashboard.
The target operator is an archetype: a senior cybersecurity / AI-governance operator at a global investment bank such as Goldman Sachs. Do not imitate Goldman branding. Model high consequence, sensitive data, many systems, low tolerance for ambiguity, and the need to intervene without reading implementation code.

## Research basis
Goldman Sachs publicly describes firmwide and divisional AI governance, risk mitigation, regulatory alignment and intentional restrictions on external LLM access. Its 2026 operating-model material emphasizes risk management, data lineage, auditability, operational-risk insight and improved user interfaces. Treat these as public signals about the operating environment, not claims about private Goldman systems.
NIST AI RMF emphasizes explicit human roles, auditability, traceability, audit logs, calibrated controls, operator-facing explanations, human overrides and escalation paths.
Security-operations research shows alert overload and the need for reliable, explainable, analytical, contextual and transferable information. Structured investigation processes can improve analyst accuracy.
Sources: https://www.goldmansachs.com/disclosures/client-security-statement.pdf ; https://www.goldmansachs.com/investor-relations/financials/8k/2026/8k-01-15-26.pdf ; https://airc.nist.gov/airmf-resources/playbook/measure/ ; https://airc.nist.gov/airmf-resources/playbook/govern/ ; https://airc.nist.gov/airmf-resources/playbook/map/ ; https://www.usenix.org/conference/usenixsecurity24/presentation/yang-limin ; https://www.usenix.org/conference/soups2023/presentation/kersten ; https://www.usenix.org/conference/usenixsecurity22/presentation/alahmadi

## Experience Design Skill
Before changing the UI, locate and read the installed Experience Design Skill in the Hermes environment. Follow its workflow and use its experience lens explicitly. If it references Jesse Schell's The Art of Game Design: A Book of Lenses, inspect the relevant interface lenses rather than inventing a substitute methodology.
Apply at minimum: Lens of Essential Experience; Lens of Control; Lens of Virtual Interface; Lens of Transparency; Lens of Feedback; Lens of Channels and Dimensions; Lens of Modes.
References: https://www.oreilly.com/library/view/the-art-of/9781466598645/K16148_C013.xhtml ; https://scharloth.w.waseda.jp/game/docs/schell.pdf
Do not copy book text. Extract the design questions and apply them to TENET.

## Product truth
TENET chain: operator/user → agent → proposal → enforcement kernel → decision → upstream → result → receipt.
Authority lives in the enforcement kernel. The model can reason and propose; it cannot authorize.
The primary UI object is an action, not an agent inventory, warrant inventory, model-metrics dashboard, kill switch or fake activity feed.

## Required experience
The operator must answer in seconds: what is happening; which agent is acting; what it wants; what resource/data is involved; for whom it acts; what authority it has; what TENET checked; what the kernel decided; whether the boundary was crossed; what proves it; and what she can stop.
The screen should feel like a live conversation with the enforcement system.

## Real-time orchestration
Use the real /api/ask orchestrator path and real /api/security-events evidence.
While /api/ask is running, continue observing the kernel evidence so newly created events appear without a page reload.
Do not simulate a live feed. Do not create fake lifecycle events. Do not animate a made-up decision.
Only render a stage as completed when corresponding evidence exists.
Visible lifecycle: REQUEST → IDENTITY / ENTITLEMENT → WARRANT / POLICY → KERNEL DECISION → UPSTREAM → RECEIPT.
Unknown remains unknown.

## Operator control
Controls must be contextual to the selected action. Prefer Deny action, Require human when the real kernel hold path exists, Revoke agent, and View proof.
Do not create client-side authority. If a control cannot be performed because authentication or a backend contract is missing, explain that and send no unauthorized request.

## Goldman-style operator mental model
The operator is not trying to learn TENET. She is trying to control risk.
Use plain language first. Put technical IDs in proof/context. Make the security decision dominant. Make data movement explicit. Make intervention obvious. Show why the decision happened. Distinguish model evidence from authority. Distinguish not contacted from not proven. Avoid alert-wall aesthetics and decorative graphs with no operational meaning.

## Interface lenses applied to TENET
Essential Experience: I can see what the AI is about to do, understand why TENET permits or blocks it, and intervene before sensitive data moves.
Control: every control must affect the selected object, communicate its consequence, and show evidence of success or refusal.
Virtual Interface: show information invisible in the underlying system but necessary for the operator, at the moment she needs it.
Transparency: the interface should let the operator explain the decision without understanding source code.
Feedback: clicked → request sent → kernel result → UI state. Never optimistic success without evidence.
Channels and Dimensions: use position for lifecycle, typography for intent/decision, motion only for real transitions, color for status, and density for expert context.
Modes: keep three modes: LIVE, INVESTIGATE, CONTROL. Do not create a separate mode for every subsystem.

## Acceptance
UX: first-time operator understands the product in under 10 seconds; first screen shows a live action; primary object is an action; agent, requested action, authority, decision and boundary result are visible.
Real-time: /api/ask can be triggered from the Control Room; the UI observes /api/security-events while it runs; new events appear without reload; selected events remain inspectable.
Evidence: no claim of upstream contact without evidence; no claim of non-contact without evidence; missing evidence is explicit; technical IDs remain inspectable.
Control: deny/revoke use existing authenticated paths; no permission bypass; Require human is not faked.
QA: run the repository pre-lint / console parser checks, then normal CI. Do not merge while required checks are red. After merge verify production.

## Mandatory self-roast before merge
Ask: what still feels like a dashboard? Where does the operator lack control? Where does the UI imply evidence that does not exist? Where is live communication fake or delayed? Which technical detail steals attention? Can a bank security operator explain allow/deny without source code? Can she prove whether data crossed the boundary? Can she intervene without ambiguity?
Fix the issues found by the roast before merge.

Final PR must include implementation, QA evidence, a short design note explaining how the Experience Design Skill and interface lenses were applied, and no invented product capabilities.
