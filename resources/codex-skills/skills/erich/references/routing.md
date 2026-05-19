# Routing

Use the smallest useful route. Do not load every skill because many are installed.

## Request Types

- `route`: "what should we use?", "what skills?", "what agents?"
- `brainstorm`: "think through this", "explore options", "what could this be?"
- `plan`: "what is the plan?", "lay this out", "how do we do it?"
- `execute`: "go", "do it", "install", "fix", "run"
- `review`: "check this", "does this make sense?", "what is risky?"
- `wrapup`: "save this", "don't lose this", "push the plan", "see you next time", "where are we?", "what's going on?"

## Canonical Routes

| Need | Route |
| --- | --- |
| Skill choice, duplicate policy, agent assignment | `skill-navigator` |
| MCPs, CLIs, subscriptions, libraries, plugins, component sources | `$erich` system inventory, then `skill-navigator` |
| Storage estate, drive cleanup, Desktop/laptop organization | `$e-stack` |
| Explicit team of agents | `dispatching-parallel-agents` + `subagent-driven-development` |
| Work plan for implementation | `writing-plans` |
| Execute existing plan | `executing-plans` |
| Debug failure | `systematic-debugging` |
| Final proof | `verification-before-completion` |
| Preserve project/session work, handoff docs, GitHub/wiki/Linear closure | `project-wrapup` |
| Branch completion, PR, merge readiness | `finishing-a-development-branch` |
| Research/intelligence | `zeus-scout` |
| Build pipeline | `zeus-forge` |
| Create frontend/design artifact | `zeus-create` |
| Ship/review | `zeus-ship` |
| Monitor/watch | `zeus-watch` |

## Avoid

- Do not use multi-agent work unless Erich asks for agents, a team, or parallelism.
- Do not start with execution when the request is actually about direction.
- Do not let wrap-up requests become vague summaries; propose a concrete closing routine.
- Do not commit, push, move files, update Linear, or edit the wiki from wrap-up without explicit execution approval.
- Do not treat old project index entries as live if the folder is missing.
- Do not trust a static skill list when live inventory can be checked quickly.
- Do not infer a paid subscription from a local install, signup email, or note. Require receipt, invoice, billing page, or account evidence.
