# Local Brain Operator Runbook

Date: 2026-05-17

## Roots

- Brain repo root: `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain`
- Brain wiki: `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki`
- Desktop Brain stub: `/Users/erichroepke/Desktop/Brain` exists only as a stub; do not delete, move, or target it for writes.
- Cornelius control repo: `/Users/erichroepke/Desktop/Cornelius`
- Brain graph runtime: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph`
- Recovery bundle: `/Users/erichroepke/.codex_tmp/m4-handoff`

This machine is now the canonical local Brain host. The M4 is a client/replica
target via `ssh studio`.

## Current Ports

- MCP HTTP daemon: `http://127.0.0.1:8788/mcp`
- Neo4j browser: `http://localhost:7476`
- Neo4j Bolt: `bolt://localhost:7689`
- Neo4j container: `zeus-brain-neo4j`

The Neo4j ports are intentionally not the defaults because another local Neo4j
already owns `7474/7687`.

Agent-facing MCP usage is documented in
[Zeus Brain MCP For Agents](ZEUS-BRAIN-MCP-FOR-AGENTS.md). Use that runbook for
Claude Code, Codex, and Linear Agent instructions, including what not to expose.

## Start/Stop Neo4j

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
docker compose -f docker-compose.neo4j.yml up -d
```

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
docker compose -f docker-compose.neo4j.yml stop
```

Verify:

```bash
docker ps --filter name=zeus-brain-neo4j
```

## Refresh The Graph

Rebuild the sidecar graph from markdown, then reload Neo4j:

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
./run_brain_graph.sh bootstrap --force
./load_neo4j.sh
```

Quick status:

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
./run_brain_graph.sh status
```

Expected current loaded state:

- `6927` atoms
- `67133` Neo4j relationships
- Relationship types: `REFERENCES`, `ASSOCIATES`, `DERIVES_FROM`,
  `INSTANTIATES`, `TENSION`, `SUPERSEDES`

## Use From Claude

Claude Code is configured in `/Users/erichroepke/.claude.json` with:

```text
zeus-brain: http://127.0.0.1:8788/mcp
```

Common tool intents:

- `zeus_brain_status`: graph health and counts
- `zeus_brain_search`: search atoms
- `zeus_brain_get`: retrieve an atom by id
- `zeus_brain_graph_query`: read-only Cypher
- `zeus_brain_hubs`: high-degree atoms
- `zeus_brain_orphans`: disconnected atoms
- `zeus_brain_path`: shortest path between atoms

Manual MCP daemon start:

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
./scripts/run-mcp-http-daemon.sh
```

## Daily Ingest

Dry run:

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
python3 -m daily.cli run --dry-run --max-cost-cents 100
```

Real run:

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
python3 -m daily.cli run --max-cost-cents 100
```

Current local snapshot is already baselined. A dry run should report no new
files unless new content has appeared since the snapshot.

## Launchd Jobs

LaunchAgent files are staged at:

- `/Users/erichroepke/Library/LaunchAgents/com.zeus-brain.mcp-daemon.plist`
- `/Users/erichroepke/Library/LaunchAgents/com.zeus-brain.daily-ingest.plist`
- `/Users/erichroepke/Library/LaunchAgents/com.zeus-brain.sync-to-studio.plist`

They are not registered until explicitly approved. Registering them creates a
persistent network daemon on `0.0.0.0:8788`, schedules daily ingest at 6am, and
schedules one-way Brain sync to the M4 at 4am.

## M4 Client

The M4 Claude config points `zeus-brain` at this machine:

```text
http://192.168.1.241:8788/mcp
```

The `studio` SSH alias currently points to the M4 LAN address:

```text
192.168.1.162
```

## Troubleshooting

If Claude cannot connect:

```bash
lsof -nP -iTCP:8788 -sTCP:LISTEN
tail -80 /tmp/zeus-brain-mcp-daemon.err.log
```

If Neo4j auth fails, confirm the private `.env` exists and contains local-only
Neo4j settings. Do not paste or print the password into tickets, chats, or
Linear:

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
test -f .env
grep -E '^(BRAIN_NEO4J_USER|BRAIN_NEO4J_URI)=' .env
```

If counts look wrong:

```bash
PASS=$(grep BRAIN_NEO4J_PASS /Users/erichroepke/Desktop/Cornelius/resources/brain-graph/.env | cut -d= -f2)
docker exec zeus-brain-neo4j cypher-shell -u neo4j -p "$PASS" \
  "MATCH (n:Atom) RETURN count(n); MATCH ()-[r]->() RETURN type(r), count(*) ORDER BY count(*) DESC;"
```
