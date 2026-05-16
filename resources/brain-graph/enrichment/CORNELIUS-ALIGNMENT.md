# Enrichment Orchestrator — Cornelius Alignment

How this orchestrator EXTENDS the Cornelius agentic structure for batch use.
This document is the load-bearing reference for "is the orchestrator doing
what Cornelius would do?" — read this first before changing semantics.

---

## What we keep from Cornelius (load-bearing)

### Edge type vocabulary — exact match

The 6 allowed edge types in `prompts.py::ALLOWED_EDGE_TYPES` mirror
`~/Cornelius/resources/brain-graph/models.py::EdgeType` EXACTLY:

| Cornelius BDG (models.py) | Orchestrator (prompts.py) | Decay | Notes |
|---|---|---|---|
| `derives-from` | `DERIVES_FROM` | 0.8 | A's claim depends on B |
| `instantiates` | `INSTANTIATES` | 0.7 | A is specific case of framework B |
| `references` | `REFERENCES` | 0.2 | A mentions B without depending |
| `associates` | `ASSOCIATES` | 0.05 | Thematic, bidirectional |
| `tension` | `TENSION` | 0.0 | Productive contradiction, bidirectional |
| `supersedes` | `SUPERSEDES` | 1.0 | A replaces B (B deprecated) |

The orchestrator uses SCREAMING_SNAKE because that's the Neo4j Cypher
convention. Cornelius's BDG uses kebab-case for the JSON sidecar. The
mapping is mechanical (`derives-from` ↔ `DERIVES_FROM`). The agents are
instructed in `SYSTEM_PROMPT` to emit SCREAMING_SNAKE so downstream Cypher
MERGE works directly.

### Layer semantics — exact match

Same 7 BDG layers (Signal, Impression, Insight, Framework, Lens,
Synthesis, Index). The orchestrator's prompt includes anchor + candidate
layer hints so the LLM can reason about layer-appropriate edge types
(e.g., framework → insight is `INSTANTIATES`; signal → insight is
typically `DERIVES_FROM`).

### Authority / direction model — same

`A->B` / `B->A` / `bidirectional`. Per BDG, only `ASSOCIATES` and
`TENSION` accept `bidirectional`. Parser enforces this rejection.

### Lifecycle + staleness — read-only consumer

The orchestrator does NOT write `lifecycle` or `staleness_score` on
edges. Those are computed by Cornelius's `compute-lifecycle` and
`propagate-change` skills, separately. The orchestrator's job is to
PROPOSE new typed edges; everything downstream of edge existence
(lifecycle drift, staleness cascades) remains under Cornelius's control.

---

## What we extend (orchestrator's value-add)

### Batch-scale dispatch

Cornelius's `find-connections` skill is designed for one-note-at-a-time
INTERACTIVE use. The narrative output is human-readable, not
machine-parsable. The orchestrator does the same WORK at 5,000-atom
scale with structured JSON output. Same semantics; different I/O shape.

### Persistent queue + audit trail

Cornelius doesn't have a per-proposal audit log. The orchestrator
records every proposal + status transition in `data/enrichment.db`
(SQLite). This enables:

- **Re-run safety**: deterministic proposal IDs (`sha1(from>type>to)`)
  collapse duplicates. Running orchestrator twice cannot create
  duplicate proposals.
- **Consensus across runs**: if Run 1 proposes (A, DERIVES_FROM, B) at
  confidence 0.8 and Run 2 proposes the same edge at 0.9, the row's
  `consensus_n` increments and `confidence` averages. Higher consensus
  = stronger signal for auto-commit.
- **Forensic trail**: SQLite `audit` table records every status
  transition (proposed → committed/review/discarded) with actor + ts.
  Lets us answer "why is this edge in Neo4j?" months later.
- **Resumable**: if 1000 of 5000 batches complete and the process
  dies, restart picks up at batch 1001. Cornelius's interactive
  skills have no resume.

### Three-tier consensus routing

The orchestrator routes proposals based on agreement + confidence:

| Tier | Trigger | Action |
|---|---|---|
| High-confidence consensus | conf ≥ 0.85 AND ≥2 agents agree | Auto-commit to Neo4j |
| Mid-confidence | 0.6 ≤ conf < 0.85 OR only 1 agent | Queue for human review (markdown in `_outputs/edge-review/`) |
| Low-confidence | conf < 0.6 | Discard with audit reason |

Cornelius's `connection-finder` doesn't make commit decisions — it
surfaces connections for human reading. The orchestrator productionizes
the decision, but lifts the THRESHOLD policy from how a human reading
Cornelius's output would mentally filter ("ok this is solid", "this is
maybe", "skip").

---

## What we explicitly do NOT replace

The following Cornelius skills remain canonical — the orchestrator does
not duplicate them:

| Cornelius skill | What it does | Why orchestrator doesn't replace |
|---|---|---|
| `find-connections` (interactive) | Narrative connection discovery for one note | Different I/O shape; orchestrator does the BATCH variant |
| `auto-discovery` | Random cross-domain sampling for serendipity | Different goal — orchestrator is exhaustive over a queue; auto-discovery is probabilistic exploration |
| `detect-tensions` | Find high-similarity + opposing-conclusion pairs | Orchestrator emits TENSION edges via its general loop; `detect-tensions` is a focused single-purpose run |
| `compute-lifecycle` | Score each atom 0-1 on reflective→generative arc | Pure Cornelius — orchestrator does NOT touch lifecycle |
| `propagate-change` | Walk downstream from a changed atom | Pure Cornelius — orchestrator does NOT touch staleness |
| `coherence-sweep` | Weekly composite report (orphans, hubs, decay, tensions) | Pure Cornelius — orchestrator does NOT replace this; it FEEDS data into it via new edges |
| `graduate-insights` | Promote candidate notes to permanent status | Note-level, not edge-level; orthogonal concern |

---

## Integration points

### Input

The orchestrator reads `data/graph_enrichments.json` (Cornelius BDG
sidecar). Format documented in
`~/Cornelius/resources/brain-graph/BRAIN-DEPENDENCY-GRAPH-ARCHITECTURE.md`
under "Per-Note Metadata (Sidecar JSON)".

### Output

Committed proposals are MERGE'd into Neo4j via the same export pattern
`export_to_cypher.py` uses. Edge ID + properties match what the BDG
sidecar would project. After enrichment + Neo4j MERGE, the BDG sidecar
remains the canonical source — but Neo4j now has the union (structural
edges from sidecar + semantic edges from enrichment).

### Round-trip preservation

If the orchestrator commits a `DERIVES_FROM` edge, then a subsequent
`./run_brain_graph.sh bootstrap` runs and overwrites `graph_enrichments.json`
with a fresh classify-from-wikilinks pass, the orchestrator-committed
semantic edge is NOT in the sidecar (only structural wikilinks are).
Two ways to handle this:

1. **Re-run after bootstrap** (current default). Orchestrator queue
   tracks last successful run; on next launch, finds new/changed atoms
   and re-proposes.
2. **Write proposed edges back to sidecar** (FUTURE). Add a
   `semantic_edges` block to `graph_enrichments.json` that
   `export_to_cypher.py` can pick up. Requires Cornelius BDG schema
   extension.

For v1 we use approach 1 — simpler, no Cornelius schema changes, idempotent.

---

## Open questions (resolve before first-pass run)

1. **Prompt parity with `find-connections`**: should the orchestrator's
   `SYSTEM_PROMPT` literally include the Cornelius `find-connections`
   skill text verbatim, or paraphrase? Verbatim = stronger fidelity but
   couples to internal Cornelius prompt updates. Currently paraphrase.

2. **Edge writeback into BDG sidecar**: per "Round-trip preservation"
   above, do we extend the BDG sidecar schema, or accept re-run cost?
   Currently re-run. Revisit if bootstrap+re-enrich cycle exceeds
   acceptable latency.

3. **Lifecycle integration**: should `compute-lifecycle` re-run after
   the orchestrator commits semantic edges? New edges change the
   generative-ratio signal. Currently: yes, manually. Could automate
   as a post-commit hook.
