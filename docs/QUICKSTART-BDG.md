# Quickstart — Brain Dependency Graph + Neo4j

Stand up a queryable graph of your Brain in under 10 minutes.

This walks you through: bootstrap the BDG sidecar, stand up Neo4j in Docker, load 5K+ atoms into the graph, run your first Cypher query.

---

## What you'll have at the end

```cypher
// 5,411 atoms classified into 7 BDG layers
MATCH (a:Atom) RETURN count(a);
// → 5411

// 881 framework atoms (your generative cores)
MATCH (a:Atom:Framework) WHERE a.lifecycle > 0.6 RETURN a.id ORDER BY a.lifecycle DESC LIMIT 10;

// Orphans (review candidates)
MATCH (a:Atom) WHERE NOT (a)--() RETURN a.id LIMIT 20;

// Cross-layer paths (how a Source becomes a Synthesis)
MATCH path = (s:Signal)-[*..4]->(syn:Synthesis) RETURN path LIMIT 5;
```

---

## Prerequisites (5 min, one-time)

| | |
|---|---|
| Python venv | already set up if you ran `./resources/local-brain-search/run_index.sh` once |
| Docker Desktop | install from [docker.com](https://docker.com), then **launch the .app** before continuing — `docker ps` must return successfully |
| Brain at `$VAULT_BASE_PATH` | check `~/Cornelius/.claude/settings.md` |
| Neo4j credentials | copy `resources/brain-graph/.env.example` → `resources/brain-graph/.env`, edit `NEO4J_PASS` |

```bash
# One-time credential setup
cd ~/Cornelius/resources/brain-graph
cp .env.example .env
$EDITOR .env   # set NEO4J_PASS to a real password
```

> **Security note**: `.env` is gitignored. Never commit it.

---

## Step 1 — Bootstrap the BDG (30 sec)

```bash
cd ~/Cornelius/resources/brain-graph
./run_brain_graph.sh bootstrap
```

What you'll see:

```
Loading LBS graph...
Classifying 5411 nodes...
  Layer distribution:
    signal      :   884
    impression  :     8
    insight     :  3551
    framework   :   881
    lens        :    23
    synthesis   :    60
    index       :     4
Typing 62137 edges...
  Edge type distribution:
    derives-from   :   8350
    instantiates   :   8216
    references     :  37896
    associates     :   7675
    tension        :      0
    supersedes     :      0

Bootstrap complete. Saved to data/graph_enrichments.json
```

> **What happened**: Cornelius read the FAISS NetworkX graph (built earlier by `run_index.sh`), classified each note into one of 7 BDG layers (Signal/Impression/Insight/Framework/Lens/Synthesis/Index) based on its folder + frontmatter, and assigned typed edges to existing wikilinks. The output goes to `data/graph_enrichments.json` (a 15MB sidecar — never edited by hand, always regenerated).

**Verify**:
```bash
./run_brain_graph.sh status
```

Should show layer counts matching the bootstrap output.

---

## Step 2 — Start Neo4j (60 sec)

```bash
docker compose -f docker-compose.neo4j.yml up -d
```

What you'll see:
```
[+] Running 3/3
 ✔ Volume zeus-neo4j-data    Created
 ✔ Volume zeus-neo4j-logs    Created
 ✔ Container zeus-brain-neo4j  Started
```

**Verify** (wait ~30s for boot):
```bash
docker ps --filter name=zeus-brain-neo4j --format '{{.Status}}'
# Expected: "Up 30s (healthy)"  or  "Up 30s (health: starting)"
```

If you see `(health: starting)`, wait another 15s and retry. Neo4j takes time to load APOC + warm caches.

If you see `Restarting` or `Exited`, run:
```bash
docker compose -f docker-compose.neo4j.yml logs neo4j | tail -30
```

**Common errors**:
- `NEO4J_PASS not set` → you skipped the `.env` step above
- `port 7687 already in use` → another Neo4j is running; stop it or change ports in compose

---

## Step 3 — Load the graph (5-10 min)

```bash
./load_neo4j.sh
```

What you'll see:
```
Exporting BDG -> Cypher...
  Wrote 67549 lines to data/bdg.cypher
Waiting for Neo4j healthy...
  Neo4j ready
Loading 67549 Cypher statements into Neo4j...
[progress bar from cypher-shell]

=== Post-load verification ===
+-----------+
| atom_count|
+-----------+
| 5411      |
+-----------+
| rel       | n     |
| REFERENCES| 37896 |
| INSTANTIATES| 8216|
| DERIVES_FROM| 8350|
| ASSOCIATES| 7675 |
+-----------+

Done. Browser: http://localhost:7474 (login as neo4j)
```

> **What happened**: The script ran `export_to_cypher.py` to convert the sidecar JSON into 67k `MERGE` Cypher statements (idempotent, so re-running is safe), then piped them into `cypher-shell` inside the container. Final counts should match the bootstrap output exactly.

---

## Step 4 — First Cypher query (browser, 2 min)

Open [http://localhost:7474](http://localhost:7474).

Log in: `neo4j` / `<your NEO4J_PASS>`.

Paste any of these in the query bar:

**4a — Sanity check (1 row):**
```cypher
MATCH (a:Atom) RETURN count(a) AS atoms;
```

**4b — Your most-connected frameworks:**
```cypher
MATCH (a:Atom:Framework)
WITH a, COUNT { (a)--() } AS degree
RETURN a.id, a.lifecycle, degree
ORDER BY degree DESC
LIMIT 10;
```

**4c — Find orphans (review candidates):**
```cypher
MATCH (a:Atom) WHERE NOT (a)--()
RETURN a.id, a.layer
LIMIT 20;
```

**4d — Cross-layer path (Source → Insight → Synthesis):**
```cypher
MATCH path = (s:Atom:Signal)-[*1..4]->(syn:Atom:Synthesis)
RETURN path
LIMIT 3;
```

If you see results, **you're done**. Brain is now queryable via Cypher.

---

## Schema cheat sheet

| BDG concept | Neo4j label | Source folder | Edge decay |
|-------------|-------------|---------------|------------|
| Signal | `:Atom:Signal` | `01-Sources/` | empirical authority |
| Impression | `:Atom:Impression` | `00-Inbox/` | transient |
| Insight | `:Atom:Insight` | `02-Permanent/`, `AI Extracted Notes/` | mixed |
| Framework | `:Atom:Framework` | `02-Permanent/` (tagged subset) | generative |
| Lens | `:Atom:Lens` | `03-MOCs/` | reflective |
| Synthesis | `:Atom:Synthesis` | `04-Output/` | reflective |
| Index | `:Atom:Index` | `05-Meta/` | meta-structural |

| BDG edge | Neo4j relationship | Decay | Direction |
|----------|--------------------|-------|-----------|
| derives-from | `DERIVES_FROM` | 0.8 | A→B |
| instantiates | `INSTANTIATES` | 0.7 | A→B |
| references | `REFERENCES` | 0.2 | A→B |
| associates | `ASSOCIATES` | 0.05 | bidirectional |
| tension | `TENSION` | 0.0 (immune) | bidirectional |
| supersedes | `SUPERSEDES` | 1.0 | B→A (B replaces A) |

Node properties on every `:Atom`: `id`, `layer`, `lifecycle` (0.0-1.0), `staleness_score` (0.0-1.0), `classification_confidence`.

Edge properties on every relationship: `authority` (`source`|`target`|`none`), `confidence`, `original_type` (`explicit` from wikilink, `semantic` from FAISS).

---

## Re-load after editing notes

```bash
# Re-bootstrap (picks up new/changed/deleted atoms)
./run_brain_graph.sh bootstrap

# Re-load Neo4j (MERGE-idempotent; just upserts deltas)
./load_neo4j.sh
```

> Watchdog auto-bootstrap is on the roadmap. For now this is manual.

---

## Stop / restart Neo4j

```bash
# Stop, keep data
docker compose -f docker-compose.neo4j.yml stop

# Stop + remove container (keeps volume = keeps your graph data)
docker compose -f docker-compose.neo4j.yml down

# Nuclear option (DELETES graph data — won't lose anything; bootstrap+load rebuilds)
docker compose -f docker-compose.neo4j.yml down -v
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `docker: command not found` | Docker Desktop not installed | Install Docker Desktop |
| `Cannot connect to the Docker daemon` | Docker Desktop not running | Launch Docker Desktop, wait for whale icon |
| `ERROR: NEO4J_PASS not set` | `.env` missing or unsourced | `cp .env.example .env`, edit |
| `port is already allocated` | Another Neo4j running | `docker ps`, stop conflicting container |
| `Neo4j did not become ready in 60s` | Slow boot OR plugin install failed | `docker compose logs neo4j` — check for APOC errors |
| `count(a) → 0` after load | Cypher load aborted silently | Check `data/bdg.cypher` line count matches `cli.py status` totals |
| `Authentication failed` | Wrong NEO4J_PASS in `.env` | Edit `.env`, then `docker compose down && up -d` to re-init auth |

---

## What's next?

- **Daily**: edit notes → `./run_brain_graph.sh bootstrap` → `./load_neo4j.sh` → query
- **Weekly**: `./run_brain_graph.sh coherence` for staleness/orphan/decay reports
- **Programmatic queries**: the `zeus-brain` Python SDK + MCP server are queued in Phase F (this roadmap)
- **Cross-machine**: `./discover_remote_vaults.sh home` once Tailscale is up — adds home Mac's vaults to the registry, then re-bootstrap to index them

See `docs/plans/2026-05-11-zeus-graphrag-roadmap.md` for the broader plan.
