# Project Wrap-Up Checklist

Use this checklist when preparing a closing routine.

## Preserve

- Handoff document with current state, repo paths, branches, verification evidence, and next action.
- Wiki note or source-pack when the work changes durable project knowledge.
- Git commit or PR when source files changed and verification is fresh.
- Linear issue/comment only when Linear is the execution mirror for this work.

## Do Not Preserve By Default

- `.env` files, tokens, credentials, local MCP auth headers.
- Build caches, FAISS indexes, SQLite runtime DBs, transient logs.
- Large raw media or mounted-drive mirrors.
- Unrelated dirty user changes.

## Required Evidence

- `git status --short` for each repo.
- Branch and remote for each repo.
- Fresh test/check command when code changed.
- Source paths for wiki docs or handoff docs.
- Explicit list of open loops.
