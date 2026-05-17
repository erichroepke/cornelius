# ZEUS BRAIN — Plan File (Multi-Phase)

**Active phase:** v3 Studio Integration (see bottom of file).
**Completed phases:** v2 Vault Consolidation Policy + v2.1 Sub-Folder Cleanup + v2.2 raw+wiki Restructure (all shipped — content preserved below as historical record).

**Plan file:** `/Users/erichroepke/.claude/plans/sunny-cooking-honey.md`
**Live state:** Brain at `~/Desktop/Brain/` is canonical with 5,609 atoms / 63,320 Neo4j edges. Phase F live. Daily routine activated. Team B three-pass enrichment shipped 135 semantic edges (32 auto-committed in passes 1+2, 103 from pass 3 pending MERGE). Studio NIKLAS staged for merge. Pattern C federation pending implementation.

---

# v2 Vault Consolidation Policy (HISTORICAL — DONE)

**Date:** 2026-05-13 (rewritten — earlier content superseded by Cornelius GraphRAG roadmap and the /autoplan review appended to it)
**Supersedes:** the earlier "ZEUS BRAIN unified knowledge graph" v1 plan written in this file. The architecture, MCP server design, Phase F sequencing, and code fixes are tracked in `/Users/erichroepke/Cornelius/docs/plans/2026-05-11-zeus-graphrag-roadmap.md` (Erich's roadmap + /autoplan review). This file now focuses ONLY on the vault-consolidation policy + the execution wiring that has been resolved interactively.

---

## Context

The unified-knowledge-graph plan reached premise-locked approval via /autoplan: Brain at `~/Desktop/Brain` is canonical, Phase F (Neo4j + Qdrant) activates now, multi-machine federation via Tailscale + SSH is in scope, Trinity deferred, all vaults indexed with `origin_vault` tags. Four critical eng fixes already landed (atomic write, export-json subcommand, env-var creds, shell-injection patch). The MCP server, Python SDK, multi-machine discovery script, 35-test suite, and QUICKSTART/SCHEMA docs are all built and ready.

What this v2 plan resolves: **per-vault decisions** that the original plan left as "all vaults indexed" without specifying which physically MOVE vs INDEX-IN-PLACE vs TRASH. Erich confirmed each interactively today (2026-05-13).

Why this matters: there are 13 candidate vaults on this Mac plus an unknown count on the Mac Studio. The big WHISKEY 2 drive holds **1.4 TB** of project archives — physically relocating it is impossible. Cornelius/Brain is a stale duplicate of Desktop/Brain. Several small "project" folders in `~/Documents/` are better as Brain content than as separate federation points. Each vault needs an explicit verdict.

---

## Per-Vault Verdict Table (Erich-confirmed)

| Vault | md count | Size | Verdict | Action |
|---|---|---|---|---|
| `~/Desktop/Brain` | 5,459 | 50M | **CANONICAL** | Already BDG-bootstrapped (5,411 nodes, 62,137 edges). No change. |
| `~/Cornelius/Brain` | 5,430 | 27M | **TRASH** (stale duplicate) | `mv ~/Cornelius/Brain ~/.Trash/cornelius-brain-stale-2026-05-13/` — Desktop is 29 atoms ahead, same SHA256 on sampled file, no unique content |
| `~/Desktop/NIKLAS` | 2.5M (271k pollution + 3,676 atoms — 0 unique vs Brain) | 17G | **TRASH POLLUTION + READONLY MARKER** | Move 271k auto-gen `__folder__.md` / `__init__.py.md` to Trash; add `READONLY.md` at root |
| `~/Desktop/JIMMY 2 BRAIN` | 2,272 | 617M | **STAYS SEPARATE — indexed only** | Add to vaults-registry as `kind: archive`; Neo4j ETL crawls with `origin_vault=jimmy` |
| `~/Desktop/BERT` | 12,593 | 5.3G | **STAYS SEPARATE — project vault** | Already in registry; Neo4j indexes as `origin_vault=bert` |
| `~/Desktop/BERT/4-2026_BERT` | 9,727 (nested in BERT) | 3.4G | **STAYS SEPARATE — nested project** | Indexed via parent BERT crawl |
| `~/Desktop/BERT-Wiki` | 195 | 3.7M | **ADD — index** | Add to registry; Neo4j indexes with `origin_vault=bert-wiki`. Small + content-dense. |
| `~/Desktop/1-2026_ARC` | 4,084 | 3.1G | **SKIP** | Erich: "we don't necessarily need to add" |
| `~/loriann_local_wiki` | 152 | unknown | **TRASH** | `mv ~/loriann_local_wiki ~/.Trash/loriann-local-wiki-2026-05-13/` |
| `~/Documents/AI CONSULTING` | 32 md + 38 non-md | 62M | **PHYSICALLY MOVE INTO BRAIN** | `mv ~/Documents/AI\ CONSULTING ~/Desktop/Brain/04-Output/projects/ai-consulting/` (Cornelius Output layer = right home for project artifacts) |
| `~/Documents/Claude` | 36 md + 34 non-md | 38M | **PHYSICALLY MOVE INTO BRAIN** | `mv ~/Documents/Claude ~/Desktop/Brain/04-Output/projects/claude-artifacts/` |
| `/Volumes/WHISKEY 2/BERT ` (trailing space) | 9,676 md + 202,652 non-md | 57G | **INDEX .md ONLY, in place** | Add to registry with `host: local-whiskey2`; Neo4j ETL crawls only `*.md` files |
| `/Volumes/WHISKEY 2/ZEUS_PROJECTS` | 46,721 md + 656,536 non-md | **1.4 TB** | **INDEX .md ONLY, in place** | Same — registry entry + ETL `.md` crawl. Non-md (videos, builds, raw) stays put. |
| `/Volumes/WHISKEY 2/ZEUS_PROJECTS/2026/1-2026_ZEUS_OBSIDIAN` | 28 | unknown | **Implicit (covered by parent ZEUS_PROJECTS crawl)** | No separate registry entry needed |
| Mac Studio vaults | unknown | unknown | **DISCOVER + index in place** | Run `./discover_remote_vaults.sh studio` (LAN-direct SSH); each remote vault added with `host: studio`, `tailscale_name: erichs-mac-studio` |

---

## Mac Studio Connection — Already Wired

SSH config (`~/.ssh/config`) already has 4 host aliases for Mac Studio:

| Alias | Path | When to use |
|---|---|---|
| `studio` | LAN-direct (likely `studio.local` or similar mDNS) | **DEFAULT** — same network, fastest |
| `studio-ts` | Tailscale-mediated | Fallback when off-LAN |
| `erichs-mac-studio.tail1af2e9.ts.net` | Full Tailnet name | Explicit Tailscale form |
| `jon` | Jon Rose's home Mac (per memory) | Unrelated to ZEUS BRAIN — leave alone |

SSH public key: `~/.ssh/id_ed25519.pub` is configured.

**Sidecar is the wrong tool** — Apple Sidecar is for using an iPad as a second display, not for cross-machine file/data discovery. SSH (already configured) is the right path.

**Discovery script** (`~/Cornelius/resources/brain-graph/discover_remote_vaults.sh`) is already written + executable. Pass alias as arg:
```bash
./discover_remote_vaults.sh studio          # LAN-direct (try first)
./discover_remote_vaults.sh studio-ts       # Tailscale fallback
```

The script: validates Tailscale state (not required if using `studio` LAN), runs `ssh <alias> 'find ... -name .obsidian'` + Cornelius-schema detection, returns NDJSON, merges into `~/Desktop/Brain/05-Meta/vaults-registry.json` via `jq` with `host`, `tailscale_name`, `last_seen`, `reachable_now` fields.

---

## Execution — Two Agent Teams

### Team A: Vault Consolidator (one-time, ~20 min)

Lower-tier OK per Erich. Haiku for grunt file ops, Sonnet for verifier reasoning.

| Agent | Tier | Job | Verification |
|---|---|---|---|
| Cornelius-Brain Trasher | Haiku | `mv ~/Cornelius/Brain ~/.Trash/cornelius-brain-stale-2026-05-13/` | `[[ ! -e ~/Cornelius/Brain ]]` |
| loriann-wiki Trasher | Haiku | `mv ~/loriann_local_wiki ~/.Trash/loriann-local-wiki-2026-05-13/` | `[[ ! -e ~/loriann_local_wiki ]]` |
| AI-CONSULTING Mover | Haiku | `mkdir -p ~/Desktop/Brain/04-Output/projects/ && mv ~/Documents/AI\ CONSULTING ~/Desktop/Brain/04-Output/projects/ai-consulting/` | source gone + dest has 32 md |
| Documents/Claude Mover | Haiku | `mkdir -p ~/Desktop/Brain/04-Output/projects/ && mv ~/Documents/Claude ~/Desktop/Brain/04-Output/projects/claude-artifacts/` | source gone + dest has 36 md |
| NIKLAS De-pollution | Haiku | Inventory 271k auto-gen files → trash to `~/.Trash/niklas-depollute-2026-05-13/`. Add `~/Desktop/NIKLAS/READONLY.md` marker. | Pollution counts both = 0 post-run |
| Registry Updater | Sonnet | Update `~/Desktop/Brain/05-Meta/vaults-registry.json` with new state: AI CONSULTING + Claude inside Brain, WHISKEY 2 paths added as `host=local-whiskey2`, JIMMY/BERT/BERT-Wiki stay `kind=project`, deleted entries removed, ARC marked `excluded` | JSON validates, vault count = 11 (was 14: -3 trashed + AI CONSULTING/Claude folded) |
| Remote Discovery | Sonnet | `./discover_remote_vaults.sh studio` (LAN first; `studio-ts` fallback if LAN fails). Merges remote vaults into registry. | At least 1 remote vault appears with `host: studio` |
| Verifier | Sonnet | Post-Team-A sanity sweep: Brain still bootstraps, registry valid JSON, no source paths still exist for moved vaults, Trash items recoverable for 30d. | All checks green |

Dependency order:
```
Trashers run in parallel (Cornelius/Brain, loriann) — no dependencies
Movers run in parallel (AI CONSULTING, Claude) — no dependencies
NIKLAS De-pollution runs in parallel — no dependencies
Registry Updater runs AFTER trashers + movers (depends on final state)
Remote Discovery runs AFTER Registry Updater (appends to fresh state)
Verifier runs LAST
```

### Team B: Semantic Enrichment Orchestrator (continuous, runs after Phase F load)

This is the "team of agents creating semantic relationships at massive scale" that was missing. Build the orchestrator now; first pass fires once Neo4j is loaded.

**Files to create**:
- `~/Cornelius/resources/brain-graph/enrichment/orchestrator.py` — main loop
- `~/Cornelius/resources/brain-graph/enrichment/prompts.py` — edge-proposal prompt template
- `~/Cornelius/resources/brain-graph/enrichment/queue.py` — SQLite work queue
- `~/Cornelius/resources/brain-graph/enrichment/agent_pool.py` — 20-parallel Anthropic API client

**Agent roles** (already designed in the GraphRAG roadmap review — re-stated here):

| Role | Tier | Concurrency | Job |
|---|---|---|---|
| Queue Builder | Haiku | 1 | Walk all atoms in `data/graph_enrichments.json`. Enqueue into SQLite in batches of 50. Skip already-enriched (content_hash match). |
| Vector Pre-Filter | Haiku | 1 | For each batch, query LBS FAISS for top-20 vector neighbors per anchor. Attach neighbor IDs to queue row. |
| Edge Inference Agent (×20) | Sonnet | 20 parallel | Read `(anchor_atom, 20 neighbors)` batch. LLM prompt: "Propose 0..k typed edges with confidence + rationale." Output JSON: `[{target, edge_type ∈ {MENTIONS, DERIVES_FROM, RELATED_TO, CONTRADICTS, SUPERSEDES, EXTENDS}, direction, confidence, rationale}]`. |
| Consensus Agent | Sonnet | 1 | Dedupe + score: high-conf (≥0.85 + ≥2 agents agree) → auto-commit. Mid-conf (0.6-0.85) → review queue. Low-conf (<0.6) → discard. |
| Auto-Commit Agent | Haiku | 1 | MERGE high-conf edges into Neo4j (via export_to_cypher pattern). Write to SQLite audit log. |
| Review Queue Writer | Haiku | 1 | Mid-conf proposals → `~/Desktop/Brain/_outputs/edge-review/{date}.md` for human approval. |
| Edge Validator | Opus | 1 (sample) | Sample 200 committed edges; score precision; flag if <90%. |

**Output state**: `data/proposed_edges.jsonl` (queue), `data/edge_audit.db` (SQLite history), `_outputs/edge-review/` (human review markdown).

**Idempotency**: Every proposed edge has deterministic ID `sha1(from_id + "→" + edge_type + "→" + to_id)`. Re-runs are safe.

**First-pass cost** (5,411 atoms × 20 neighbors = ~108k pairwise checks; batched into 5,411/50 ≈ 110 batches): ~$40-80 single-pass per /autoplan estimate. No cap per user.

**Build now, run later**: Orchestrator + queue can be built without Docker/Neo4j (writes to JSONL + SQLite). Auto-Commit Agent waits for Neo4j to come up; queues all proposed edges meanwhile.

---

## Pre-flight Actions (user-blocking)

| # | Action | Who | Why |
|---|--------|-----|-----|
| 1 | Open Docker Desktop | **User** | Neo4j load + MCP server live testing |
| 2 | Open Tailscale.app + log in | **User** | Off-LAN access to Mac Studio (Plan B; LAN-direct works without this) |
| 3 | Set `NEO4J_PASS` in `~/Cornelius/resources/brain-graph/.env` | **User** | Generated by `openssl rand -base64 24`; copy template via `cp .env.example .env` |
| 4 | Confirm `ssh studio echo ok` works | **User OR Verifier agent** | LAN reachability sanity check |

Once 1, 3 done: Team A + Phase F load run. Once 4 confirms: Remote Discovery agent runs.

---

## Files to Create / Modify

### Create (new code)
- `~/Cornelius/resources/brain-graph/enrichment/orchestrator.py` — main enrichment loop
- `~/Cornelius/resources/brain-graph/enrichment/prompts.py` — edge proposal prompts
- `~/Cornelius/resources/brain-graph/enrichment/queue.py` — SQLite queue + dedupe
- `~/Cornelius/resources/brain-graph/enrichment/agent_pool.py` — 20-parallel Anthropic client
- `~/Cornelius/resources/brain-graph/enrichment/__init__.py`
- `~/Cornelius/resources/brain-graph/enrichment/test_orchestrator.py` — unit tests for queue + dedupe + consensus
- `~/Cornelius/resources/brain-graph/team_a_consolidate.sh` — orchestrates the 8-agent Team A (or invokes them via Task tool from a Claude Code session)

### Modify
- `~/Desktop/Brain/05-Meta/vaults-registry.json` — final state per verdict table
- `~/Desktop/NIKLAS/READONLY.md` — new marker file (frozen state)

### Reference / Reuse (no changes needed)
- `~/Cornelius/resources/brain-graph/discover_remote_vaults.sh` — already built
- `~/Cornelius/resources/brain-graph/export_to_cypher.py` — already built, 13/13 tests
- `~/Cornelius/resources/brain-graph/mcp_server.py` — already built
- `~/Cornelius/resources/brain-graph/sdk/zeus_brain/` — already built
- `~/Cornelius/resources/brain-graph/load_neo4j.sh` — already built
- `~/Cornelius/resources/brain-graph/store.py` — atomic-write fix applied
- `~/Cornelius/resources/brain-graph/cli.py` — `export-json` subcommand applied
- `~/Cornelius/resources/brain-graph/docker-compose.neo4j.yml` — env-var creds applied
- `~/Cornelius/resources/local-brain-search/run_search.sh` — shell-injection fix applied

---

## Verification

After Team A executes:

```bash
# 1. Trashed items are in Trash (recoverable)
ls -la ~/.Trash/ | grep -E "cornelius-brain-stale|loriann-local-wiki|niklas-depollute" | head -5

# 2. Moved items are inside Brain
ls ~/Desktop/Brain/04-Output/projects/ai-consulting/ | head -3
ls ~/Desktop/Brain/04-Output/projects/claude-artifacts/ | head -3

# 3. Source paths gone
[ ! -e ~/Documents/AI\ CONSULTING ] && echo "AI CONSULTING moved OK"
[ ! -e ~/Documents/Claude ] && echo "Claude moved OK"
[ ! -e ~/Cornelius/Brain ] && echo "Cornelius/Brain trashed OK"
[ ! -e ~/loriann_local_wiki ] && echo "loriann trashed OK"

# 4. NIKLAS pollution gone
find ~/Desktop/NIKLAS -name "__folder__.md" 2>/dev/null | wc -l   # expect 0
[ -f ~/Desktop/NIKLAS/READONLY.md ] && echo "NIKLAS frozen"

# 5. Registry up to date
python3 -c "import json; d=json.load(open('/Users/erichroepke/Desktop/Brain/05-Meta/vaults-registry.json')); print(f'vault_count={d[\"vault_count\"]}, status={d.get(\"status\")}')"

# 6. Brain still bootstraps cleanly after Brain content changes
cd ~/Cornelius/resources/brain-graph && ./run_brain_graph.sh bootstrap

# 7. Remote discovery succeeded
jq '.vaults | map(select(.host == "studio")) | length' ~/Desktop/Brain/05-Meta/vaults-registry.json
```

After Team B first pass (post Phase F load):

```bash
# 8. Proposed edges queued
wc -l ~/Cornelius/resources/brain-graph/data/proposed_edges.jsonl
# expect many thousands

# 9. High-confidence edges committed to Neo4j
docker exec zeus-brain-neo4j cypher-shell -u neo4j -p "$NEO4J_PASS" \
  "MATCH ()-[r:MENTIONS|DERIVES_FROM|RELATED_TO|CONTRADICTS|SUPERSEDES|EXTENDS]->() RETURN type(r), count(*) ORDER BY count(*) DESC"
# expect non-zero per relationship type

# 10. Review queue populated
ls ~/Desktop/Brain/_outputs/edge-review/ | head -5

# 11. Edge validator precision
cat ~/Cornelius/resources/brain-graph/data/edge_audit.db | sqlite3 "SELECT AVG(precision) FROM validation_samples"
# expect >= 0.90
```

---

## Out of Scope (Explicit)

- **Sidecar / display-mirroring tools** — wrong category; SSH/Tailscale already configured
- **Trinity Docker stack** — deferred per /autoplan premise gate (not needed for current scope)
- **1-2026_ARC indexing** — Erich said skip
- **Bidirectional MD↔Neo4j sync** — unidirectional v1 per /autoplan taste decision
- **Physically moving WHISKEY 2 content** — 1.4 TB; index-only
- **Apple Notes ingestion** — SQLite, not markdown; separate sprint if ever
- **Cornelius/Brain backup-keep alternative** — Erich said trash

---

## Sequence (one-shot ready)

```
Pre-flight (USER)
  ├─ Open Docker Desktop
  ├─ Copy .env.example → .env + edit NEO4J_PASS
  └─ (Optional) Open Tailscale.app

Team A (parallel where possible)
  ├─ Trashers (Cornelius/Brain, loriann)         [parallel]
  ├─ Movers (AI CONSULTING, Claude)              [parallel]
  ├─ NIKLAS De-pollution                          [parallel]
  ├─ Registry Updater                             (after trashers + movers)
  ├─ Remote Discovery (ssh studio)                (after Registry Updater)
  └─ Verifier                                     (last)

Phase F load
  ├─ docker compose -f docker-compose.neo4j.yml up -d
  ├─ ./load_neo4j.sh                              (5,411 nodes + 62,137 structural edges)
  ├─ Verify in Neo4j browser
  └─ Add zeus-brain MCP via `claude mcp add`

Team B first pass (semantic enrichment, ~4-8h wall, runs in background)
  ├─ Build orchestrator + queue (~1h CC, no deps on Neo4j)
  ├─ Queue Builder + Vector Pre-Filter walk Brain (~5 min)
  ├─ 20 Edge Inference Agents propose edges (~4-8h)
  ├─ Consensus + Auto-Commit fill Neo4j with semantic edges
  └─ Edge Validator samples + reports precision
```

Post-execution Brain has: 5,411 atoms + ~100k+ semantic edges + multi-machine origin tracking + protected MCP queryable from any project.

---

# Vault Organization Cleanup v2.1 — Brain to Cornelius-Canonical

**Date appended:** 2026-05-13 (after Phase F load completed successfully)
**Scope:** restructure `~/Desktop/Brain/` SUB-folders to match Cornelius canonical layout per `~/Cornelius/FOLDER-STRUCTURE.md`. Top-level numbered prefixes (`00-`, `01-`, ...) STAY per Erich (5,411 atom paths depend on them).

## Why this section was added

After Phase F Neo4j load (5,411 atoms + 62,137 edges live), Erich showed me a screenshot of a vault he called "a total mess" and asked for a "team of agents to come up with a structure." The screenshot was NIKLAS (frozen legacy), not Brain — but Erich's direction stands: clean up Brain anyway so it more closely matches Cornelius's canonical `FOLDER-STRUCTURE.md` template.

## What's actually messy vs clean (post-Phase-F state)

| Layer | Current | Cornelius canonical sub-folders | Gap |
|---|---|---|---|
| `00-Inbox/` (13 md) | flat | `Quick Captures/`, `Content Extractions/`, `To Process/` | needs 3 sub-folders + audit existing into them |
| `01-Sources/` (886 md) | flat | `Books/`, `Articles/`, `Videos/`, `Podcasts/` | needs 4 sub-folders + audit existing into them (likely 50+ source notes to triage by type) |
| `02-Permanent/` (4,382 md) | flat | flat (per canonical — "all atomic notes") | ✅ matches canonical |
| `03-MOCs/` (34 md) | flat | flat with `MOC - Master Navigation.md` index | ✅ structure ok; check for missing Master Navigation |
| `04-Output/` (128 md) | has `projects/{ai-consulting,claude-artifacts}/` (from Team A) | `Articles/`, `Frameworks/`, `Insights/`, `Projects/` | needs `Articles/`, `Frameworks/`, `Insights/` (Projects already there) |
| `05-Meta/` (4 md) | `Changelogs/`, `Parts/`, `Templates/` | `Changelogs/`, `Templates/`, `Workflows/` | needs `Workflows/`; `Parts/` is Brain-specific (keep) |
| `06-Belief-System/` (0 md) | `.gitkeep` only | not in canonical | **decide: fill or trash** |
| `08-Meta-Cognitive/` (0 md) | `.gitkeep` only | not in canonical | **decide: fill or trash** |
| `AI Extracted Notes/` (0 md) | empty | canonical | ✅ canonical empty state is fine |
| `Document Insights/` (78 md) | `parameter-golf/` subdir | canonical (separate provenance for external docs) | ✅ canonical with real content |
| Root files | `.gitignore`, `CHANGELOG.md`, `README.md` | system files | ✅ |

## Cleanup verdicts (per-folder)

| Folder | Verdict | Reason |
|---|---|---|
| `00-Inbox/` | **Restructure** | Create `Quick Captures/`, `Content Extractions/`, `To Process/`; audit 13 existing md into them (likely all "Quick Captures" since they're loose) |
| `01-Sources/` | **Restructure (largest job)** | Create `Books/`, `Articles/`, `Videos/`, `Podcasts/`; audit 886 source notes by frontmatter `type:` field — this is the heaviest agent work |
| `02-Permanent/` | **Leave alone** | Cornelius says "all atomic notes" flat — match. 4,382 atoms with established wikilinks. |
| `03-MOCs/` | **Audit + add Master Navigation if missing** | Cornelius wants `MOC - Master Navigation.md` as top-level index |
| `04-Output/` | **Add sub-folders** | Create `Articles/`, `Frameworks/`, `Insights/` next to existing `projects/` |
| `05-Meta/` | **Add `Workflows/` sub-folder** | Keep existing `Changelogs/`, `Parts/`, `Templates/` |
| `06-Belief-System/` | **TRASH** (empty + non-canonical) | `.gitkeep`-only placeholder; not in Cornelius canonical |
| `08-Meta-Cognitive/` | **TRASH** (empty + non-canonical) | Same as above |
| `AI Extracted Notes/` | **Keep** | Canonical Cornelius layer; currently empty is fine (waiting for `extract-insights` skill output) |
| `Document Insights/` | **Keep** | Canonical Cornelius extension; 78 md across `parameter-golf/` subdir |

## Team C: Vault Cleanup Crew (6 agents)

Per Erich rule "agent teams are the DEFAULT for ANY bulk operation":

| # | Agent | Tier | Job | Verification |
|---|---|---|---|---|
| 1 | **Inventory Agent** | Haiku | Walk Brain layer by layer (00→05). For each `.md`, read frontmatter `type:` + `tags:` + folder hints. Output: `_outputs/cleanup-inventory-2026-05-13.json` with proposed sub-folder destination per file. | JSON validates, every md has a verdict |
| 2 | **Decider Agent** | Sonnet | Read inventory. For each AMBIGUOUS file (no clear frontmatter type), classify based on filename + body sample. Cross-references Cornelius FOLDER-STRUCTURE.md. Output: `_outputs/cleanup-decisions-2026-05-13.json` (final dest per file). | All decisions logged with rationale; no "?" left |
| 3 | **Mover Agent** | Haiku | Create new sub-folders under each layer per decisions. `mv` files into their decided sub-folder. Update wikilinks if filename changes (no rename, just relocate — wikilinks resolve via slug, not path, so no rewrites needed). | All source paths gone, dest paths populated |
| 4 | **Empty-Folder Trasher** | Haiku | Move `06-Belief-System/` + `08-Meta-Cognitive/` to `~/.Trash/brain-empty-placeholders-2026-05-13/`. | Both gone from Brain; recoverable from Trash |
| 5 | **Doc Writer** | Sonnet | For each layer (00-05), write or refresh `README.md` documenting the canonical Cornelius structure + Brain-specific customizations. Add `MOC - Master Navigation.md` to `03-MOCs/` if missing. | 6 layer READMEs exist + 1 Master Navigation MOC |
| 6 | **Verifier + Neo4j Re-loader** | Sonnet | Re-run `./run_brain_graph.sh bootstrap` (re-classifies relocated atoms). Re-export to Cypher. Re-load Neo4j. Compare atom + edge counts to pre-cleanup (should be unchanged — only PATHS moved, not content). | atom_count = 5,411 ± 0; edge_count = 62,137 ± 0; git status clean |

**Dependency order:**
```
Inventory (1)
    │
    ▼
Decider (2)              Empty-Folder Trasher (4) [parallel — no deps]
    │
    ▼
Mover (3)                Doc Writer (5) [parallel — independent of moves]
    │                            │
    ▼                            ▼
        Verifier + Neo4j Re-loader (6)
```

**Wall clock estimate:** ~30-60 min (Sonnet decider over 886 source notes is the bottleneck).
**Cost estimate:** ~$2-5 (Haiku for grunt, Sonnet for decisions, Opus only if Verifier hits issues).

## Constraints — Iron Laws

- **Move to Trash, NEVER delete** (per Erich rule).
- **No file renames** (per memory: "Only rename when absolutely positive"). Files are RELOCATED to sub-folders, filenames preserved. Wikilinks resolve by slug — no rewrites needed.
- **02-Permanent stays FLAT** — per canonical Cornelius. Do NOT add `Frameworks/` sub-folder inside; that's what `04-Output/Frameworks/` is for.
- **Git commit after each agent succeeds** so cleanup is bisectable and revertable.
- **Pre-cleanup snapshot**: `cp -R ~/Desktop/Brain ~/Desktop/Brain.pre-cleanup-2026-05-13` BEFORE Team C runs. Cleanup is reversible at the directory level.

## Critical files

### Reuse (no changes needed)
- `~/Cornelius/FOLDER-STRUCTURE.md` — canonical Cornelius spec (the target structure)
- `~/Cornelius/EXAMPLES.md` — sample frontmatter shapes (helps Decider Agent classify)
- `~/Cornelius/resources/brain-graph/{run_brain_graph.sh, load_neo4j.sh, export_to_cypher.py}` — already built; Verifier Agent invokes these

### Create
- `~/Desktop/Brain/_outputs/cleanup-inventory-2026-05-13.json` — Inventory Agent output
- `~/Desktop/Brain/_outputs/cleanup-decisions-2026-05-13.json` — Decider Agent output
- `~/Desktop/Brain/00-Inbox/{Quick Captures,Content Extractions,To Process}/` — new sub-folders
- `~/Desktop/Brain/01-Sources/{Books,Articles,Videos,Podcasts}/` — new sub-folders
- `~/Desktop/Brain/04-Output/{Articles,Frameworks,Insights}/` — new sub-folders (Projects already there)
- `~/Desktop/Brain/05-Meta/Workflows/` — new sub-folder
- `~/Desktop/Brain/03-MOCs/MOC - Master Navigation.md` — top-level navigation index
- `~/Desktop/Brain/0{0..5}-*/README.md` — 6 layer READMEs

### Trash
- `~/Desktop/Brain/06-Belief-System/` → `~/.Trash/brain-empty-placeholders-2026-05-13/`
- `~/Desktop/Brain/08-Meta-Cognitive/` → same destination

## Verification (after Team C completes)

```bash
# Layer structure matches canonical Cornelius + Brain customizations
ls ~/Desktop/Brain/00-Inbox/    # expect: Quick\ Captures, Content\ Extractions, To\ Process, *.md
ls ~/Desktop/Brain/01-Sources/  # expect: Books, Articles, Videos, Podcasts, *.md
ls ~/Desktop/Brain/04-Output/   # expect: Articles, Frameworks, Insights, projects
ls ~/Desktop/Brain/05-Meta/     # expect: Changelogs, Parts, Templates, Workflows

# Atom + edge counts unchanged (paths moved, content preserved)
cd ~/Cornelius/resources/brain-graph && ./run_brain_graph.sh status
# expect: 5,411 atoms, 62,137 edges (same as pre-cleanup)

# Neo4j re-loaded with new paths
docker exec zeus-brain-neo4j cypher-shell -u neo4j -p "$BRAIN_NEO4J_PASS" \
  "MATCH (n:Atom) RETURN count(n)"
# expect: 5,411

# Git status clean
cd ~/Desktop/Brain && git status

# Trash recoverable
ls ~/.Trash/brain-empty-placeholders-2026-05-13/
```

## Out of scope (NOT in v2.1)

- Renaming `00-Inbox` → `Inbox` (Erich locked: keep numbered prefixes)
- Restructuring `02-Permanent/` into sub-folders (Cornelius canonical = flat)
- Moving `Document Insights/` (canonical, has real content)
- Cleaning up NIKLAS (frozen per READONLY.md; no value-add)
- Cleaning up project vaults (BERT, etc — separate concern, indexed only via Neo4j)

---

# Vault Restructure v2.2 — raw + wiki Two-Tier (SUPERSEDES v2.1 layout)

**Date appended:** 2026-05-13 (after Team C sub-folder moves landed but before final Neo4j re-sync)
**Reverses:** v2.1's "keep numbered prefixes" decision. User explicitly chose physical restructure into 2-tier raw + wiki shape after seeing the post-cleanup state.

## Why this section exists

After v2.1's sub-folder moves landed (509 atoms relocated; Sessions/, Books/, Articles/, etc. populated), Erich rethought the top-level: "It has to go back to the original Obsidian-like Claude thing. There's a raw format for items not yet ingested, and everything indexed after that. Index itself = two things: inbox (or raw) and wiki (knowledge base)... Output should be a subfolder of the wiki... once something is output, it should automatically go into inbox and then get sorted back into the wiki."

The v2.1 numbered-prefix layout (`00-Inbox`, `01-Sources`, ...) doesn't capture that. The cleanest expression of the mental model is two top-level folders: `raw/` and `wiki/`.

## Target layout (Brain post-v2.2)

```
~/Desktop/Brain/
├── raw/                        ← was 00-Inbox; unindexed catch-all
│   ├── Quick Captures/
│   ├── Content Extractions/
│   ├── To Process/
│   ├── zeus-wiki-conflicts/    (pre-existing sub-dir, preserved)
│   ├── zeus-wiki-untyped/      (pre-existing sub-dir, preserved)
│   └── README.md
│
├── wiki/                       ← indexed knowledge base (BDG-bootstrappable)
│   ├── Sources/                ← was 01-Sources
│   │   ├── Articles/
│   │   ├── BERT-Wiki/
│   │   ├── Books/
│   │   ├── Experts/
│   │   ├── Podcasts/
│   │   ├── Sessions/           (498 session-captures)
│   │   ├── Videos/
│   │   └── [383 root .md files]
│   ├── Permanent/              ← was 02-Permanent (4,382 atoms, flat)
│   ├── MOCs/                   ← was 03-MOCs (34 MOCs)
│   ├── Output/                 ← was 04-Output, NOW INSIDE wiki/
│   │   ├── Articles/
│   │   ├── Frameworks/
│   │   ├── Insights/
│   │   ├── Syntheses/
│   │   └── projects/
│   │       ├── ai-consulting/
│   │       └── claude-artifacts/
│   ├── Meta/                   ← was 05-Meta
│   │   ├── _outputs/
│   │   ├── Changelogs/
│   │   ├── file-contexts/
│   │   ├── folder-guides/
│   │   ├── Parts/
│   │   ├── Templates/
│   │   └── Workflows/
│   ├── AI Extracted Notes/     ← was top-level
│   └── Document Insights/      ← was top-level
│
├── .git/
├── .gitignore
├── CHANGELOG.md
└── README.md
```

**Top-level becomes 2 folders + 4 root files.** Two-tier semantic: raw = unindexed, wiki = everything indexed.

## Output recycle policy

Per user: "Once something is output, it should automatically go into inbox and then get sorted back into the wiki."

Interpretation (implemented as daily-routine policy, NOT a folder change):
1. When the daily routine sees a new file in `wiki/Output/`, it places a `.recycle.json` pointer in `raw/Content Extractions/` referencing the output for re-evaluation.
2. The pointer says: "this output should be re-analyzed for atom extraction." Daily routine's `/extract-insights` pass will produce new permanent atoms in `wiki/Permanent/`.
3. Output files themselves stay in `wiki/Output/` (not moved). The recycle is an INDEXING signal, not a physical move.

This preserves provenance (output stays where written) while triggering re-ingestion. Acyclic in practice: outputs cycle once through extraction; resulting atoms are new, not edits.

## Execution — Team D: Top-Level Restructure (5 agents)

| # | Agent | Tier | Job | Verification |
|---|---|---|---|---|
| 1 | **Mover Agent** | Haiku | Atomic same-volume moves: `mv 00-Inbox raw/` + `mkdir wiki/` + `mv 01-Sources wiki/Sources/` + `mv 02-Permanent wiki/Permanent/` + `mv 03-MOCs wiki/MOCs/` + `mv 04-Output wiki/Output/` + `mv 05-Meta wiki/Meta/` + `mv "AI Extracted Notes" wiki/` + `mv "Document Insights" wiki/`. Single transaction. | 2 top-level dirs (raw, wiki) + 4 root files exist; all 9 source paths gone |
| 2 | **Cornelius config patcher** | Haiku | Update `~/Cornelius/.claude/settings.md` if it references `02-Permanent/` etc. (likely it references `VAULT_BASE_PATH` only; no per-folder paths). Confirm via grep. | grep -r "02-Permanent\|00-Inbox" ~/Cornelius/.claude/ returns 0 hits |
| 3 | **BDG re-bootstrap (--force)** | Sonnet | `./run_brain_graph.sh bootstrap --force` to re-classify EVERY atom with new vault-relative paths. Required because classify.py uses path-prefix matching (`01-Sources/` → Signal, `02-Permanent/` → Insight) — new path structure means re-classification with updated yaml. May need brain_graph_config.yaml update (vault_paths fields). | data/graph_enrichments.json regenerated with paths starting `wiki/Permanent/`, `wiki/Sources/`, `raw/`, etc. atom_count = 5,411 |
| 4 | **Neo4j re-sync** | Haiku | DETACH DELETE all atoms in Neo4j; re-export sidecar to Cypher; reload. Cypher load takes ~3-4 min for 67k MERGE statements. | atom count = 5,411; 4 edge types present with same counts (REFERENCES 37,896 / DERIVES_FROM 8,350 / INSTANTIATES 8,216 / ASSOCIATES 7,675) |
| 5 | **README writer** | Sonnet | Write `Brain/README.md` (overview), `Brain/raw/README.md` (what raw contains + how daily routine processes it), `Brain/wiki/README.md` (layers + canonical structure). Reference user's mental model: raw = unindexed, wiki = indexed. | 3 READMEs exist, each <1KB and human-readable |

**Dependency order:**
```
Mover (1)
    │
    ▼
Cornelius config patcher (2)         README writer (5) [parallel — no atom deps]
    │
    ▼
BDG re-bootstrap --force (3)
    │
    ▼
Neo4j re-sync (4)
```

**Wall clock estimate:** ~10 min (Neo4j reload dominates).
**Risk:** BDG's `brain_graph_config.yaml` references vault_paths like `01-Sources/`. Need to update those to `wiki/Sources/`, `wiki/Permanent/`, etc., or BDG re-bootstrap classifies everything as the default "insight" layer. Mover Agent or Patcher Agent handles config alongside moves.

## Daily Routine — Team E (PARALLEL build, separate concern)

Per user: "create a series of routines within Claude to organize this wiki once a day. Anything in RAW would be wicked — anywhere on the hard drive."

The daily-routine background agent has already written 4 of 9 deliverables (paused mid-stream when plan mode re-entered):

**Already on disk** (per agent's report):
- `~/Cornelius/resources/brain-graph/daily/__init__.py`
- `~/Cornelius/resources/brain-graph/daily/sweeper.py` — INVENTORY SWEEPER: walks ~/Desktop, ~/Documents, ~/Downloads, all Inbox/ dirs; md5+mtime+size diff in `data/raw-inventory.last.json`
- `~/Cornelius/resources/brain-graph/daily/router.py` — ROUTER: classifies new files (extension + frontmatter + session heuristics)
- `~/Cornelius/resources/brain-graph/daily/processor.py` — PROCESSOR: `claude -p` headless invocation of Cornelius `/extract-insights` + `/extract-document-insights`; SQLite audit
- `~/Cornelius/resources/brain-graph/daily/enricher.py` — ENRICHER: delegates to `run_brain_graph.sh` + `load_neo4j.sh`

**Blocked by plan-mode entry, ready to write on approval:**
- `~/Cornelius/resources/brain-graph/daily/digest.py` — DAILY DIGEST: writes `wiki/Meta/Changelogs/daily-YYYY-MM-DD.md`
- `~/Cornelius/resources/brain-graph/daily/cli.py` — `python -m daily.cli run [--dry-run]` + `rollback` subcommand
- `~/Cornelius/resources/brain-graph/daily/test_daily.py` — 10+ pytest unit tests
- `~/Cornelius/resources/brain-graph/daily/README.md`
- `~/Library/LaunchAgents/com.zeus-brain.daily-ingest.plist` — 6am daily trigger

**Critical design decisions already baked in by agent** (per its report):
- Idempotent via md5+mtime+size state
- NEVER auto-touches `wiki/Permanent/` (formerly `02-Permanent/`) — all auto-routing lands in `raw/*` or `wiki/AI Extracted Notes/`
- `rm` forbidden — rollback uses `mv ~/.Trash/`
- TCC-safe writes via `/bin/zsh -c cp` subprocess
- $5/day default budget cap, `--max-cost-cents` flag
- SQLite audit at `data/daily_audit.db`

**Open paths to update** in the partial files (because v2.2 changed structure):
- `daily/router.py` destination mapping: `00-Inbox/Quick Captures` → `raw/Quick Captures`; `01-Sources/Books` → `wiki/Sources/Books`; etc.
- `daily/sweeper.py` scan roots: add the v2.2 paths to scan-ignore (Brain itself shouldn't be a scan source — only its `raw/` would receive)

## Critical files

### To CREATE / MODIFY (post-restructure)
- `Brain/README.md`, `Brain/raw/README.md`, `Brain/wiki/README.md` — Team D #5
- `~/Cornelius/resources/brain-graph/brain_graph_config.yaml` — update `vault_paths` lists to new wiki/ prefixes
- `~/Cornelius/resources/brain-graph/daily/{digest,cli,test_daily}.py` + `daily/README.md` + plist — Team E
- `~/Cornelius/resources/brain-graph/daily/router.py` — path mapping updates after restructure

### To REUSE (no changes)
- `~/Cornelius/resources/brain-graph/run_brain_graph.sh` — accepts `bootstrap --force`
- `~/Cornelius/resources/brain-graph/load_neo4j.sh` — same as before
- `~/Cornelius/resources/brain-graph/export_to_cypher.py` — path-agnostic
- `~/Cornelius/CLAUDE.md` + `FOLDER-STRUCTURE.md` — reference docs (no edits)
- LBS FAISS index — needs re-index after restructure (paths change)

### Pre-restructure snapshot
- `~/Desktop/Brain.pre-cleanup-2026-05-13/` — already taken; rollback to this is `mv ~/Desktop/Brain ~/.Trash/brain-restructure-failed-{ts}/ && mv ~/Desktop/Brain.pre-cleanup-2026-05-13 ~/Desktop/Brain`

## Verification (after Team D + E)

```bash
# 1. Two top-level folders + 4 root files
ls ~/Desktop/Brain/
# expect: raw  wiki  .git  .gitignore  CHANGELOG.md  README.md

# 2. wiki/ has 6 sub-dirs + 2 ex-top-level
ls ~/Desktop/Brain/wiki/
# expect: Sources  Permanent  MOCs  Output  Meta  AI Extracted Notes  Document Insights

# 3. Atom + edge counts unchanged after re-bootstrap + reload
cd ~/Cornelius/resources/brain-graph && ./run_brain_graph.sh status
# expect: 5,411 atoms, 62,137 edges

# 4. Neo4j paths reflect new structure
docker exec zeus-brain-neo4j cypher-shell -u neo4j -p "$BRAIN_NEO4J_PASS" \
  "MATCH (n:Atom) WHERE n.id STARTS WITH 'wiki/' RETURN count(n)"
# expect: 5,411 (all atoms now under wiki/ prefix)

# 5. Daily routine smoke
python -m daily.cli run --dry-run
# expect: identifies any new files in scan roots; reports proposed routing; writes no changes

# 6. launchd job installed (after Erich launchctl loads it)
launchctl list | grep zeus-brain.daily-ingest
```

## Out of scope (v2.2)

- Updating wikilinks in atom bodies — Obsidian resolves by slug, not path; no rewrites needed
- Renaming Cornelius/Brain template (already trashed)
- Touching NIKLAS (frozen)
- Migrating to a NEW knowledge graph schema — BDG schema unchanged; only paths change

---

# v3 Studio Integration — Multi-Machine Brain (ACTIVE)

**Date:** 2026-05-16
**Trigger:** Mac Studio is now reachable via LAN. Studio has 6.5GB NIKLAS vault (1,309 active atoms, last touched May 11), an attached 80TB ANEP_RAID (active Unpacking documentary production), a 140TB year-organized MASTER archive, brothersrfilms drive, and full Claude Code installation. Erich wants Brain queryable from Studio, Studio running its own ingestion routine, and Studio's content (footage, files, projects) flowing into the unified Brain graph.

## Context

Today's session (2026-05-15→16) closed the laptop-side Brain build: Phase F live, daily routine activated with $1 cap, 5,609 atoms in Neo4j with 32+103=135 semantic edges from Team B three passes. Now the multi-machine work that the v2 plan deferred. Recon report (`wiki/Meta/_outputs/mac-studio-recon-2026-05-16.md`) confirmed Pattern C — Federated MCP — as the right architecture. Studio NIKLAS rsynced to laptop staging (~/Desktop/NIKLAS-from-studio-2026-05-16/, 4.1GB transferred, 1,309 real atoms inside 1.6M file count due to old auto-gen pollution). User-confirmed integration decisions:

- **Scope:** ALL Studio content — NIKLAS + ANEP_RAID NIKLAS_RAW (3.2GB) + MASTER 140TB .md project archives + brothersrfilms/holdmyleg (after inventory).
- **Obsidian on Studio:** Daily rsync replica (laptop pushes Brain to Studio nightly; Studio reads local copy in Obsidian).
- **Studio pipeline:** Studio runs PARALLEL daily routine. Sweeps Studio's drives, processes via Cornelius skills locally, pushes resulting atoms to laptop Brain via MCP write endpoint.

## Pre-flight state (done before plan)

| Item | State |
|---|---|
| Mac Studio reachable | LAN-direct via `ssh studio` (Tailscale NOT installed yet) |
| Recon report | `wiki/Meta/_outputs/mac-studio-recon-2026-05-16.md` (8/10 PASS, 2 disk-health warns) |
| Studio NIKLAS staging | `~/Desktop/NIKLAS-from-studio-2026-05-16/` (6.5GB rsync, 1,309 atoms + 266K pollution to filter) |
| Studio environment | Claude Code installed via Homebrew, Zeus structure in `~/.claude/`, Python 3.9.6 (needs 3.11+ for Cornelius), no Docker, no Neo4j |
| Studio disk pressure | Internal 94% full (57GB free), MASTER 140 TB 1 at 99.3% (1TB free), ANEP at 86% |
| Laptop MCP server | Built (`~/Cornelius/resources/brain-graph/mcp_server.py`) bound to localhost only |

## Phases

### Phase 1: Merge Studio NIKLAS into laptop Brain (queued — agent dispatch)

Studio NIKLAS at `~/Desktop/NIKLAS-from-studio-2026-05-16/` has 1,309 real atoms wrapped in 266K `__folder__.md` + 2.4K `__init__.py.md` auto-gen pollution.

**Merge agent classifies each real atom (1,309 total):**

1. **SKIP** — md5 match against existing laptop Brain atom (duplicate)
2. **INGEST** — unique, route to appropriate Brain layer:
   - `wiki/atoms/` content → `wiki/Permanent/`
   - `wiki/bundles/` (Maps of Content) → `wiki/MOCs/`
   - `wiki/concepts/`, `wiki/entities/`, `wiki/personas/`, `wiki/theories/` → `wiki/Permanent/` with type-specific tags
   - `wiki/sources/` → `wiki/Sources/`
   - `wiki/_briefings/`, `wiki/_candidates/`, `wiki/connection_reports/`, `wiki/gmail-cache/` → `wiki/Document Insights/2026-05-16 Studio NIKLAS Merge/` (session-archived)
   - Studio's `Brain/` (old numbered prefix) — only 3 stubs, skip or merge to `wiki/Meta/`
3. **FLAG** — same filename or slug, different content → `wiki/Meta/_outputs/studio-merge-divergent-2026-05-16.md` review queue

Reports outcome counts. Re-bootstrap BDG + reload Neo4j after merge.

**Files touched:**
- New: `wiki/Document Insights/2026-05-16 Studio NIKLAS Merge/CHANGELOG.md`
- New: `wiki/Meta/_outputs/studio-merge-divergent-2026-05-16.md`
- Modified: BDG sidecar after bootstrap

**Expected:** ~200-400 unique atoms ingested (Studio's wiki/ has zettelkasten-specific content that may not exist in laptop's Brain).

### Phase 2: Bind MCP server to network interface

Currently `mcp_server.py` binds to `localhost:8788`. Studio can't reach it.

**Change:** Bind to `0.0.0.0:8788` (or specific LAN IP `192.168.1.X`) with bearer-token auth (already implemented in mcp_server.py per memory). Verify firewall allows port 8788 inbound from LAN.

**Files modified:**
- `~/Cornelius/resources/brain-graph/mcp_server.py` — change bind address
- `~/Cornelius/resources/brain-graph/.env` — add `MCP_BIND_HOST=0.0.0.0` env var

**Verify:** `curl -H "Authorization: Bearer $TOKEN" http://192.168.1.X:8788/health` returns 200 from Studio.

### Phase 3: Studio MCP client setup

Studio's `~/.claude/mcp.json` already has Zeus structure. Add a `zeus-brain` MCP entry pointing at laptop.

**Files modified (on Studio via ssh):**
- `studio:~/.claude.json` (top-level `mcpServers` per Erich's memory — that's the active registry)

**Entry:**
```json
{
  "zeus-brain": {
    "type": "http",
    "url": "http://192.168.1.X:8788",
    "headers": {"Authorization": "Bearer <token>"}
  }
}
```

**Verify:** `ssh studio "claude mcp list"` shows `zeus-brain`; `ssh studio "claude -p 'use zeus-brain MCP to search for bert-zeus-naming-candidates'"` returns the atom.

### Phase 4: Daily rsync replica (laptop → Studio)

One-way nightly sync of laptop's Brain to Studio for Obsidian browsing.

**Cron on laptop (or launchd):**
```bash
# /tmp/sync-brain-to-studio.sh
rsync -az --delete --exclude ".git" \
  ~/Desktop/Brain/ \
  studio:~/Desktop/Brain-replica/
```

**Schedule:** 4am MT (before laptop's daily routine at 6am, so Studio reflects last-night's state).

**Files created:**
- `~/Cornelius/resources/brain-graph/scripts/sync-brain-to-studio.sh`
- `~/Library/LaunchAgents/com.zeus-brain.sync-to-studio.plist`

**On Studio:** Open Obsidian, add `~/Desktop/Brain-replica/` as a vault. Read-only browse.

**Conflict prevention:** Studio's Obsidian DOES NOT write to Brain-replica. Any changes Erich wants to make on Studio must go through Claude Code's MCP write endpoint (Phase 7) or be done on laptop.

### Phase 5: Python 3.11+ on Studio (prerequisite for Studio's daily routine)

Studio has Python 3.9.6. Cornelius brain-graph + daily routine need 3.11+.

```bash
ssh studio "brew install python@3.11"
```

Plus: virtual env setup, install Cornelius brain-graph dependencies.

**Files created on Studio:**
- `studio:~/Cornelius/resources/local-brain-search/venv-studio/` — fresh venv with sentence-transformers + dependencies

### Phase 6: Studio's parallel daily routine

Sweeper + router + processor on Studio. Pushes atoms to laptop Brain via MCP write endpoint.

**Drives swept:**
- `~/Desktop/NIKLAS/` — POST-MERGE: skip (move to ~/.Trash/ after Phase 1 completes; Studio reads Brain-replica instead)
- `/Volumes/ANEP_RAID_1B/NIKLAS_RAW/` — active doc production raw inbox (3.2GB Obsidian content)
- `/Volumes/MASTER 140 TB/<year>/<project>/` — project archives, .md files only (NOT video)
- `/Volumes/MASTER 140 TB 1/<...>` — same, after disk-health remediation
- `/Volumes/brothersrfilms/holdmyleg/` — after content inventory in Phase 8

**Studio launchd job:**
- `~/Library/LaunchAgents/com.zeus-brain.daily-ingest-studio.plist` (mirrors laptop's plist with adjusted SCAN_ROOTS)
- Fires 6:30am MT (30 min after laptop's, so Studio sees laptop's overnight content via replica)
- $1 cost cap on first auto-fire (same as laptop)

**Studio sweeper config (new file `daily/sweeper_studio.py` or env-var override):**
```python
SCAN_ROOTS_STUDIO = [
    {"path": "/Volumes/ANEP_RAID_1B/NIKLAS_RAW", "max_depth": -1},
    {"path": "/Volumes/MASTER 140 TB", "max_depth": 3, "ext_filter": [".md"]},
    {"path": "/Volumes/MASTER 140 TB 1", "max_depth": 3, "ext_filter": [".md"]},
    {"path": "/Volumes/brothersrfilms", "max_depth": 2, "ext_filter": [".md", ".txt"]},
]
```

**Studio processor:**
- Routes new files locally on Studio
- Invokes Cornelius skills locally via `claude -p /extract-insights` (or `/extract-document-insights` for external docs)
- Generated atoms go through MCP write endpoint (Phase 7) to laptop Brain

**Audit DB on Studio:**
- `studio:~/Cornelius/resources/brain-graph/data/daily_audit_studio.db` — local audit log

**Push to laptop via MCP:**
- After processor runs, push generated atoms via `POST /atoms` on laptop's MCP server
- Receives canonical path back; Studio writes that path locally for future deduplication

### Phase 7: MCP write endpoint (laptop side)

Current MCP server is read-only. Add `POST /atoms` for Studio (and future federation peers) to push atoms.

**Endpoint:**
```
POST /atoms
Authorization: Bearer <token>
Body: {
  "vault_relative_path": "wiki/Permanent/atom-name.md",  
  "content": "...",
  "frontmatter": {...},
  "origin_machine": "studio",
  "origin_drive": "ANEP_RAID_1B",
  "origin_path": "/Volumes/ANEP_RAID_1B/NIKLAS_RAW/vyborov/file.md",
  "content_hash": "md5..."
}
Returns: {"canonical_path": "wiki/Permanent/atom-name.md", "deduplicated": false}
```

**Implementation:**
- Add tool to `mcp_server.py`
- Validates content against denylist (already exists for cypher)
- Writes to `~/Desktop/Brain/<vault_relative_path>` atomically (via store.py atomic-write pattern)
- Returns canonical path or dedup signal if md5 matches existing

**Files modified:**
- `~/Cornelius/resources/brain-graph/mcp_server.py` — add write tool
- `~/Cornelius/resources/brain-graph/test_mcp_safety.py` — add 5-10 write-endpoint tests (auth, path traversal, dedup, atomic-write, denylist)

### Phase 8: brothersrfilms / holdmyleg inventory

Unknown drive. Need scope decision before sweeper config in Phase 6.

**Recon (ssh studio):**
```bash
ssh studio 'find /Volumes/brothersrfilms -maxdepth 3 -type d | head -20'
ssh studio 'find /Volumes/brothersrfilms -type f -name "*.md" | wc -l'
ssh studio 'du -sh /Volumes/brothersrfilms/holdmyleg'
```

**Then user verdict:**
- Same project as Hold My Leg session work on laptop? → ingest under existing project label
- Separate brothersrfilms project? → new project label, atoms tagged accordingly
- Skip? → exclude from Studio sweeper

### Phase 9: Tailscale on Studio (off-LAN access)

After Phase 6 works on LAN, add Tailscale for travel/off-LAN.

```bash
ssh studio "brew install tailscale"
ssh studio "sudo tailscale up --hostname=erichs-mac-studio"
```

Update Studio's MCP endpoint URL to laptop's Tailscale IP (100.x.y.z instead of 192.168.1.X). Test off-LAN: disable laptop WiFi, connect via cellular, query Brain from Studio.

### Phase 10: Disk health (parallel — urgent)

Independent of Brain integration but flagged in recon as urgent ops issues.

- **MASTER 140 TB 1 at 99.3% (1TB free)** — audit largest folders, offload or expand. Run on Studio: `du -h /Volumes/MASTER\ 140\ TB\ 1 | sort -rh | head -50`.
- **Studio internal at 94% (57GB free)** — audit ~/Desktop, ~/Documents, ~/Library/Caches. Free at least 100GB before Studio runs its daily routine (which writes audit DBs + venv).

## Architecture diagram

```
                    ┌─────────────────────────────────────┐
                    │   LAPTOP (canonical Brain host)     │
                    │                                     │
                    │   ~/Desktop/Brain/  (5,609 atoms)   │
                    │   Neo4j Docker (port 7687)          │
                    │   MCP server (port 8788, 0.0.0.0)   │
                    │   Daily routine (6am MT)            │
                    │                                     │
                    └──────────┬──────────────────────────┘
                               │
                       LAN (192.168.1.x)
                       + Tailscale fallback
                               │
              ┌────────────────┼─────────────────┐
              │                │                 │
              ▼                ▼                 ▼
        rsync 4am MT     MCP queries        MCP writes
        (laptop→studio)  (Studio reads)     (Studio pushes atoms)
              │                │                 │
              ▼                ▼                 ▼
                    ┌────────────────────────────────────┐
                    │   STUDIO (federation client)       │
                    │                                    │
                    │   ~/Desktop/Brain-replica/         │ ← rsync target
                    │     ↳ Obsidian opens this          │
                    │                                    │
                    │   Claude Code → MCP to laptop      │ ← queries Brain
                    │                                    │
                    │   Daily routine (6:30am MT)        │ ← parallel pipeline
                    │     Sweeps: ANEP_RAID, MASTER 140, │
                    │             brothersrfilms         │
                    │     Pushes atoms → laptop MCP      │ ← write endpoint
                    │                                    │
                    └────────────────────────────────────┘
```

## Critical files

### Existing (read/reuse)
- `~/Cornelius/resources/brain-graph/mcp_server.py` — MCP server (extend with write endpoint)
- `~/Cornelius/resources/brain-graph/store.py` — atomic-write pattern (reuse for MCP write)
- `~/Cornelius/resources/brain-graph/daily/sweeper.py` — sweeper engine (parameterize SCAN_ROOTS for Studio)
- `~/Cornelius/resources/brain-graph/daily/router.py` — router (reuse as-is)
- `~/Cornelius/resources/brain-graph/daily/processor.py` — processor (reuse with MCP push instead of local write)
- `~/Cornelius/resources/brain-graph/daily/com.zeus-brain.daily-ingest.plist` — template for Studio variant
- `~/Cornelius/resources/brain-graph/discover_remote_vaults.sh` — already SSH-based (reusable for ANEP/MASTER inventory)
- `~/Desktop/Brain/wiki/Meta/_outputs/mac-studio-recon-2026-05-16.md` — recon report
- `~/Desktop/NIKLAS-from-studio-2026-05-16/` — staged Studio NIKLAS

### Create (new code)
- `~/Cornelius/resources/brain-graph/scripts/merge_studio_niklas.py` — Phase 1 merge driver (md5 compare, route, FLAG divergent)
- `~/Cornelius/resources/brain-graph/scripts/sync-brain-to-studio.sh` — Phase 4 rsync replica
- `~/Library/LaunchAgents/com.zeus-brain.sync-to-studio.plist` — Phase 4 cron
- `~/Cornelius/resources/brain-graph/daily/sweeper_studio_roots.py` — Phase 6 Studio-side scan roots
- `studio:~/Library/LaunchAgents/com.zeus-brain.daily-ingest-studio.plist` — Phase 6 Studio launchd
- `~/Cornelius/resources/brain-graph/mcp_server.py` — Phase 7 add write tool (modify, not create)
- `~/Cornelius/resources/brain-graph/scripts/push-atom-to-laptop.py` — Phase 6 Studio's atom push client

### Modify
- `~/Cornelius/resources/brain-graph/.env` — add `MCP_BIND_HOST=0.0.0.0` and `MCP_WRITE_TOKEN=<generated>`
- `~/Cornelius/resources/brain-graph/test_mcp_safety.py` — add 5-10 write-endpoint tests
- `studio:~/.claude.json` — add `zeus-brain` MCP entry pointing at laptop

## Verification

### Phase 1 verification (Studio NIKLAS merge)
```bash
# Atom count grew
find /Users/erichroepke/Desktop/Brain -type f -name "*.md" -not -path "*/.git/*" | wc -l
# expect: 5,576 + 200-400 from merge

# BDG re-bootstrapped after merge
cd ~/Cornelius/resources/brain-graph && ./run_brain_graph.sh status

# Divergent review queue exists
cat /Users/erichroepke/Desktop/Brain/wiki/Meta/_outputs/studio-merge-divergent-2026-05-16.md | head -20
```

### Phase 2-3 verification (MCP federation)
```bash
# From laptop
curl -H "Authorization: Bearer $MCP_TOKEN" http://192.168.1.X:8788/health
# expect: 200 OK

# From Studio
ssh studio "claude mcp list" | grep zeus-brain
# expect: zeus-brain entry present

ssh studio "claude -p 'search Brain for bert-zeus-naming-candidates and return the file path'"
# expect: returns wiki/Document Insights/2026-05-15 Bert Zeus/bert-zeus-naming-candidates.md
```

### Phase 4 verification (rsync replica)
```bash
# Run sync manually first
~/Cornelius/resources/brain-graph/scripts/sync-brain-to-studio.sh

# Verify on Studio
ssh studio "find ~/Desktop/Brain-replica -name '*.md' | wc -l"
# expect: matches laptop's count

# Check launchd registered
launchctl list | grep zeus-brain.sync-to-studio
```

### Phase 5 verification (Python on Studio)
```bash
ssh studio "/opt/homebrew/bin/python3.11 --version"
# expect: Python 3.11.x
ssh studio "ls ~/Cornelius/resources/local-brain-search/venv-studio/bin/python"
```

### Phase 6 verification (Studio daily routine)
```bash
# Dry-run from Studio
ssh studio "cd ~/Cornelius/resources/brain-graph && python -m daily.cli run --dry-run --max-cost-cents 100"
# expect: scans Studio drives, no writes

# launchd registered
ssh studio "launchctl list | grep zeus-brain.daily-ingest-studio"
```

### Phase 7 verification (MCP write endpoint)
```bash
# Write test atom via MCP
curl -X POST http://192.168.1.X:8788/atoms \
  -H "Authorization: Bearer $MCP_WRITE_TOKEN" \
  -d '{"vault_relative_path":"wiki/Document Insights/test/sample.md","content":"# Test","content_hash":"..."}'
# expect: {"canonical_path":"...","deduplicated":false}

# Verify it landed
ls -la "/Users/erichroepke/Desktop/Brain/wiki/Document Insights/test/sample.md"
```

### Phase 9 verification (Tailscale)
```bash
ssh studio-ts echo "Tailscale reachability OK"
# expect: prints OK (was timeout before)
```

### End-to-end verification
```bash
# 1. Touch a new file on Studio's ANEP_RAID
ssh studio "echo '# test atom' > /Volumes/ANEP_RAID_1B/NIKLAS_RAW/test-integration-$(date +%s).md"

# 2. Wait for Studio's 6:30am daily routine OR trigger manually
ssh studio "launchctl start com.zeus-brain.daily-ingest-studio"

# 3. Verify atom appeared in laptop's Brain
find /Users/erichroepke/Desktop/Brain -name "test-integration-*" | head

# 4. Verify it's in Neo4j after next laptop bootstrap
docker exec zeus-brain-neo4j cypher-shell -u neo4j -p "$BRAIN_NEO4J_PASS" \
  "MATCH (n:Atom) WHERE n.id CONTAINS 'test-integration' RETURN n.id"
```

## Phase sequence + dependencies

```
Phase 1: Merge Studio NIKLAS          [agent dispatch, ~30-60min]
    │
    ▼
Phase 2: Bind MCP to network          [code change + restart, ~10min]
    │
    ▼
Phase 3: Studio MCP client            [ssh edit ~/.claude.json, ~5min]
    │
    ├──► Phase 4: Daily rsync replica  [parallel, ~30min]
    │
    └──► Phase 7: MCP write endpoint   [parallel, ~1hr code + tests]
              │
              ▼
        Phase 5: Python 3.11+ on Studio [~15min]
              │
              ▼
        Phase 6: Studio daily routine   [~2hr setup + first dry-run]

Phase 8: brothersrfilms recon         [parallel anytime, ~10min]
Phase 9: Tailscale on Studio          [after LAN works, ~15min]
Phase 10: Disk health                 [parallel ongoing, audit + remediation]
```

**Critical path:** Phase 1 → Phase 2 → Phase 3 → Phase 5 → Phase 6 + Phase 7 (parallel). Total estimated wall time: **3-5 hours** including agent dispatch.

## Out of scope (v3)

- Replacing Obsidian Sync (Erich's not paying for it; rsync replica is sufficient)
- Real-time bidirectional sync (Studio only WRITES via MCP push; doesn't edit Brain-replica directly)
- Replicating Neo4j to Studio (Pattern C means Studio queries laptop's Neo4j; no local graph DB)
- Replicating LBS FAISS to Studio (same reason; could be added later as fallback when laptop unreachable)
- Trinity Docker stack (deferred per prior /autoplan; not blocking Studio integration)
- Studio writing to Studio's NIKLAS post-merge (NIKLAS becomes archive after Phase 1; new writes go to Brain via MCP)
- ANEP_RAID's full inventory beyond NIKLAS_RAW (Phase 6 sweeps that subdir; expanding scope to full ANEP is a separate decision)
- Migrating MASTER 140TB project archive structure (only .md files indexed; archive structure preserved as-is)

## Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Studio disk fills during Studio daily routine (94% full, 57GB free) | HIGH | Phase 10 disk audit BEFORE Phase 6. Studio's audit DB + venv adds ~500MB; need cushion. |
| MCP server crash takes Brain offline for Studio | MEDIUM | launchd KeepAlive on MCP server. Studio falls back to Brain-replica for reads when MCP unreachable. |
| Tailscale not installed = no off-LAN access | MEDIUM | Phase 9 handles this. Until then, Studio must be on home LAN. Document this. |
| Atom dedup logic in MCP write endpoint races between Studio + laptop daily routines | MEDIUM | md5-based atomic check in Phase 7. Last-write-wins is acceptable for v1 (Phase 1 will surface any conflicts to review queue). |
| Studio's NIKLAS contains atoms that LAPTOP'S Brain doesn't have but laptop's Cornelius classifier wouldn't accept | LOW | Phase 1 FLAG divergent → human review. Don't auto-accept anything weird. |
| ANEP_RAID disconnect during Studio sweep | LOW | Sweeper already handles missing drives gracefully (skip + log). |

---

# v4 Mac Studio Full Provisioning — Transfer System to Studio

**Date:** 2026-05-17
**Trigger:** Erich asked to transfer today's work to Mac Studio so Studio becomes a fully self-sufficient Brain host, not just a federated read-replica.

## Context

After v3 Studio integration shipped, Studio's role is CLIENT — queries laptop's Brain via MCP and reads a nightly rsync replica. That works for browsing + querying but Studio still depends on the laptop for:

- Neo4j graph database (only laptop has Docker)
- BDG bootstrap (only laptop has Python 3.11+ + Cornelius)
- Daily routine sweeping + Cornelius skill invocation
- MCP server itself (laptop's daemon, port 8788)

If the laptop is offline, Studio's Brain access degrades to "read the rsync replica in Obsidian." No graph queries, no semantic enrichment, no daily ingest from Studio's own drives.

v4 elevates Studio from client → peer. Studio gets its own full stack: tooling, dependencies, optional Docker+Neo4j, and the ability to run the daily routine + write atoms locally.

Two patterns to choose between:

- **Pattern D — Studio as PEER:** Studio runs same stack as laptop but Brain stays canonical on laptop. Studio's daily routine + Cornelius skills run locally, atoms push to laptop via MCP. Studio's queries go through Pattern C federation. Same as v3 + Studio gets full local tooling.
- **Pattern E — Studio as CANONICAL:** Brain moves to Studio. Laptop becomes the federated client. Inverts v3.

This plan assumes **Pattern D** as default (smaller risk, additive). Pattern E is an explicit migration if Erich wants to make Studio primary (e.g., laptop becomes travel-only).

## Pre-flight state (known from v3 recon + work)

| Item | State |
|---|---|
| Studio reachability | `ssh studio` works on LAN (Tailscale NOT installed) |
| Studio OS | macOS 26.3 (Tahoe), Homebrew installed |
| Studio Python | 3.9.6 — TOO OLD for Cornelius brain-graph (needs 3.11+) |
| Studio Docker | NOT installed (required for Neo4j locally) |
| Studio Claude Code | Installed at `/opt/homebrew/bin/claude` |
| Studio internal disk | 99% full at time of last check (12GB free) — CRITICAL |
| Studio attached drives | ANEP_RAID_1B (80TB, 86% full), MASTER 140 TB (year archive), MASTER 140 TB 1 (99.3% full) |
| Studio Brain rsync replica | LIVE at `studio:~/Desktop/Brain-replica/` (4am MT nightly) |
| Studio MCP client | `zeus-brain` registered (HTTP, user-scoped, ✓ Connected) |

## Phases

### Phase 1: Disk health remediation (BLOCKER for everything else)

Studio internal is 99% full. NOTHING new can be installed safely until at least 50GB free.

**Audit steps:**
1. `ssh studio "du -sh ~/Library/Caches/* 2>/dev/null | sort -rh | head -20"` — find biggest caches
2. `ssh studio "du -sh ~/Desktop/* 2>/dev/null | sort -rh | head -20"` — Desktop offenders
3. `ssh studio "ls -laS /private/var/folders 2>/dev/null | head -10"` — system caches
4. `ssh studio "find ~/Downloads -type f -size +500M -exec ls -lah {} \\;"` — large downloads

**Common Mac wins:**
- Empty Xcode + Simulator caches (often 10-50GB)
- Trash old Time Machine snapshots: `tmutil deletelocalsnapshots /`
- Clean Docker volumes if any (we know Studio has no Docker, so N/A)
- iCloud Drive optimized storage on/off toggle

**Target:** Studio internal ≥50GB free before Phase 2.

**Files:** Write findings to `wiki/Meta/_outputs/studio-disk-audit-2026-05-17.md`.

### Phase 2: Studio prereqs

Install missing tooling via Homebrew (Studio has brew).

```bash
ssh studio 'bash -s' <<'EOF'
# Python 3.11+ (Cornelius brain-graph requirement)
brew install python@3.11
which python3.11

# git + rsync + jq + sqlite (some may already be present)
brew install git rsync jq sqlite

# Docker Desktop (optional — only if Pattern D's Phase 5 locally hosts Neo4j)
# Skip for now if disk is tight; Studio can keep using laptop's Neo4j via MCP.

# Tailscale (for off-LAN access, prerequisite for v3 Phase 9)
brew install --cask tailscale
# Then GUI sign-in required — Erich must launch + auth manually
EOF
```

**Files modified on Studio:**
- `/opt/homebrew/bin/python3.11` — new
- `/opt/homebrew/bin/git` (may already exist)
- `/Applications/Tailscale.app` — new

**User actions:**
- Sign in to Tailscale.app GUI on Studio after install. Authenticate against Erich's Tailnet (`tail1af2e9.ts.net`).

### Phase 3: Clone brain-graph tooling onto Studio

```bash
ssh studio 'bash -s' <<'EOF'
# Clone Cornelius (Erich's fork — personal-config branch has today's work)
mkdir -p ~/Cornelius/resources
cd ~/Cornelius
git clone -b personal-config https://github.com/erichroepke/cornelius.git .
# OR if it's an existing checkout, pull:
# git pull origin personal-config
EOF
```

**Verify:** `ssh studio "ls ~/Cornelius/resources/brain-graph/"` lists daily/, enrichment/, mcp_server.py, scripts/, sdk/, tests.

### Phase 4: Studio venv + dependencies

```bash
ssh studio 'bash -s' <<'EOF'
cd ~/Cornelius/resources/local-brain-search
# Create venv with Python 3.11
/opt/homebrew/bin/python3.11 -m venv venv-studio
source venv-studio/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Also install brain-graph deps
cd ~/Cornelius/resources/brain-graph
pip install -r requirements-mcp.txt
# sentence-transformers, faiss-cpu, mcp, fastmcp, neo4j, pydantic, etc.
EOF
```

**Disk impact:** ~1-2GB for sentence-transformers models + FAISS. Add to disk-audit headroom.

### Phase 5: Studio's local data state

Studio needs its own copies of:
- `brain_graph_config.yaml` (point to `~/Desktop/Brain-replica/` or new path)
- `.env` (generate fresh BRAIN_NEO4J_PASS + MCP_WRITE_TOKEN — DIFFERENT from laptop's)
- LBS FAISS index (regenerate, ~5 min)
- BDG sidecar (regenerate, ~30s)

```bash
ssh studio 'bash -s' <<'EOF'
cd ~/Cornelius/resources/brain-graph
# Copy the v2.2-compatible config
cp brain_graph_config.yaml.example brain_graph_config.yaml || cp brain_graph_config.yaml /tmp/  # if no .example, hand-edit
# Generate fresh secrets
echo "BRAIN_NEO4J_USER=neo4j" > .env
echo "BRAIN_NEO4J_PASS=$(openssl rand -base64 24)" >> .env
echo "MCP_WRITE_TOKEN=$(openssl rand -hex 32)" >> .env
echo "BRAIN_PATH=$HOME/Desktop/Brain-replica" >> .env

# Re-index LBS against Brain-replica
cd ~/Cornelius/resources/local-brain-search
./run_index.sh  # ~5 min, builds FAISS index + metadata files

# Bootstrap BDG
cd ~/Cornelius/resources/brain-graph
./run_brain_graph.sh bootstrap --force
EOF
```

**Files created on Studio:**
- `studio:~/Cornelius/resources/local-brain-search/data/brain.faiss` (~40MB)
- `studio:~/Cornelius/resources/local-brain-search/data/brain_metadata.binary` (~16MB serialized metadata)
- `studio:~/Cornelius/resources/brain-graph/data/graph_enrichments.json` (~16MB sidecar)

### Phase 6: Decide — Local Neo4j on Studio? Or stay federated?

**Option A: Skip local Neo4j (RECOMMENDED for v4 first cut).**
Studio queries laptop's Neo4j via MCP for graph reads. No Docker required on Studio. Simpler. Works as long as laptop is on LAN/Tailscale.

**Option B: Install Docker + Neo4j on Studio (for offline resilience).**
Studio gets its own Neo4j container. Requires Docker Desktop (~3GB) + Neo4j data (~500MB). Brings disk pressure back unless Phase 1 cleared serious headroom.

**Sync model if Option B:**
- Studio's Neo4j is a read-replica (one-way: laptop pushes via cron, e.g. nightly cypher dump + import)
- OR: bidirectional with conflict resolution (more complex)

Default to Option A. Document the upgrade path to Option B in case Erich wants offline mode later.

### Phase 7: Studio's daily routine (independent ingest)

Reuse v3 Phase 6 design — Studio sweeps its OWN drives (NIKLAS_RAW on ANEP_RAID, MASTER 140 TB project .md files), processes via Cornelius skills locally, pushes atoms to LAPTOP'S Brain via MCP write endpoint.

```bash
ssh studio 'bash -s' <<'EOF'
cd ~/Cornelius/resources/brain-graph

# Snapshot first to baseline Studio's drive state (one-time)
./venv-studio/bin/python -m daily.cli snapshot

# Install launchd job for 6:30am MT trigger (30 min offset from laptop)
cp daily/com.zeus-brain.daily-ingest.plist ~/Library/LaunchAgents/com.zeus-brain.daily-ingest-studio.plist
# Hand-edit plist: change Label suffix to "-studio", adjust SCAN_ROOTS env to studio paths
launchctl load ~/Library/LaunchAgents/com.zeus-brain.daily-ingest-studio.plist
EOF
```

**Sweeper config for Studio (`daily/sweeper_studio_roots.py` or env override):**
```python
SCAN_ROOTS_STUDIO = [
    {"path": "/Volumes/ANEP_RAID_1B/NIKLAS_RAW", "max_depth": -1},
    {"path": "/Volumes/MASTER 140 TB", "max_depth": 3, "ext_filter": [".md"]},
    {"path": "/Volumes/MASTER 140 TB 1", "max_depth": 3, "ext_filter": [".md"]},
]
EXCLUDE_DIR_PATTERNS_STUDIO = (
    ".Trash", "Library", "Movies", "Pictures", "Music",
    ".cache", ".git", "__pycache__", "node_modules", ".venv", "venv",
    "Brain", "Brain-replica", "NIKLAS",  # don't sweep the wiki itself
    "snapshots", "components",
)
```

**Push to laptop via MCP write_atom (Phase 7 endpoint already shipped):**
The processor writes atoms locally on Studio, then POSTs each via `mcp__zeus-brain__write_atom` with auth token (already configured in Studio's `~/.claude.json`).

### Phase 8: Obsidian on Studio

Already working — `~/Desktop/Brain-replica/` is a synced read copy. Erich opens it in Obsidian.

Optional improvement: install Smart Connections plugin pointed at the same FAISS index Studio builds in Phase 5 for local semantic search inside Obsidian.

### Phase 9: Verification

```bash
# 1. Studio can run brain-graph CLI
ssh studio "cd ~/Cornelius/resources/brain-graph && ./venv-studio/bin/python -m daily.cli status"

# 2. Studio's LBS works
ssh studio "cd ~/Cornelius/resources/local-brain-search && ./run_search.sh 'bert zeus naming' --limit 3"

# 3. Studio's MCP client still reaches laptop's daemon
ssh studio "/opt/homebrew/bin/claude mcp get zeus-brain"  # expect: ✓ Connected

# 4. Studio's daily routine dry-run succeeds
ssh studio "cd ~/Cornelius/resources/brain-graph && ./venv-studio/bin/python -m daily.cli run --dry-run --max-cost-cents 100"

# 5. End-to-end: drop file on ANEP, trigger Studio routine, verify atom lands on laptop
ssh studio "echo '# v4 test' > /Volumes/ANEP_RAID_1B/NIKLAS_RAW/v4-test-$(date +%s).md"
ssh studio "launchctl start com.zeus-brain.daily-ingest-studio"
sleep 60
find ~/Desktop/Brain -name "v4-test-*" 2>/dev/null
```

### Phase 10: Tailscale activation (off-LAN)

After Phase 2 install + Erich's GUI auth:

```bash
ssh studio "tailscale status"  # expect: shows Studio's 100.x.y.z IP

# Update Studio's MCP entry to use Tailscale hostname (not 192.168.1.162)
ssh studio "/opt/homebrew/bin/claude mcp remove zeus-brain -s user"
LAPTOP_TS_IP=$(tailscale ip -4 | head -1)  # run on laptop
TOKEN=$(grep MCP_WRITE_TOKEN ~/Cornelius/resources/brain-graph/.env | cut -d= -f2)
ssh studio "/opt/homebrew/bin/claude mcp add --transport http -s user zeus-brain http://${LAPTOP_TS_IP}:8788/mcp --header 'Authorization: Bearer ${TOKEN}'"
```

**Off-LAN test:** Erich takes laptop to a coffee shop, Studio queries Brain over Tailscale. If `claude mcp get zeus-brain` still ✓ Connected from Studio with laptop on cellular → SUCCESS.

## Architecture diagram (post-v4)

```
                      ┌─────────────────────────────────────┐
                      │   LAPTOP — CANONICAL Brain host     │
                      │                                     │
                      │   ~/Desktop/Brain/  (6,927 atoms)   │
                      │   Neo4j Docker                      │
                      │   MCP HTTP daemon (port 8788)       │
                      │   Daily routine (6am MT)            │
                      │   rsync-to-studio (4am MT)          │
                      └────────┬────────────────────────────┘
                               │
                       LAN (192.168.1.x)
                       OR Tailscale (100.x.x.x post-Phase 10)
                               │
              ┌────────────────┼─────────────────┐
              │                │                 │
              ▼                ▼                 ▼
        rsync 4am MT     MCP reads          MCP writes
       (laptop→studio)   (Studio queries)   (Studio pushes atoms)
              │                │                 │
              ▼                ▼                 ▼
                      ┌────────────────────────────────────┐
                      │   STUDIO — PEER (full local stack)  │
                      │                                    │
                      │   ~/Desktop/Brain-replica/          │ ← rsync target
                      │     ↳ Obsidian opens this           │
                      │                                    │
                      │   ~/Cornelius/  (git clone)         │ ← brain-graph tooling
                      │     venv-studio/  (Python 3.11)     │
                      │     LBS FAISS index (Studio's own)  │
                      │     BDG sidecar (Studio's own)      │
                      │                                    │
                      │   Daily routine (6:30am MT)         │ ← parallel pipeline
                      │     Sweeps: ANEP_RAID, MASTER 140  │
                      │     Pushes atoms → laptop's MCP    │ ← write endpoint
                      │                                    │
                      │   Optional: local Neo4j (Phase 6B)  │ ← offline resilience
                      └────────────────────────────────────┘
```

## Critical files

### Create on Studio (NEW)
- `studio:~/Cornelius/` (full git clone of Cornelius personal-config branch)
- `studio:~/Cornelius/resources/local-brain-search/venv-studio/` (Python 3.11 venv)
- `studio:~/Cornelius/resources/local-brain-search/data/brain.faiss` (~40MB Studio's own index)
- `studio:~/Cornelius/resources/brain-graph/.env` (Studio's own secrets, distinct from laptop)
- `studio:~/Cornelius/resources/brain-graph/data/graph_enrichments.json` (Studio's own BDG sidecar)
- `studio:~/Library/LaunchAgents/com.zeus-brain.daily-ingest-studio.plist`

### Reuse / modify
- `studio:~/.claude.json` — already has zeus-brain MCP entry (v3 Phase 3); maybe update to Tailscale IP in Phase 10
- `studio:~/Desktop/Brain-replica/` — rsync replica (already populated, 4am MT auto-refresh)

### Stays on laptop only
- `~/Cornelius/resources/brain-graph/mcp_server.py` running as launchd HTTP daemon (`com.zeus-brain.mcp-daemon.plist`)
- Neo4j Docker container (`zeus-brain-neo4j`)
- Canonical `~/Desktop/Brain/`
- All Team B proposals (`data/team-b-{first,second,third}pass/`)

## Verification (end-to-end)

```bash
# A. Studio has all tooling
ssh studio "ls ~/Cornelius/resources/brain-graph/{daily,enrichment,scripts,sdk}" | wc -l  # expect: nonzero each

# B. Studio's Python is 3.11+
ssh studio "~/Cornelius/resources/local-brain-search/venv-studio/bin/python --version"  # 3.11.x

# C. Studio's LBS works
ssh studio "~/Cornelius/resources/local-brain-search/run_search.sh 'phase F' --limit 3 --json"  # returns results

# D. Studio's MCP client reaches laptop
ssh studio "/opt/homebrew/bin/claude mcp get zeus-brain"  # ✓ Connected

# E. Studio's daily routine dry-run
ssh studio "cd ~/Cornelius/resources/brain-graph && ./venv-studio/bin/python -m daily.cli run --dry-run"

# F. End-to-end ingest from Studio → laptop
ssh studio "echo '# v4 e2e test' > /Volumes/ANEP_RAID_1B/NIKLAS_RAW/v4-e2e-$(date +%s).md"
ssh studio "launchctl start com.zeus-brain.daily-ingest-studio"
sleep 120
find ~/Desktop/Brain -name 'v4-e2e-*' 2>/dev/null  # expect: file landed on laptop

# G. Off-LAN test (after Tailscale)
# Take laptop off home Wi-Fi, query from Studio
ssh studio "/opt/homebrew/bin/claude mcp get zeus-brain"  # still ✓ Connected via Tailscale
```

## Phase sequence + critical path

```
Phase 1: Disk health [BLOCKER — must clear before any install]
   │
   ▼
Phase 2: Studio prereqs (brew install python3.11, git, rsync, tailscale)
   │
   ▼
Phase 3: Git clone Cornelius onto Studio
   │
   ▼
Phase 4: Studio venv + pip install deps
   │
   ▼
Phase 5: Studio's local LBS index + BDG sidecar (regenerated locally from Brain-replica)
   │
   ├──► Phase 6: Decide local Neo4j (default: skip; defer to laptop's via MCP)
   │
   ├──► Phase 7: Studio daily routine + launchd
   │
   ├──► Phase 8: Obsidian on Studio (already working)
   │
   └──► Phase 10: Tailscale activation (Erich GUI auth required)
              │
              ▼
        Phase 9: End-to-end verification
```

**Critical path wall time:** ~2-3 hours assuming disk health Phase 1 is straightforward. Most time is `pip install` waiting for sentence-transformers downloads.

## Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Studio disk fills during install (99% full!) | CRITICAL | Phase 1 BLOCKER. Don't proceed until ≥50GB free. |
| Python 3.11 install on Tahoe fails (recent OS, brew lag) | LOW | Fallback: pyenv install 3.11.x manually. Or use Python 3.12 if 3.11 isn't available. |
| FAISS sentence-transformers download fails (~500MB) | LOW | Retry with `pip install --no-cache-dir`. Or rsync the model from laptop's venv. |
| Studio's daily routine sweeps drives that auto-unmount | MEDIUM | Sweeper handles missing drives gracefully. Document which drives must be mounted before 6:30am. |
| Tailscale GUI auth requires physical interaction with Studio | MEDIUM | Document as user action. Phase 10 deferred until Erich is physically at Studio. |
| Both machines' daily routines fire on same content (race) | LOW | Different scan roots — laptop sweeps ~/Desktop, Studio sweeps /Volumes/ANEP + /Volumes/MASTER. No overlap. |
| Studio Neo4j desync from laptop's (if Phase 6B chosen) | DEFERRED | Pattern A keeps Studio querying laptop's Neo4j; no replica drift. |
| Cornelius repo clone pulls Brain template scaffolding that conflicts with Brain-replica | LOW | Brain-replica is at ~/Desktop/Brain-replica/, separate from anything in ~/Cornelius/. No path overlap. |

## Out of scope (v4)

- Inverting canonicality (Pattern E: Brain moves to Studio, laptop becomes client). Separate plan if Erich wants this later.
- iOS/iPad federation. Pattern C HTTP MCP works for any client, but iOS Claude Code is not yet a thing.
- Multi-tenant write conflicts (multiple Erich machines writing same atom). Out of scope until ≥3 machines.
- Replicating Trinity Docker stack on Studio (Trinity deferred per prior plans).
- Migrating MASTER 140TB project archive to Studio's internal disk (it's 140TB; impossible).

## Out-of-band user actions

| # | Action | Where | Why |
|---|--------|-------|-----|
| 1 | Free disk space on Studio (≥50GB) | Studio GUI / terminal | Phase 1 blocker |
| 2 | Authorize Tailscale GUI sign-in on Studio | Studio GUI | Phase 10 prereq |
| 3 | Decide Option A (no local Neo4j) vs Option B (Docker + Neo4j) | Decision | Phase 6 fork |
| 4 | Mount required drives before 6:30am if Studio daily routine should sweep them | Daily habit | Sweeper limitation |
