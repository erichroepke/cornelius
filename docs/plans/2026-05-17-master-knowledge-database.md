# Master Knowledge Database Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use zeus:executing-plans to implement this plan task-by-task.

**Goal:** Build a desktop-hosted master knowledge database that indexes distributed drives, vaults, and project folders into one searchable RAG + Zettelkasten + Neo4j/MCP system without physically consolidating all source files.

**Architecture:** External files remain in place and are represented by a source catalog, file inventory, and intake queue. Approved items are processed through named profiles and optional project/lens Markdown, producing durable `Brain/wiki` notes, RAG chunks, graph nodes, and Neo4j relationships. `brain-console` becomes the operator surface for status, source registry, intake approval, and search.

**Tech Stack:** Python stdlib, SQLite, Markdown/YAML, existing Cornelius daily pipeline, FAISS/local-brain-search, Brain Dependency Graph, Neo4j Docker, MCP server, local `brain-console` HTTP UI.

---

## Current State Analysis

### Confirmed Roots

- Brain wiki: `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki`
- Brain repo root: `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain`
- Cornelius repo/tooling root: `/Users/erichroepke/Desktop/Cornelius`
- Brain graph runtime: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph`
- Local search runtime: `/Users/erichroepke/Desktop/Cornelius/resources/local-brain-search`
- Brain Console: `/Users/erichroepke/Desktop/Cornelius/resources/brain-console`
- Neo4j browser: `http://localhost:7476/browser/`
- Neo4j Bolt: `bolt://localhost:7689`
- MCP HTTP daemon: `http://127.0.0.1:8788/mcp`

### What Already Exists

- `Brain/wiki` is the working Markdown knowledge base.
- `Brain` is connected to `https://github.com/erichroepke/zeus-brain`.
- `resources/brain-graph/data/graph_enrichments.json` exists.
- `resources/local-brain-search/data` exists.
- `zeus-brain-neo4j` is running and loaded.
- `zeus-brain` MCP is listening.
- `resources/brain-console` exists and is a read-only dashboard for status, search, graph neighborhoods, and sources.
- `resources/brain-graph/daily` has a five-stage pipeline:
  - `sweeper.py`
  - `router.py`
  - `processor.py`
  - `enricher.py`
  - `digest.py`

### Main Gaps

- Path truth for active config/docs/scripts must avoid stale `/Users/erichroepke/Cornelius` and `/Users/erichroepke/Desktop/Brain` targets. `/Users/erichroepke/Desktop/Brain` is only a stub and must not be deleted or moved.
- The daily sweeper is intentionally narrow and does not know about the full drive/source universe.
- There is no first-class source catalog for all drives, vaults, and folders.
- There is no intake queue that separates detection from analysis.
- There is no approval gate before analysis.
- There is no analysis profile or lens registry.
- There is no durable schema for "same source, many interpretations."
- The Brain Console is read-only and does not yet expose intake approval or profile selection.
- The graph schema does not yet explicitly represent source items, analysis runs, profiles, lenses, and project contexts as first-class nodes.

### Product Correction

The product is not "analysis." The product is a stocked, searchable master database. Analysis is one controlled ingestion path into that database.

The system must support two complementary retrieval modes:

- Hierarchical RAG: source-folder/project-aware retrieval over files, chunks, and provenance.
- Zettelkasten: atomic notes, MOCs, semantic links, and long-lived ideas.

---

## Target Model

### Core Entities

```text
SourceRoot
  a watched drive/folder/vault with policy

SourceItem
  a discovered file/folder/media item, never physically moved by default

IntakeItem
  a new/changed SourceItem awaiting action or approval

AnalysisProfile
  named processing mode, such as index_only, markdown_zettelkasten, project_inventory

Lens
  user-provided Markdown context, usually a project one-pager or master MD

AnalysisRun
  one approved pass over one or more SourceItems with one profile and optional lens

KnowledgeArtifact
  output written to Brain/wiki: source notes, atoms, MOCs, manifests, summaries

GraphEdge
  relationship between SourceItems, AnalysisRuns, KnowledgeArtifacts, and atoms
```

### Processing Rule

Detection is automatic. Analysis is approval-driven unless a source policy explicitly allows auto-processing.

### Source File Rule

External source files stay where they are. Brain stores searchable knowledge, metadata, pointers, hashes, manifests, extracted text, and atomic notes.

### Multi-Context Rule

A source can be analyzed multiple times for different projects or lenses. Never overwrite the original interpretation; append a new `AnalysisRun`.

---

## Data Layout

### Brain Runtime Directory

Create a local runtime directory that is ignored by Git:

```text
/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/.brain/
  source_catalog.yaml
  source_inventory.db
  intake_queue.db
  analysis_runs.db
  rag/
  graph/
  logs/
```

### Brain Wiki Additions

```text
/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki/Meta/Lenses/
  README.md
  *.md

/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki/Meta/Analysis Profiles/
  README.md
  *.md

/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki/Meta/Intake/
  pending-YYYY-MM-DD.md
  completed-YYYY-MM-DD.md

/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki/Sources/
  Projects/
  Footage/
  Vaults/
  Drives/
```

### Cornelius Code Additions

```text
/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/source_catalog.py
/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/inventory.py
/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/intake_queue.py
/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/profiles.py
/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/lenses.py
/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/analysis_runs.py
/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/test_source_intake.py
```

### Brain Console Additions

```text
/Users/erichroepke/Desktop/Cornelius/resources/brain-console/server.py
/Users/erichroepke/Desktop/Cornelius/resources/brain-console/static/app.js
/Users/erichroepke/Desktop/Cornelius/resources/brain-console/static/index.html
/Users/erichroepke/Desktop/Cornelius/resources/brain-console/static/styles.css
```

---

## Source Catalog Shape

Create `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/.brain/source_catalog.yaml`.

Initial schema:

```yaml
version: 1
roots:
  - id: zeus_drive_zeus
    path: /Volumes/ZEUS DRIVE/Zeus
    kind: workspace
    enabled: true
    watch: true
    recurse: true
    max_depth: 8
    include_extensions: [md, txt, pdf, docx, json, yaml, csv]
    exclude_names: [.git, node_modules, __pycache__, .venv]
    default_policy: queue_for_approval
    default_profiles: [markdown_zettelkasten, project_context]

  - id: master_140_2026
    path: /Volumes/MASTER 140 TB 1/2026
    kind: project_archive
    enabled: true
    watch: true
    recurse: true
    max_depth: 5
    include_extensions: [md, txt, pdf, docx, json, csv]
    exclude_names: [.git, node_modules, Cache, Renders]
    default_policy: queue_for_approval
    default_profiles: [project_inventory, document_insights]

  - id: anep_footage
    path: /Volumes/ANEP_RAID_1B/2FOOTAGE
    kind: footage
    enabled: true
    watch: true
    recurse: true
    max_depth: 6
    include_extensions: [mov, mp4, wav, m4a, xml, fcpxml, csv, md, txt]
    default_policy: queue_for_approval
    default_profiles: [media_manifest]
```

Important: this catalog is not a move plan. It is an inventory and intake policy.

---

## SQLite Schemas

### `source_inventory.db`

```sql
CREATE TABLE source_items (
  id TEXT PRIMARY KEY,
  root_id TEXT NOT NULL,
  abs_path TEXT NOT NULL UNIQUE,
  rel_path TEXT NOT NULL,
  kind TEXT NOT NULL,
  extension TEXT,
  size_bytes INTEGER,
  mtime REAL,
  content_hash TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  last_changed_at TEXT,
  status TEXT NOT NULL,
  metadata_json TEXT
);
```

### `intake_queue.db`

```sql
CREATE TABLE intake_items (
  id TEXT PRIMARY KEY,
  source_item_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  suggested_profiles_json TEXT NOT NULL,
  suggested_project TEXT,
  suggested_lens_path TEXT,
  status TEXT NOT NULL,
  approved_profile TEXT,
  approved_lens_path TEXT,
  approved_at TEXT,
  notes TEXT
);
```

### `analysis_runs.db`

```sql
CREATE TABLE analysis_runs (
  id TEXT PRIMARY KEY,
  source_item_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  lens_path TEXT,
  requested_by TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  model TEXT,
  prompt_version TEXT,
  status TEXT NOT NULL,
  output_paths_json TEXT,
  created_edges_json TEXT,
  summary TEXT,
  error TEXT
);
```

---

## Analysis Profiles

Profiles should be Markdown-documented and code-enforced.

Initial profiles:

```text
index_only
  Inventory, metadata, hash, source note pointer. No AI analysis.

markdown_zettelkasten
  Extract source notes, atomic ideas, links, tags, and MOC candidates.

document_insights
  Extract attributed insights from PDFs, docs, proposals, RFPs, articles.

project_inventory
  Build a project map from folders, docs, briefs, notes, and existing metadata.

media_manifest
  Inventory footage/audio/photo files, technical metadata, sidecars, transcripts, project associations.

project_context
  Use a user-approved project master MD as a lens for organization and note linking.
```

Do not implement face detection, object detection, or video understanding in v1. Represent them as future profile types.

---

## Graph Model Additions

Extend Neo4j beyond `(:Atom)` by adding optional nodes:

```cypher
(:SourceRoot {id, path, kind})
(:SourceItem {id, path, kind, hash, root_id})
(:AnalysisRun {id, profile, lens_path, created_at, status})
(:Lens {id, path, title})
(:Project {id, name})
(:Atom {id, layer, lifecycle})
```

Relationships:

```cypher
(:SourceRoot)-[:CONTAINS]->(:SourceItem)
(:SourceItem)-[:ANALYZED_BY]->(:AnalysisRun)
(:AnalysisRun)-[:USED_LENS]->(:Lens)
(:AnalysisRun)-[:PRODUCED]->(:Atom)
(:Atom)-[:DERIVES_FROM]->(:SourceItem)
(:SourceItem)-[:BELONGS_TO_PROJECT]->(:Project)
(:Atom)-[:ASSOCIATES|REFERENCES|TENSION|SUPERSEDES]->(:Atom)
```

This keeps raw provenance separate from durable Zettelkasten notes.

---

## Implementation Tasks

### Task 1: Correct Canonical Paths

**Files:**
- Modify: `/Users/erichroepke/Desktop/Cornelius/docs/LOCAL-BRAIN-OPERATOR-RUNBOOK.md`
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-console/README.md`
- Search/verify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/*.sh`

**Steps:**

1. Replace stale active `/Users/erichroepke/Cornelius` references with `/Users/erichroepke/Desktop/Cornelius`.
2. Replace stale active `/Users/erichroepke/Desktop/Brain` targets with `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain`.
3. Verify scripts either use relative paths or detect Desktop root correctly.
4. Run:

```bash
rg "/Users/erichroepke/Cornelius|~/Cornelius|/Users/erichroepke/Desktop/Brain|~/Desktop/Brain" /Users/erichroepke/Desktop/Cornelius
```

Expected: only historical plan docs may retain old references.

5. Commit:

```bash
git -C /Users/erichroepke/Desktop/Cornelius add docs/LOCAL-BRAIN-OPERATOR-RUNBOOK.md resources/brain-console/README.md resources/brain-graph
git -C /Users/erichroepke/Desktop/Cornelius commit -m "docs: correct local brain paths"
```

### Task 2: Add Source Catalog Loader

**Files:**
- Create: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/source_catalog.py`
- Test: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/test_source_intake.py`

**Test cases:**

- Loads YAML or a minimal JSON-compatible YAML subset.
- Expands `~` and environment variables.
- Ignores disabled roots.
- Validates required keys: `id`, `path`, `kind`, `enabled`.
- Does not fail when a drive is disconnected; marks it unavailable.

**Implementation notes:**

- Use stdlib where possible.
- If PyYAML is unavailable, support a constrained JSON file first or add PyYAML to requirements.
- Return typed dataclasses, not raw dictionaries.

### Task 3: Add Inventory Database

**Files:**
- Create: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/inventory.py`
- Test: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/test_source_intake.py`

**Behavior:**

- Walk enabled roots according to source policy.
- Hash only eligible files.
- Store stable `source_item_id = sha1(abs_path + content_hash)`.
- Track `first_seen_at`, `last_seen_at`, `last_changed_at`.
- Skip excluded names.
- Do not move or copy files.

**Acceptance:**

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
python3 -m pytest daily/test_source_intake.py -q
```

Expected: PASS.

### Task 4: Add Intake Queue

**Files:**
- Create: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/intake_queue.py`
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/cli.py`
- Test: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/test_source_intake.py`

**CLI:**

```bash
python3 -m daily.cli discover --dry-run
python3 -m daily.cli discover
python3 -m daily.cli intake list
python3 -m daily.cli intake approve <id> --profile <profile> --lens <path>
python3 -m daily.cli intake skip <id> --reason "..."
```

**Rules:**

- Discovery queues items only.
- Discovery does not run AI.
- Approval writes selected profile and lens.
- Processor only processes approved items.

### Task 5: Add Profiles and Lenses

**Files:**
- Create: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/profiles.py`
- Create: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/lenses.py`
- Create: `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki/Meta/Lenses/README.md`
- Create: `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki/Meta/Analysis Profiles/README.md`
- Test: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/test_source_intake.py`

**Rules:**

- A profile describes allowed outputs and prompt constraints.
- A lens is Markdown and user-owned.
- A lens can be omitted for `index_only` and `media_manifest`.
- A lens path must resolve inside `Brain/wiki` or an approved source root.

### Task 6: Connect Intake to Processor

**Files:**
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/processor.py`
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/cli.py`
- Create: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/analysis_runs.py`
- Test: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/daily/test_source_intake.py`

**Behavior:**

- Process only approved intake items.
- Create an `AnalysisRun` row before work starts.
- Write source notes and output artifacts into `Brain/wiki`.
- Record all generated paths in `analysis_runs.db`.
- Mark run failed with error details if processing fails.

### Task 7: Add Brain Console Intake UI

**Files:**
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-console/server.py`
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-console/static/index.html`
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-console/static/app.js`
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-console/static/styles.css`

**Endpoints:**

```text
GET  /api/intake
POST /api/intake/approve
POST /api/intake/skip
GET  /api/profiles
GET  /api/lenses
```

**UI:**

- Add `Intake` panel.
- Show source path, root, kind, size, mtime, suggested profiles.
- Let user approve with profile and lens.
- Let user skip with reason.

### Task 8: Add Graph Export for Source/Analysis Nodes

**Files:**
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/export_to_cypher.py`
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/load_neo4j.sh`
- Test: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/test_export_to_cypher.py`

**Behavior:**

- Export `SourceRoot`, `SourceItem`, `AnalysisRun`, `Lens`, and `Project` nodes.
- Preserve existing `Atom` export.
- Add relationships without breaking old graph queries.

### Task 9: Extend MCP Tools

**Files:**
- Modify: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/mcp_server.py`
- Test: `/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/test_mcp_safety.py`

**Tools:**

```text
zeus_brain_sources
zeus_brain_intake
zeus_brain_analysis_runs
zeus_brain_find_by_source
zeus_brain_find_by_project
```

**Safety:**

- Keep write endpoints token-gated.
- Keep graph query read-only.
- Do not expose secrets or full `.env`.

### Task 10: Rollout and Baseline

**Steps:**

1. Create `source_catalog.yaml` with a small safe subset first:
   - `/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki`
   - `/Volumes/ZEUS DRIVE/Zeus`
   - `/Volumes/ANEP_RAID_1B/NIKLAS_RAW`
2. Run discovery dry-run.
3. Run discovery real, queue-only.
4. Approve one Markdown source with `index_only`.
5. Approve one Markdown source with `markdown_zettelkasten`.
6. Approve one project folder with `project_inventory`.
7. Refresh BDG and Neo4j.
8. Verify Brain Console shows intake and graph changes.
9. Only then expand to MASTER 140 and footage roots.

---

## Verification Commands

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
python3 -m pytest daily/test_daily.py daily/test_source_intake.py test_mcp_safety.py test_export_to_cypher.py -q
```

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
python3 -m daily.cli discover --dry-run
python3 -m daily.cli intake list
```

```bash
cd /Users/erichroepke/Desktop/Cornelius/resources/brain-console
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 server.py
```

Open:

```text
http://localhost:8789
```

---

## Commit Plan

Use small commits:

1. `docs: correct local brain paths`
2. `feat(daily): add source catalog loader`
3. `feat(daily): add inventory database`
4. `feat(daily): add approval intake queue`
5. `feat(daily): add profiles and lenses`
6. `feat(daily): process approved intake items`
7. `feat(console): add intake approval UI`
8. `feat(graph): export source and analysis nodes`
9. `feat(mcp): expose source and analysis queries`
10. `docs: document master knowledge database workflow`

---

## Non-Goals For First Build

- No face detection.
- No video content understanding.
- No automatic expensive model analysis.
- No physical movement of large source archives.
- No putting FAISS, Neo4j store files, or runtime DBs into Git.
- No broad sweep of all 140TB content on first run.

---

## Execution Recommendation

Start with Tasks 1-4. They create the safe substrate:

- correct canonical paths
- source registry
- inventory
- approval queue

Do not start profile processing or graph schema changes until the queue is proven with a small source set.
