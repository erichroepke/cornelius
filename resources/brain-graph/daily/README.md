# Daily Routine — Brain Auto-Organizer

A scheduled pipeline that ingests new content from anywhere on the hard drive (and the Mac Studio over Tailscale when reachable), classifies it, routes it into `~/Desktop/Brain/`, runs Cornelius extraction skills on appropriate content, re-bootstraps the BDG, and writes a daily digest.

## What it does, in order

| Step | Module | Job |
|---|---|---|
| 1 | `sweeper.py` | Diffs `~/Desktop`, `~/Documents`, `~/Downloads`, and any `Inbox/` dir under `~/` against `data/raw-inventory.last.json`. Returns NEW files since last run. |
| 2 | `router.py` | Classifies each new file by extension + frontmatter + content sniff. Proposes a destination (`raw/Quick Captures`, `wiki/Sources/Books`, `wiki/AI Extracted Notes`, etc.). |
| 3 | `processor.py` | For new sources, invokes Cornelius `/extract-insights` (your content) or `/extract-document-insights` (PDFs/EPUBs) via `claude -p` headless. Logs to SQLite. Respects `--max-cost-cents` cap. |
| 4 | `enricher.py` | Re-runs `./run_brain_graph.sh bootstrap --force` then `./load_neo4j.sh` to refresh the BDG sidecar and Neo4j projection. |
| 5 | `digest.py` | Writes `~/Desktop/Brain/wiki/Meta/Changelogs/daily-YYYY-MM-DD.md` summarizing the run. |

## Install

```bash
# 1. Verify Python deps are in the LBS venv (already installed):
source ~/Cornelius/resources/local-brain-search/venv/bin/activate
python -c "import sqlite3, hashlib, subprocess; print('ok')"

# 2. Dry-run to validate plumbing (no writes, no API calls):
cd ~/Cornelius/resources/brain-graph
python -m daily.cli run --dry-run

# 3. Install launchd job to run daily at 6am:
cp ~/Cornelius/resources/brain-graph/daily/com.zeus-brain.daily-ingest.plist \
   ~/Library/LaunchAgents/com.zeus-brain.daily-ingest.plist
launchctl load ~/Library/LaunchAgents/com.zeus-brain.daily-ingest.plist

# 4. Verify it's queued:
launchctl list | grep zeus-brain.daily-ingest
```

## Run manually

```bash
cd ~/Cornelius/resources/brain-graph

# Default — full pipeline
python -m daily.cli run

# Dry-run — sweeper + router only; no file moves, no API calls
python -m daily.cli run --dry-run

# Cap cost at $1
python -m daily.cli run --max-cost-cents 100

# See state
python -m daily.cli status
```

## Rollback

Every move into `raw/` or `wiki/` is logged to `~/Cornelius/resources/brain-graph/data/daily_audit.db`. To reverse a day's moves:

```bash
python -m daily.cli rollback 2026-05-13
```

Moves are reversed via `mv dest src`. If the source path is occupied (shouldn't happen, but defensive), the dest goes to `~/.Trash/daily-rollback-conflict-YYYY-MM-DD-<name>/`.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.zeus-brain.daily-ingest.plist
rm ~/Library/LaunchAgents/com.zeus-brain.daily-ingest.plist
```

## Design constraints

- **NEVER auto-touches `wiki/Permanent/`** — all auto-routing lands in `raw/*` or `wiki/AI Extracted Notes/` (separate provenance). Permanent promotion requires explicit user action (Cornelius `/graduate-insights`).
- **`rm` is forbidden** — rollbacks use `mv ~/.Trash/`.
- **TCC-safe** — external drive writes go through `/bin/zsh -c cp` subprocess pattern.
- **Idempotent** — md5 + mtime + size state in `data/raw-inventory.last.json`. Re-running the same day produces same result.
- **Budget cap** — `--max-cost-cents` default 500 ($5). Processor aborts if running cost exceeds cap.

## Files

| File | Purpose |
|---|---|
| `__init__.py` | Package init + version |
| `sweeper.py` | Inventory walk + md5 diff against last state |
| `router.py` | File-type → Brain layer classification |
| `processor.py` | `claude -p` headless skill invocations |
| `enricher.py` | BDG bootstrap + Neo4j reload delegation |
| `digest.py` | Daily Changelog markdown writer |
| `cli.py` | `python -m daily.cli {run, rollback, status}` |
| `test_daily.py` | pytest unit tests for router constants + digest formatting |
| `com.zeus-brain.daily-ingest.plist` | launchd 6am trigger |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `launchctl list` shows zeus-brain but exit code non-zero | Check `/tmp/daily-routine.err.log` (the plist writes errors there) |
| Sweeper finds 0 files even though there are new files | Check `data/raw-inventory.last.json` mtime — may need `rm data/raw-inventory.last.json` for full re-sweep |
| Processor stuck on a single file for >10 min | Likely a hung `claude -p` subprocess. Kill with `pkill -f 'daily.cli run'`, restart |
| Neo4j reload fails | `docker ps` + check container health. If down: `docker compose -f docker-compose.neo4j.yml up -d` |
| Wrong layer assignments after run | LBS index may be stale. `cd ~/Cornelius/resources/local-brain-search && ./run_index.sh`, then re-run daily routine |
