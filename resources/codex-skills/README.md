# Codex Skills

This directory is the Git-backed source for Erich-specific Codex skills that must not exist only in local runtime mirrors.

## Current Skills

- `erich`: front-door routing, sidecar grounding, skill/tool inventory, wiki search gate, and wrap-up routing.
- `project-wrapup`: closing routine for preserving project/session work into handoff docs, GitHub, Brain/wiki, and Linear when appropriate.

## Sync

Install or refresh runtime mirrors:

```bash
python3 resources/codex-skills/scripts/sync_codex_skills.py
```

Check mirrors without writing:

```bash
python3 resources/codex-skills/scripts/sync_codex_skills.py --check
```

Configured mirrors:

- `/Users/erichroepke/.codex/skills`
- `/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS/E-STACK/codex-skills/skills`
- `/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS/E-STACK/codex-skills/runtime-mirror/skills`
- `/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS/ERICH` for the standalone Erich copy
