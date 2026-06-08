---
name: erich
description: Use as Erich's front-door planning and system-routing skill. It searches live skill inventory, sidecar context, E-STACK, and workspace state before choosing Codex, E-STACK, Superpowers, Zeus skills, agents, brainstorm workflows, or project wrap-up. Use when Erich asks how to use the system, what skills/agents to invoke, how to plan, how to preserve work, or how to keep Erich in the loop as source-of-truth.
metadata:
  short-description: Route skills and plan with Erich
---

# Erich

The Erich skill is the front door. It answers: "What do we have, what should we use, what is the plan, and how does Erich stay part of the decision?"

Use it before substantial planning, skill selection, agent orchestration, E-STACK cleanup, Zeus work, or ambiguous "what now?" requests.

## First Moves

1. Read mandatory home context if available:
   - `/Users/erichroepke/AGENTS.md`
   - `/Volumes/ZEUS DRIVE/Zeus/Sidecar/CURRENT.md`
   - the `active_note` named in `CURRENT.md`
2. Run live skill search:

```bash
python3 /Users/erichroepke/.codex/skills/erich/scripts/skill_inventory.py \
  --out /tmp/erich-skill-inventory
```

3. Run live tool/system inventory when the request touches MCPs, CLIs, subscriptions, libraries, plugins, components, or paid tooling:

```bash
python3 /Users/erichroepke/.codex/skills/erich/scripts/system_inventory.py \
  --out /tmp/erich-system-inventory \
  --workspace "$PWD"
```

4. Classify the request:
   - `route`: choose skills, agents, or workflow.
   - `brainstorm`: draw out direction before a plan.
   - `plan`: produce an actionable plan with gates.
   - `execute`: hand off to implementation skills or agents.
   - `review`: inspect risks, stale state, or missing verification.
5. State the system route before acting.

Read [references/routing.md](references/routing.md) for routing rules and [references/erich-in-loop.md](references/erich-in-loop.md) for the human decision layer.

## Erich Pass

Before locking a plan, draw out the decision instead of over-prescribing it:

- Mirror the goal in Erich's words.
- Label the tension or constraint.
- Ask one open question only if the answer materially changes the plan.
- Separate facts from assumptions.
- Say what would be done next if Erich says "go."

Do not turn this into generic brainstorming. The target is a plan that Erich recognizes as his intent, with the right system components attached.

## Wrap-Up Gate

Before a session, project, branch, research pass, or agent run fades out, check whether work needs preservation.

Trigger the wrap-up gate when Erich says or implies:

- "we're done", "see you next time", "wrap this up", "finish this off"
- "save this", "don't lose this", "push the plan", "add this to GitHub"
- "where are we?", "what's going on?", "what do we need to do?"
- a project has dirty files, untracked files, agent output, Linear decisions, wiki notes, or a branch that could be stranded

Route to `project-wrapup` when the answer should propose a closing routine. The routine should cover handoff docs, GitHub branch/commit/PR choices, Brain/wiki preservation, Linear mirror updates, verification, and open loops.

Do not auto-commit, push, move files, edit the wiki, or create Linear issues from the wrap-up gate unless Erich explicitly asks to execute after the proposal is clear.

## Search Contract

Live skill knowledge comes from current files, not memory:

- Installed Codex skills: `/Users/erichroepke/.codex/skills/*/SKILL.md`
- E-STACK package manifest: `/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS/E-STACK/codex-skills/manifests/e-stack-skills.json`
- E-STACK runtime skill: `/Users/erichroepke/.codex/skills/e-stack/SKILL.md`
- Sidecar source of truth: `/Volumes/ZEUS DRIVE/Zeus/Sidecar/CURRENT.md`
- MCPs, CLIs, plugin cache, workspace dependencies, and local tool/subscription evidence: `/tmp/erich-system-inventory/system.md`
- Billing/subscription status: Gmail, Stripe, account page, or receipt evidence only. Installed tools and local mentions are `referenced-unverified` until backed by billing or signup evidence.

## Zeus Wiki Search Gate

The Zeus Wiki / Brain graph is the durable knowledge cache. Use it when Erich explicitly asks to search the wiki, when a task depends on prior project decisions, or when planning would materially improve by checking existing Brain context.

Preferred route:

1. Check whether `zeus-brain` MCP or the local Brain Console/search endpoint is available.
2. Run a bounded query against the local wiki/graph/search layer before locking the plan.
3. Cite retrieved wiki notes, source packs, or graph records separately from assumptions.
4. If the index/graph is stale, say so and use filesystem search as a fallback instead of pretending the graph is current.
5. Report cost before using external services. Local Neo4j/FAISS/wiki search has no per-query API bill; external LLM summarization, remote embeddings, OCR/ASR, hosted databases, or web search may cost money.

Skills are also knowledge sources. When a skill, workflow, or routing decision becomes stable, create or update a wiki note for it so future planning can retrieve it from Brain, not only from `.codex/skills`.


If a skill or project is referenced but not found live, label it `referenced-unverified`.

## Route Output

Every Erich pass should output:

```markdown
## System Route

- Request type:
- Skills to use:
- Agents to use:
- Skills to avoid:
- Current evidence:
- Wiki search:
- Closing routine:
- Unknowns:

## Plan State

Goal:
Today:
Success:
Decided:
Open:
Next if Erich says go:
```

Use [references/output.md](references/output.md) for complete templates.

## Default Routing

- Storage, drives, Desktop, laptop, cleanup: `$e-stack`
- Which skill/agent should own this: `skill-navigator`
- Which MCP/CLI/subscription/library/component should own this: Erich system inventory, then `skill-navigator`
- Paid tooling questions: system inventory plus Gmail/Stripe/account evidence; do not infer active subscription from an installed tool
- Multi-agent work explicitly requested: `dispatching-parallel-agents`
- Build/debug/verify a code plan: `writing-plans`, `executing-plans`, `systematic-debugging`, `verification-before-completion`
- Project/chat/session wrap-up, GitHub preservation, handoff docs, wiki/Linear closure: `project-wrapup`, then `finishing-a-development-branch` or `verification-before-completion` if needed
- Zeus research/build/create/ship/watch: `zeus-scout`, `zeus-forge`, `zeus-create`, `zeus-ship`, `zeus-watch`
- Creative or uncertain direction: Erich pass first, then brainstorm mode, then plan

## Anti-Sycophancy

When Erich asks for a judgment, do not just agree. Use:

1. Evidence for the idea.
2. Evidence against the idea.
3. What would have to be true.
4. Your synthesis, labeled as synthesis.
5. Confidence level and next check.

This keeps the system useful without becoming contrarian theater.

## Handoff

After the plan is nailed:

- For read-only work, run the chosen inventory/search/review commands.
- For implementation, invoke the right implementation skill or agent team.
- For E-STACK cleanup, stop at a manifest and approval gate before moves.
- For unresolved direction, continue the Erich pass rather than pretending the plan is ready.
