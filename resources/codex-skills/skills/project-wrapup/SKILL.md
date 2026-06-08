---
name: project-wrapup
description: Use when a project, branch, chat, research pass, agent run, or implementation session appears to be ending and work needs preservation, handoff, GitHub/wiki/Linear closure, or next-session continuity.
---

# Project Wrap-Up

Project wrap-up prevents finished or nearly-finished work from becoming stranded in a local folder, chat transcript, dirty branch, temporary output, or unindexed wiki note.

Use this skill when Erich says or implies:

- "we're done", "see you next time", "wrap this up", "save this", "don't lose this"
- "push the plan", "add it to GitHub", "where are we?", "what's going on?"
- "make sure this is in the wiki", "add a handoff", "finish this off"
- a project has working code, research, Linear issues, or agent output that needs a closing decision

## Core Rule

Propose the closing routine before executing it.

Do not commit, push, move files, create Linear issues, edit the wiki, or close a branch unless Erich explicitly asks for execution after seeing the proposed routine. If he already explicitly asked to implement or push, execute carefully after the proposal is unambiguous.

## First Pass

Gather current state before recommending closure:

```bash
pwd
git status --short
git branch --show-current
git remote -v
find . -maxdepth 3 -type f \( -name '*HANDOFF*' -o -name '*README*' -o -name '*PLAN*' \) | head -50
```

If the task spans multiple repos, run the Git checks in each repo separately and label which repo owns each change.

## Closing Routine

Use this checklist as the default proposal:

1. **State**: summarize what changed, what is live, what is only planned, and what is unverified.
2. **Files**: list dirty files, untracked files, generated/runtime files, secrets, and source docs separately.
3. **Handoff**: create or update a short handoff doc when the next session would otherwise lose context.
4. **Wiki**: decide whether a Brain/wiki note or source-pack should preserve the durable decision.
5. **GitHub**: decide whether to commit directly, create a branch, open a PR, or leave the worktree intact.
6. **Linear**: decide whether Linear needs issues, comments, status updates, or no action.
7. **Verification**: run fresh checks before any completion claim or push.
8. **Open Loops**: name the next action, owner, and blocking condition.

## GitHub Decision

Use this default policy:

| Situation | Recommendation |
| --- | --- |
| Clean, small doc/source update | Commit on current branch if branch policy allows |
| Code or behavior change | Branch or worktree, verify, then push/PR |
| Dirty repo with unrelated user changes | Do not stage all; stage only owned paths |
| Generated indexes, caches, logs, secrets | Do not commit unless explicitly intended source artifacts |
| Work is useful but unfinished | Commit a handoff or push a branch, not a misleading "done" commit |
| Tests fail or verification is missing | Do not claim complete; report blocker and next check |

## Wiki Decision

Use Brain/wiki for durable knowledge, not temporary runtime state.

Preserve:

- accepted decisions
- source inventories
- handoff summaries
- integration maps
- reusable workflows
- project architecture notes

Do not preserve:

- secrets, tokens, `.env` values
- raw cache directories
- large generated indexes unless they are intentionally versioned artifacts
- vague chat summaries without source paths or next action

## Output Template

```markdown
## Wrap-Up Proposal

Current state:
Repos involved:
Files to preserve:
Files to ignore:
Recommended GitHub action:
Recommended wiki action:
Recommended Linear action:
Verification required:
Open loops:
Next if Erich says go:
```

## Escalation

- If work is on a development branch and verified, use `finishing-a-development-branch`.
- Before saying work is complete, use `verification-before-completion`.
- If a reusable workflow was created or changed, use `writing-skills`.
- If multiple independent repos or agents are involved and Erich asks for a team, use `dispatching-parallel-agents`.
