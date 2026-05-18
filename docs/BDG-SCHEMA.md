# BDG Schema Reference

The Brain Dependency Graph is a directed, typed knowledge graph layered on top of your Obsidian vault. Same data, two representations:

- **File-based**: `data/graph_enrichments.json` (the sidecar). Canonical. Always regenerated from the vault + LBS index.
- **Neo4j**: projected from the sidecar via `export_to_cypher.py`. Queryable via Cypher. Idempotent.

Both share the schema documented below.

---

## Node labels — the seven layers

Every atom is a `:Atom` plus exactly one layer label.

| Layer label | Vault folder | Default mode | What lives here | Authority |
|-------------|--------------|--------------|-----------------|-----------|
| `:Atom:Signal` | `01-Sources/` | reflective | Raw inputs — book notes, paper summaries, conversation transcripts | Source material wins on conflict |
| `:Atom:Impression` | `00-Inbox/` | reflective | Fleeting captures, not yet processed | Transient; gets promoted or trashed |
| `:Atom:Insight` | `02-Permanent/`, `AI Extracted Notes/`, `Document Insights/` | mixed | Your atomic ideas — one idea per note | Lifecycle determines current mode |
| `:Atom:Framework` | `02-Permanent/` (subset) | generative | Original mental models, frameworks, theories | Highest creative authority — drives downstream |
| `:Atom:Lens` | `03-MOCs/` | reflective | Maps of Content, navigational hubs | Derived from members; rebuilt as members change |
| `:Atom:Synthesis` | `04-Output/` | reflective | Articles, essays, composed output | Can flip to generative via reader feedback |
| `:Atom:Index` | `05-Meta/` | reflective | Meta-structural — dashboards, changelogs, system docs | Always rebuilt, never authored |

A note's layer is detected automatically by `classify.py` based on its folder + frontmatter (`type:` field).

---

## Node properties

Every `:Atom` has:

| Property | Type | Range | Meaning |
|----------|------|-------|---------|
| `id` | string | unique | Relative vault path, e.g. `02-Permanent/dopamine-and-curiosity.md`. **The primary key.** |
| `layer` | string | enum | One of: `signal`, `impression`, `insight`, `framework`, `lens`, `synthesis`, `index` |
| `lifecycle` | float | 0.0-1.0 | Where on the reflective→generative arc. <0.3 = reflective, 0.3-0.6 = crystallizing, >0.6 = generative |
| `staleness_score` | float | 0.0-1.0 | How likely this note needs review. >0.3 = review candidate. Computed via propagation from changed upstream notes |
| `classification_confidence` | float | 0.0-1.0 | How sure classify.py is about the layer assignment |
| `last_coherence_check` | string (ISO date) or null | — | When this node was last walked by `/coherence-sweep` |

Properties are stored in `data/graph_enrichments.json` (sidecar) and mirrored to Neo4j on every export.

---

## Relationship types — the six edge categories

Every edge has a **type** (semantic meaning), **direction** (which note is authoritative), and **decay** (how staleness propagates).

| Type | Cypher name | Decay | Direction | Semantics |
|------|-------------|-------|-----------|-----------|
| derives-from | `DERIVES_FROM` | 0.8 (tight) | A → B | B was synthesized from A. Heavy staleness propagation. |
| instantiates | `INSTANTIATES` | 0.7 | A → B | B is a specific case of framework A |
| references | `REFERENCES` | 0.2 (loose) | A → B | B mentions a concept from A |
| associates | `ASSOCIATES` | 0.05 (near-zero) | bidirectional | B is thematically related to A. No staleness flow. |
| tension | `TENSION` | 0.0 (immune) | bidirectional | A and B productively contradict. Never auto-resolved. |
| supersedes | `SUPERSEDES` | 1.0 (full) | B → A | B replaces A (A is deprecated) |

**Why decay matters**: when a Framework atom changes, staleness flows downstream through the graph. `derives-from` is tight coupling (0.8), so child Insights almost always flagged. `references` is loose (0.2), so passing mentions stay fresh. `tension` is immune (0.0) — contradictions are FEATURES, not bugs, and never get auto-resolved.

---

## Edge properties

Every relationship has:

| Property | Type | Meaning |
|----------|------|---------|
| `authority` | string | `source` (source node wins on conflict), `target` (target wins), or `none` (bidirectional/unresolved) |
| `confidence` | float | Classifier confidence for this edge type (0.0-1.0) |
| `original_type` | string | How the edge was created: `explicit` (parsed from `[[wikilink]]`) or `semantic` (inferred from FAISS similarity) |

---

## Lifecycle phases — when does an Insight become a Framework?

Lifecycle is a **single score** (0.0 to 1.0) that captures where an atom sits on the reflective→generative arc. It's computed from behavioral signals, not declared manually.

| Score | Phase | What it means |
|-------|-------|---------------|
| 0.0-0.3 | reflective | Sources are authoritative for empirical claims |
| 0.3-0.6 | crystallizing | Authority contested — flag conflicts for human review |
| 0.6-1.0 | generative | This atom is authoritative over its downstream |

Signals that push lifecycle up:
- **Citation frequency**: cited by 5+ NEW notes in 30 days → +0.3
- **Generative ratio**: more outbound edges than inbound (>1.0 ratio) → +0.3, (>2.0) → +0.6
- **Cross-domain reach**: cited across 3+ thematic clusters → +0.25
- **Temporal acceleration**: citation rate increasing over time → +0.15

When an Insight crosses 0.6, Cornelius's `/coherence-sweep` flags it: *"This note appears to have crossed into generative territory — consider promoting to framework status."*

---

## Tension edges — productive contradictions

Tensions are the most important departure from a flat knowledge graph. Two notes that:
- Have high semantic similarity (>0.75 by FAISS) AND opposing conclusions
- Where neither side "wins"
- Where resolution would destroy insight, not create it

are linked by a `TENSION` edge.

Example from Erich's vault: *Neuroscience of belief rigidity* ↔ *Buddhist release of attachment* — neuroscience says changing minds is neurologically painful; Buddhism says attachment creates suffering. Both are correct. The tension between them is where new frameworks and articles emerge.

`TENSION` edges:
- Are bidirectional (no authority)
- Have 0.0 staleness propagation (immune)
- Are NEVER auto-resolved — always surfaced for human judgment
- Are detected by `./run_brain_graph.sh tensions` (manual; not run by bootstrap)

---

## Constraints + indexes (Neo4j)

The export creates one constraint at the start:

```cypher
CREATE CONSTRAINT atom_id IF NOT EXISTS FOR (a:Atom) REQUIRE a.id IS UNIQUE;
```

For full-text search over atom IDs, optionally create:

```cypher
CREATE FULLTEXT INDEX atom_fulltext IF NOT EXISTS
FOR (a:Atom) ON EACH [a.id];
```

This enables the `vector` / `hybrid` modes in the MCP `zeus_brain_search` tool.

---

## Idempotency

The export is **MERGE-based**, not CREATE-based. Re-running `./load_neo4j.sh` is safe:
- Existing nodes get their properties updated (ON MATCH SET)
- New nodes get fully created (ON CREATE SET)
- Edges MERGE on (source, type, target) — duplicates impossible

**One subtle case**: if you rename a note in Obsidian, the old Neo4j node becomes an orphan (its `id` no longer matches any vault path). The new node gets created fresh. A periodic `coherence-sweep` would flag the orphan; manual cleanup via Cypher removes it.

---

## Reading the graph

### Useful one-liners

```cypher
-- Status check
MATCH (n:Atom) RETURN count(n) AS atoms;
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC;

-- Orphans (no edges at all)
MATCH (a:Atom) WHERE NOT (a)--() RETURN a.id, a.layer LIMIT 20;

-- Hub atoms (most connected)
MATCH (a:Atom) WITH a, COUNT { (a)--() } AS deg
WHERE deg >= 10 RETURN a.id, deg ORDER BY deg DESC LIMIT 10;

-- Decay candidates
MATCH (a:Atom) WHERE a.staleness_score >= 0.3 OR a.lifecycle < 0.2
RETURN a.id, a.layer, a.lifecycle, a.staleness_score
ORDER BY a.staleness_score DESC LIMIT 20;

-- Cross-layer paths (Source → ... → Synthesis)
MATCH path = (s:Atom:Signal)-[*1..4]->(syn:Atom:Synthesis)
RETURN path LIMIT 5;

-- High-confidence frameworks
MATCH (a:Atom:Framework) WHERE a.lifecycle > 0.6
RETURN a.id, a.lifecycle ORDER BY a.lifecycle DESC;

-- Find tension zones
MATCH (a:Atom)-[t:TENSION]-(b:Atom)
RETURN a.id, b.id, t.confidence;

-- Atoms with only weak edges (associates only)
MATCH (a:Atom)
WHERE all(r IN [(a)--() | r] WHERE type(r) = 'ASSOCIATES')
RETURN a.id, a.layer LIMIT 20;
```

### Via the Python SDK

```python
from zeus_brain import Client

brain = Client.from_env()
print(brain.status())              # {'atom_count': 5411, 'edge_count': 62137}
hubs = brain.hubs(min_degree=10)
orphans = brain.orphans(limit=20)
path = brain.path("02-Permanent/foo.md", "02-Permanent/bar.md")
```

### Via the MCP server

Mount once:
```bash
claude mcp add -s user zeus-brain \
    /Users/erichroepke/Desktop/Cornelius/resources/local-brain-search/venv/bin/python \
    /Users/erichroepke/Desktop/Cornelius/resources/brain-graph/mcp_server.py
```

Then in any project: `zeus_brain_orphans`, `zeus_brain_hubs`, `zeus_brain_path`, `zeus_brain_graph_query` are all available as tools.

---

## When the schema changes

If you add a new BDG layer or edge type:

1. Update `models.py` (add to `Layer` or `EdgeType` enum)
2. Update `brain_graph_config.yaml` (add `artifact_types` entry, default edges)
3. Update `export_to_cypher.py` (`_LAYER_TO_LABEL` or `_EDGE_TYPE_TO_REL` dict)
4. Update `BDG-SCHEMA.md` (this file)
5. Bump version in `data/graph_enrichments.json` (`version: "1.1"`) — older sidecars should fail-fast on load

The atom `id` (vault path) is the only stable primary key. Everything else is regenerated.

---

## Source files

| Concern | File |
|---------|------|
| Data model | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/models.py` |
| Schema config | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/brain_graph_config.yaml` |
| Classification logic | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/classify.py` |
| Persistence (sidecar) | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/store.py` |
| Cypher export | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/export_to_cypher.py` |
| Neo4j loader | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/load_neo4j.sh` |
| Neo4j Docker config | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/docker-compose.neo4j.yml` |
| MCP server | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/mcp_server.py` |
| Python SDK | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/sdk/zeus_brain/` |
| Architecture spec | `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/BRAIN-DEPENDENCY-GRAPH-ARCHITECTURE.md` |

For onboarding, see `/Users/erichroepke/Desktop/Cornelius/docs/QUICKSTART-BDG.md`.
