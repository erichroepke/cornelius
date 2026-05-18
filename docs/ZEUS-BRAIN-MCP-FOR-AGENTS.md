# Zeus Brain MCP For Agents

Date: 2026-05-18
Issue: ERI-131

This runbook is for Claude Code, Codex, and Linear Agent workers that need to use the Zeus Brain without exposing local credentials or mistaking task mirrors for source-of-truth context.

## Layer Map

| Layer | What it is | Use it for | Do not use it for |
| --- | --- | --- | --- |
| Brain/wiki | The human-readable knowledge base and source-of-truth notes. Current installed wiki path: `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki`. | Reading design intent, decisions, concepts, context, and closeout notes. | Treating raw graph counts or Linear issue text as the full truth. |
| local-brain-search | Local FAISS/metadata search under `/Users/erichroepke/Desktop/Cornelius/resources/local-brain-search`. | Fast semantic search and connection discovery from shell scripts when MCP is unavailable or when a local command is simpler. | Network access, secret-bearing automation, or direct Neo4j administration. |
| Neo4j | The graph database backing the Brain Dependency Graph. Local Bolt port is `bolt://localhost:7689`. | Graph traversal, relationship queries, path/hub/orphan analysis through approved tooling. | Direct agent edits, credential sharing, or treating raw graph nodes as richer than the wiki notes they index. |
| Neo4j Browser | Neo4j's admin web UI. In this setup, the raw browser is not the normal agent path and may be hidden behind the local console routing. | Human/admin inspection when explicitly needed. | Agent search, routine context gathering, or anything that requires sharing Neo4j credentials. |
| zeus-brain MCP | The Model Context Protocol interface over the Brain graph. Current local URL: `http://127.0.0.1:8788/mcp`. Studio/LAN clients use the same path on the host's LAN or Tailscale address, for example `http://<brain-host-lan-ip>:8788/mcp`. | Safe agent access to status, search, atom retrieval, neighborhoods, paths, hubs, or read-only Cypher. | Publishing secrets, bypassing source-of-truth docs, or mutating server code. |
| Linear | The execution mirror for tasks, owners, status, acceptance criteria, and handoffs. | Selecting work, tracking delivery state, linking evidence and source docs. | Becoming the source of truth for design decisions, Brain content, or final project history. |

## Current MCP Endpoint

Local clients on the Brain host should use:

```text
http://127.0.0.1:8788/mcp
```

Studio or LAN clients should use the Studio/LAN equivalent for the host running the daemon:

```text
http://<brain-host-lan-ip>:8788/mcp
```

Do not paste bearer tokens, Neo4j passwords, `.env` contents, or private LAN inventories into Linear, PR descriptions, public docs, or model-visible prompts. If a client needs a token, configure it in that client's private MCP settings or environment, not in a task description.

## Install In Local Agent Clients

The daemon must be running first:

```bash
launchctl print gui/501/com.zeus-brain.mcp-daemon
```

Claude Code global install:

```bash
claude mcp add --transport http zeus-brain http://127.0.0.1:8788/mcp
claude mcp list | grep zeus-brain
```

Expected:

```text
zeus-brain: http://127.0.0.1:8788/mcp (HTTP) - ✓ Connected
```

Codex global install:

```bash
codex mcp add zeus-brain --url http://127.0.0.1:8788/mcp
codex mcp get zeus-brain
```

Expected:

```text
transport: streamable_http
url: http://127.0.0.1:8788/mcp
enabled: true
```

Linear itself does not directly call arbitrary local MCP servers. Linear is the task system. Linear-connected agents can use Zeus Brain if their runtime also has the `zeus-brain` MCP configured. Put the instruction in Linear issues, not secrets:

```text
Before answering, use zeus-brain MCP: run zeus_brain_status, then zeus_brain_search for the relevant topic, and cite the Brain/wiki note paths.
```

For another Mac on the same private network, use the Brain host LAN or Tailscale address:

```bash
claude mcp add --transport http zeus-brain http://<brain-host-lan-or-tailscale-ip>:8788/mcp
```

Prefer Tailscale over public internet exposure. Do not port-forward `8788` to the open internet.

## How Agents Should Search

Start with the Brain/wiki mental model, then choose the least-privileged search path:

1. If `zeus-brain` MCP is configured, call `zeus_brain_status` first. Confirm `neo4j_reachable` is true and the atom/edge counts are plausible before relying on results.
2. Use `zeus_brain_search` for broad discovery. Prefer `mode="hybrid"` or `mode="graph"` with 5-20 results, then retrieve specific atoms with `zeus_brain_get`.
3. Use `zeus_brain_neighborhood`, `zeus_brain_path`, `zeus_brain_hubs`, and `zeus_brain_orphans` for graph context after you have a candidate atom or concept.
4. Use `zeus_brain_graph_query` only for read-only Cypher. Mutating Cypher is out of scope for agents unless a separate task explicitly grants it.
5. If MCP is unavailable, fall back to local scripts:

```bash
cd /Users/erichroepke/Desktop/Cornelius
./resources/local-brain-search/run_search.sh "your query"
./resources/local-brain-search/run_connections.sh "Atom Or Note Name"
```

When reporting findings, cite the Brain/wiki note path or atom id that informed the answer. If results came from an older index or a failed health check, state that limitation instead of presenting the result as current.

## Plain-English Prompts

Use one of these in Claude Code, Codex, or a Linear worker that has MCP access:

```text
Use zeus-brain MCP. Check status first, then search the wiki for "Hold My Leg project brief" and summarize the strongest matching notes with paths.
```

```text
Search my Zeus Brain for everything related to [topic]. Use graph neighborhoods if you find a relevant atom.
```

```text
Before solving this Linear issue, use zeus-brain MCP to find prior plans, related wiki notes, and graph context. Cite the note paths in your answer.
```

## Write And Update Scope

Read/search tools are safe defaults. Writes are intentionally gated:

- `write_atom` requires `MCP_WRITE_TOKEN` and a matching `token` argument.
- Destination paths must be vault-relative and start with `wiki/` or `raw/`.
- Markdown content must include YAML frontmatter.
- Existing matching content is deduplicated by MD5.
- File writes use tempfile + `os.replace` for atomic replacement.
- Every write is appended to `resources/brain-graph/data/mcp_write_audit.jsonl`.

Automatic broad-drive ingestion is not fully enabled yet. The next product milestone is an approval queue: detect new files, present them in Brain Console, let Erich choose the project/lens/profile, then process and refresh the indexes.

## Security Model

Current safe posture:

- Localhost access for this Mac: `http://127.0.0.1:8788/mcp`.
- Private LAN or Tailscale for trusted machines.
- No public port forwarding.
- No secrets in Linear, docs, PRs, or prompts.
- Use read-only tools by default.
- Use `write_atom` only through a task that explicitly needs to create/update Brain notes.

Future hardening before any public or semi-public hosting:

- Require bearer-token auth at the HTTP transport layer, not only per-tool token arguments.
- Split read token and write token.
- Add request logging and rate limits.
- Bind to Tailscale-only IP or put behind a private reverse proxy.
- Add token rotation documentation.

## Linear Agent Rules

Linear is a task mirror. It is not the canonical knowledge base.

- Use Linear to find the current issue, scope, status, acceptance criteria, owner, blockers, and handoff expectations.
- Use Brain/wiki, local source docs, repo files, and linked plans for the actual source-of-truth reasoning.
- Link Linear issues back to the relevant wiki/MAP/source docs.
- Do not close an issue only because Linear looks complete. Close it only when the source docs or repo evidence explain what changed and why.
- Do not store secrets, raw `.env` values, Neo4j passwords, MCP write tokens, or private network details in Linear.

## Verify Connection

From Claude Code or another MCP-capable agent:

```text
Use zeus-brain MCP and run zeus_brain_status.
```

Expected shape:

```json
{
  "neo4j_reachable": true,
  "sidecar_present": true,
  "atom_count": 6927,
  "edge_count": 67133
}
```

Counts drift as the Brain grows, so use them as a sanity check, not a hard-coded contract.

From shell on the Brain host:

```bash
lsof -nP -iTCP:8788 -sTCP:LISTEN
tail -80 /tmp/zeus-brain-mcp-daemon.err.log
```

Verify Neo4j separately without exposing secrets:

```bash
docker ps --filter name=zeus-brain-neo4j
```

If you must run `cypher-shell`, read the password locally from the private `.env` and do not print it:

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
PASS=$(grep BRAIN_NEO4J_PASS .env | cut -d= -f2)
docker exec zeus-brain-neo4j cypher-shell -u neo4j -p "$PASS" \
  "MATCH (n:Atom) RETURN count(n) AS atoms;"
```

## What Not To Expose

Never expose:

- `BRAIN_NEO4J_PASS`, `NEO4J_PASS`, `ZEUS_BRAIN_TOKEN`, or `MCP_WRITE_TOKEN`.
- Full `.env` files, launchd plist contents with secrets, or copied MCP client configs containing tokens.
- Publicly routable URLs for a private Brain instance.
- Raw private LAN inventories beyond the minimum endpoint needed by an approved client.
- Personal source paths unless the task requires local path context.

Do expose:

- The non-secret endpoint shape: `http://127.0.0.1:8788/mcp` or `http://<brain-host-lan-ip>:8788/mcp`.
- The tool names and read-only usage pattern.
- Health status, counts, and source note paths when useful.
- Links from Linear issues to source docs, without copying secrets into Linear.

## Safe Default For Workers

If you are unsure, use this sequence:

1. Refresh the Linear issue for task scope only.
2. Query `zeus_brain_status`.
3. Search the Brain through MCP.
4. Open the linked Brain/wiki or repo source files.
5. Make changes only in the scoped files.
6. Update Linear with evidence links, not secrets.
