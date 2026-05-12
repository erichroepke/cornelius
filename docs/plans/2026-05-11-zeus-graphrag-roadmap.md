# Zeus GraphRAG Roadmap — Phases D, E, F Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate NIKLAS atoms into the unified Brain, drive a new BERT brainstorm end-to-end through the front end, then swap the backend from FAISS/BDG to Qdrant/Neo4j without breaking the wrapper-script contract.

**Architecture:** Cornelius is the front end. `~/Desktop/Brain/` is the unified vault (Cornelius-shaped, 7 namespace folders). Today's "graph + vector" pair = Brain Dependency Graph (file-based directed graph) + FAISS Local Brain Search. Tomorrow's = Neo4j + Qdrant. Cornelius wrapper scripts (`run_index.sh`, `run_brain_graph.sh`) hide the swap. Trinity is the orchestration backend (Docker stack) — stays parked until Phase F.

**Tech Stack:** Python 3.10+, FAISS (now) → Qdrant (later), file-based BDG (now) → Neo4j (later), Cornelius MIT skills + sub-agents, Trinity Docker Compose, Obsidian for editing, `gh` CLI + git for version control, `~/Desktop/BERT/` for brainstorm staging.

**Pre-flight (already completed in setup phase):**
- Cornelius forked: `github.com/erichroepke/cornelius` (origin), `Abilityai/cornelius` (upstream)
- `personal-config` branch pushed
- Brain at `~/Desktop/Brain/` with 3,677 Permanent notes
- VAULT_BASE_PATH points at `/Users/erichroepke/Desktop/Brain`
- Zeus EXPERTS + PARTS symlinked under Brain
- Private repo `github.com/erichroepke/zeus-brain` initialized

---

## Phase D — NIKLAS Migration (Tasks 1-6)

**Why:** NIKLAS has 3,676 atoms, Brain has 3,677. Near-match suggests overlap. Need diff before merge to avoid duplicates. Schema differs (NIKLAS has 8 page types + lenses; Brain has 7 numbered folders). Reconciliation required.

**Working directory for new code:** `~/Cornelius/resources/niklas-migration/`

### Task 1: Audit NIKLAS schema vs Brain schema

**Files:**
- Create: `~/Cornelius/resources/niklas-migration/AUDIT.md`

**Step 1: Read NIKLAS schema**

Run: `cat ~/Desktop/NIKLAS/.zeus-system/WIKI_SCHEMA.md`
Capture: page types (source/entity/concept/synthesis/idea/project/atom/bundle), required frontmatter fields, lens taxonomy.

**Step 2: Sample NIKLAS atom**

Run: `ls ~/Desktop/NIKLAS/wiki/atoms/ | head -1` to pick one; then `cat` it.
Capture: actual frontmatter shape vs documented schema. They may differ.

**Step 3: Sample Brain Permanent note**

Run: `ls ~/Desktop/Brain/02-Permanent/ | head -1`; then `cat`.
Capture: Brain's frontmatter (per Cornelius CLAUDE.md: `created`, `updated`, `created_by`, `updated_by`, `agent_version`).

**Step 4: Write AUDIT.md**

Document field-by-field mapping. Identify:
- Direct map (NIKLAS `created` → Brain `created`)
- Lossy fields (NIKLAS `lens`, `confidence`, `explored` → drop or stuff into tags?)
- Required-by-Brain-but-missing-in-NIKLAS (`created_by`, `agent_version`)
- Reverse (NIKLAS has, Brain doesn't)

**Step 5: Commit**

```bash
cd ~/Cornelius
git checkout personal-config
git add resources/niklas-migration/AUDIT.md
git commit -m "docs: audit NIKLAS schema vs Brain schema for migration"
```

---

### Task 2: Build atom-diff script (TDD)

**Files:**
- Create: `~/Cornelius/resources/niklas-migration/diff_atoms.py`
- Create: `~/Cornelius/resources/niklas-migration/test_diff_atoms.py`
- Create: `~/Cornelius/resources/niklas-migration/fixtures/niklas_sample/atom_unique.md`
- Create: `~/Cornelius/resources/niklas-migration/fixtures/niklas_sample/atom_overlap.md`
- Create: `~/Cornelius/resources/niklas-migration/fixtures/brain_sample/atom_overlap.md`

**Step 1: Write failing test for filename overlap detection**

```python
# test_diff_atoms.py
import pytest
from pathlib import Path
from diff_atoms import diff_atoms

FIXTURES = Path(__file__).parent / "fixtures"

def test_diff_detects_unique_files():
    niklas = FIXTURES / "niklas_sample"
    brain = FIXTURES / "brain_sample"
    result = diff_atoms(niklas_dir=niklas, brain_dir=brain)
    assert result.unique_to_niklas == ["atom_unique.md"]
    assert result.overlapping == ["atom_overlap.md"]
```

**Step 2: Create fixtures**

`fixtures/niklas_sample/atom_unique.md`:
```markdown
---
title: Unique atom
type: atom
---
Body text.
```

`fixtures/niklas_sample/atom_overlap.md` + `fixtures/brain_sample/atom_overlap.md`:
```markdown
---
title: Overlapping atom
type: atom
---
Body text.
```

**Step 3: Run test — expect FAIL**

```bash
cd ~/Cornelius/resources/niklas-migration
python -m pytest test_diff_atoms.py::test_diff_detects_unique_files -v
```
Expected: `ModuleNotFoundError: No module named 'diff_atoms'`

**Step 4: Implement minimal `diff_atoms.py`**

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class DiffResult:
    unique_to_niklas: list[str]
    overlapping: list[str]

def diff_atoms(niklas_dir: Path, brain_dir: Path) -> DiffResult:
    niklas_names = {p.name for p in niklas_dir.glob("*.md")}
    brain_names = {p.name for p in brain_dir.glob("*.md")}
    return DiffResult(
        unique_to_niklas=sorted(niklas_names - brain_names),
        overlapping=sorted(niklas_names & brain_names),
    )
```

**Step 5: Run test — expect PASS**

```bash
python -m pytest test_diff_atoms.py -v
```

**Step 6: Add content-hash test for overlapping-but-different**

```python
def test_diff_detects_content_drift_in_overlapping():
    # Two files with same name but different body should be flagged as drift
    result = diff_atoms(niklas_dir=FIXTURES/"niklas_drift", brain_dir=FIXTURES/"brain_drift")
    assert result.drifted == ["atom_drift.md"]
```

Add `drifted: list[str]` field to `DiffResult`. Compute via sha256 of body (skip frontmatter).

**Step 7: Run real diff against live data**

```bash
python diff_atoms.py \
  --niklas ~/Desktop/NIKLAS/wiki/atoms \
  --brain ~/Desktop/Brain/02-Permanent \
  --output diff_report.json
```

**Step 8: Commit**

```bash
git add resources/niklas-migration/
git commit -m "feat(niklas-migration): atom diff with overlap + drift detection"
```

---

### Task 3: Build frontmatter reconciler (TDD)

**Files:**
- Create: `~/Cornelius/resources/niklas-migration/reconcile_frontmatter.py`
- Create: `~/Cornelius/resources/niklas-migration/test_reconcile_frontmatter.py`

**Step 1: Failing test for required Brain fields**

```python
def test_reconciler_adds_missing_brain_fields():
    niklas_text = """---
title: Test
type: atom
created: 2026-04-12
---

Body."""
    result = reconcile(niklas_text)
    assert "created_by: niklas-migration" in result
    assert "agent_version: 03.26" in result
    assert "updated:" in result
```

**Step 2: Run — expect FAIL**

**Step 3: Implement reconciler**

```python
import re
from datetime import date

def reconcile(text: str, agent_version: str = "03.26") -> str:
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not fm_match:
        raise ValueError("no frontmatter")
    fm = fm_match.group(1)
    body = text[fm_match.end():]
    if "created_by:" not in fm:
        fm += "\ncreated_by: niklas-migration"
    if "updated_by:" not in fm:
        fm += "\nupdated_by: niklas-migration"
    if "agent_version:" not in fm:
        fm += f"\nagent_version: {agent_version}"
    if "updated:" not in fm:
        fm += f"\nupdated: {date.today().isoformat()}"
    return f"---\n{fm}\n---\n{body}"
```

**Step 4: Failing test for NIKLAS-specific fields preserved**

```python
def test_reconciler_preserves_niklas_lens():
    niklas_text = """---
title: X
lens: dossier
confidence: 0.8
---

Body."""
    result = reconcile(niklas_text)
    assert "lens: dossier" in result
    assert "confidence: 0.8" in result
```

**Step 5: Run + iterate until passes**

**Step 6: Commit**

```bash
git add resources/niklas-migration/
git commit -m "feat(niklas-migration): frontmatter reconciler preserves NIKLAS fields"
```

---

### Task 4: Build migration script with --dry-run (TDD)

**Files:**
- Create: `~/Cornelius/resources/niklas-migration/migrate.py`
- Create: `~/Cornelius/resources/niklas-migration/test_migrate.py`

**Step 1: Failing test for dry-run idempotency**

```python
def test_dry_run_does_not_write(tmp_path):
    src = tmp_path / "niklas"; src.mkdir()
    (src / "test.md").write_text("---\ntitle: T\n---\nbody")
    dst = tmp_path / "brain"; dst.mkdir()
    migrate(src=src, dst=dst, dry_run=True)
    assert list(dst.iterdir()) == []  # nothing written
```

**Step 2: Run — expect FAIL**

**Step 3: Implement**

```python
from pathlib import Path
import shutil
from reconcile_frontmatter import reconcile

def migrate(src: Path, dst: Path, dry_run: bool = True):
    plan = []
    for md in src.glob("*.md"):
        target = dst / md.name
        if target.exists():
            plan.append(("skip-exists", md))
            continue
        plan.append(("migrate", md))
        if not dry_run:
            target.write_text(reconcile(md.read_text()))
    return plan
```

**Step 4: Add apply-mode test**

```python
def test_apply_writes_with_reconciled_frontmatter(tmp_path):
    src = tmp_path / "niklas"; src.mkdir()
    (src / "test.md").write_text("---\ntitle: T\n---\nbody")
    dst = tmp_path / "brain"; dst.mkdir()
    migrate(src=src, dst=dst, dry_run=False)
    written = (dst / "test.md").read_text()
    assert "created_by: niklas-migration" in written
    assert "body" in written
```

**Step 5: Run + iterate**

**Step 6: CLI wrapper**

```python
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--src", required=True)
    p.add_argument("--dst", required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    plan = migrate(Path(args.src), Path(args.dst), dry_run=not args.apply)
    for action, path in plan:
        print(f"{action}\t{path.name}")
```

**Step 7: Commit**

```bash
git add resources/niklas-migration/
git commit -m "feat(niklas-migration): dry-run + apply migration script"
```

---

### Task 5: Run dry-run against live NIKLAS

**Step 1: Execute dry-run**

```bash
cd ~/Cornelius/resources/niklas-migration
python migrate.py \
  --src ~/Desktop/NIKLAS/wiki/atoms \
  --dst ~/Desktop/Brain/02-Permanent \
  > dry_run_report.txt
wc -l dry_run_report.txt
grep -c "^migrate" dry_run_report.txt
grep -c "^skip-exists" dry_run_report.txt
```

Expected output: roughly 3,676 lines total. Numbers should approximately match: `migrate` count = net-new atoms, `skip-exists` count ≈ overlapping notes.

**Step 2: Eyeball dry_run_report.txt**

Manually review a sample of 10-20 `migrate` entries — confirm they really are net-new (search Brain for the title to double-check).

**Step 3: Pause for Erich review**

Don't proceed to apply without Erich confirming the dry-run delta looks correct. The numbers might surface unexpected dedup gaps (case sensitivity, frontmatter-only overlaps, etc.).

**Step 4: Commit the report**

```bash
git add resources/niklas-migration/dry_run_report.txt
git commit -m "chore(niklas-migration): dry-run report against live NIKLAS"
```

---

### Task 6: Apply migration + freeze NIKLAS

**Step 1: Backup Brain Permanent state**

```bash
cp -R ~/Desktop/Brain/02-Permanent ~/Desktop/Brain/02-Permanent.pre-niklas-migration
```

**Step 2: Apply migration**

```bash
cd ~/Cornelius/resources/niklas-migration
python migrate.py \
  --src ~/Desktop/NIKLAS/wiki/atoms \
  --dst ~/Desktop/Brain/02-Permanent \
  --apply
```

**Step 3: Verify count delta**

```bash
ls ~/Desktop/Brain/02-Permanent/*.md | wc -l
```

Expected: 3,677 + N (where N = `migrate` count from dry-run).

**Step 4: Freeze NIKLAS — write READONLY marker**

Create `~/Desktop/NIKLAS/READONLY.md`:

```markdown
---
status: frozen
frozen_at: 2026-05-11
reason: Atoms migrated to ~/Desktop/Brain/02-Permanent on 2026-05-11. NIKLAS is now read-only legacy.
---

# NIKLAS — READ-ONLY

All atomic insights migrated to `~/Desktop/Brain/02-Permanent`.
For new captures, use the unified Brain.
This vault remains as historical reference and `raw/` source archive.
```

**Step 5: Commit Brain repo + Cornelius repo**

```bash
cd ~/Desktop/Brain
git add 02-Permanent/
git commit -m "feat: import NIKLAS atoms (net-new only, schema reconciled)"
git push

cd ~/Cornelius
git add resources/niklas-migration/
git commit -m "feat(niklas-migration): apply complete, NIKLAS frozen"
git push
```

**Step 6: Re-index FAISS + bootstrap BDG**

```bash
cd ~/Cornelius/resources/local-brain-search
./run_index.sh
cd ~/Cornelius/resources/brain-graph
./run_brain_graph.sh bootstrap
```

---

## Phase E — BERT-Driven Brainstorm (Tasks 7-16)

**Why:** With the unified Brain in place, drive a real new project through the BERT POSIT pipeline. Atoms graduate INTO Brain as they crystallize. Validates the front-end-as-backend stance — every artifact is a future Neo4j node, every wiki-link a future edge.

**Note:** This phase is process-heavy, not TDD-shaped. Tasks are runbook-style.

### Task 7: Name new project + scaffold workspace

**Files:**
- Create: `~/Desktop/BERT/{N}-2026_{NAME}/dev/{1-goals,2-experts,3-research,4-blueprint,5-moonshot,6-pressure-test,archive}/` (mirror BERT template)

**Step 1: Erich names the project**

Confirm name + auto-increment N (currently 5-2026_PG_RECORD exists at Desktop/BERT/; next would be `6-2026_{NAME}`).

**Step 2: Scaffold from BERT template**

```bash
TEMPLATE=/Volumes/ZEUS\ DRIVE/Zeus/Projects/2026/4-2026_BERT
NEW=~/Desktop/BERT/6-2026_{NAME}
mkdir -p "$NEW"
cp -R "$TEMPLATE/L1" "$NEW/L1"
cp "$TEMPLATE/HOW_THIS_WORKS.md" "$NEW/"
cp "$TEMPLATE/CLAUDE.md" "$NEW/"
```

**Step 3: Commit (BERT projects don't usually live in git, but worth a snapshot)**

Optional. Skip if Erich prefers clean Desktop.

---

### Task 8: Register new project with Bert

**Files:**
- Modify: `~/.bert/active_project.json`

**Step 1: Update active_project.json**

```json
{
  "project": "6-2026_{NAME}",
  "path": "/Users/erichroepke/Desktop/BERT/6-2026_{NAME}",
  "level": "L1",
  "currentStage": "1-goals",
  "latestVersion": "V1",
  "hasMap": false,
  "hasState": true,
  "devRoot": "/Users/erichroepke/Desktop/BERT/6-2026_{NAME}/dev",
  "updatedAt": "2026-05-11T00:00:00.000Z"
}
```

**Step 2: Verify Bert picks it up**

```bash
cat ~/.bert/active_project.json
```

---

### Task 9: Stage 1 — POSIT goal V1 (Bert writes, Erich pushes back)

**Step 1: Invoke `/bert`**

Bert auto-loads active_project, asserts goal_V1.md based on conversation context (no interrogation per IRON LAW).

**Step 2: Erich reviews in Obsidian**

Open `~/Desktop/BERT/6-2026_{NAME}/dev/1-goals/goal_V1.md` in Obsidian. Inline-comment, push back.

**Step 3: Bert writes goal_V2.md (NEVER overwrites V1)**

**Step 4: Iterate V2 → V3 until "YES, that's exactly it"**

**Step 5: Atoms surface during stage — graduate to Brain**

If a clear atomic insight emerges, run Cornelius `/graduate-insights` to lift it to `~/Desktop/Brain/02-Permanent/`.

---

### Task 10: Stage 2 — Expert discovery

**Step 1: Bert writes `expert_{slug}.md` for each discovered expert**

One file per expert. NEVER consolidated. Each cites Zeus EXPERTS at `~/Desktop/Brain/01-Sources/Experts/zeus/` (via symlink) when relevant.

**Step 2: Erich selects/rejects experts in Obsidian**

**Step 3: Bert writes goal_POST_EXPERT.md** synthesizing what the experts say about the goal.

**Step 4: Graduate expert profiles into Brain**

If the expert isn't already in Zeus EXPERTS, run `/extract-document-insights` on the source material that surfaced them.

---

### Task 11: Stage 3 — Deep research

**Step 1: Bert runs deep-research via MCP tools**

`/deep-research <topic>` Cornelius skill, OR `/research` Zeus skill. Cite all sources.

**Step 2: Atoms emerge during research — graduate continuously**

Insights captured to `02-Permanent/`, sources documented to `01-Sources/Articles/`.

**Step 3: Erich reviews research V1 → V2 in Obsidian**

---

### Task 12: Stage 4 — Blueprint

**Step 1: Bert drafts blueprint based on goals + experts + research**

Mermaid diagrams, architecture sketches. Lives in `dev/4-blueprint/blueprint_V1.md`.

**Step 2: Erich reviews + iterates**

---

### Task 13: Stage 5 — Moonshot (MANDATORY)

**Step 1: Bert applies What-If Filters (Zero, 10X, Remove, Invert, Self-serve, Always On)**

Reference: `/moonshot/02-whatif` skill from Erich's moonshot plugin.

**Step 2: Pick top 3 what-ifs → draft axiom**

`/moonshot/03-axiom` — one declarative belief that becomes the filter for every downstream decision.

**Step 3: Erich confirms axiom**

---

### Task 14: Stage 6 — Pressure test (MANDATORY)

**Step 1: Premortem**

Run `/moonshot/10-premortem`. Document expected failure modes.

**Step 2: Red team**

Two-agent dialectic via `/dialectic` (Cornelius skill). Committed-position adversarial argument.

**Step 3: Document tensions → may feed back into Stage 1-5**

Butterfly Effect Upstream: pressure-test discoveries can revise earlier stages. Revise upward before MAP.

---

### Task 15: Erich authors MAP at L1 root (Bert REFUSES to auto-generate)

**Files:**
- Create: `~/Desktop/BERT/6-2026_{NAME}/MAP_L1_M1.md`

**Step 1: Erich opens MAP_TEMPLATE_REFERENCE.md**

```bash
cat ~/Desktop/BERT/6-2026_{NAME}/L1/MAP_TEMPLATE_REFERENCE.md
```

**Step 2: Erich authors MAP**

Each mission has: What and Why + EF (Expert Floor proven path) + MS (Moonshot 10X path) + Merge Strategy + Citation Trail.

**Step 3: Decompose missions to child levels (L2, L3, ...)**

Each mission seeds a child level. Recurse to Stage 1 for each. Trees grow lopsided — branches verify independently.

---

### Task 16: Promote all atoms + MOC to Brain

**Step 1: Move MAP into Brain**

```bash
cp ~/Desktop/BERT/6-2026_{NAME}/MAP_L1_M1.md \
   ~/Desktop/Brain/04-Output/Projects/{NAME}/MAP.md
```

**Step 2: Create project MOC**

```bash
cat > ~/Desktop/Brain/03-MOCs/MOC\ -\ {NAME}.md <<EOF
---
created: 2026-05-11
type: moc
tags: [project, ${NAME}]
---

# MOC — ${NAME}

## Goal
[[Projects/${NAME}/goal_POST_EXPERT]]

## Experts consulted
- [[Experts/${NAME}/...]]

## Atomic insights
- [[atom_1]]
- [[atom_2]]

## MAP
[[Projects/${NAME}/MAP]]
EOF
```

**Step 3: Re-index FAISS + BDG**

```bash
~/Cornelius/resources/local-brain-search/run_index.sh
~/Cornelius/resources/brain-graph/run_brain_graph.sh bootstrap
```

**Step 4: Commit Brain repo**

```bash
cd ~/Desktop/Brain
git add 04-Output/Projects/{NAME}/ 03-MOCs/
git commit -m "feat: ship ${NAME} brainstorm output + MOC"
git push
```

---

## Phase F — Backend Swap-in (Tasks 17-25, DEFERRED)

**Why:** Today's FAISS + file-based BDG works but doesn't scale past ~50K notes and can't do real graph queries (Cypher patterns, shortest path, community detection). Trinity + Neo4j + Qdrant is the production backend. The swap is one-shot because Cornelius wrapper scripts already abstract the engines.

**Defer rationale:** Phase A-E delivers full functional value. Phase F is performance + scale. Only do when (a) Brain crosses 20K notes, OR (b) explicit Cypher queries are needed, OR (c) Erich wants to demo Trinity multi-agent collaboration.

### Task 17: Trinity Docker stack up

**Files:**
- Modify: `~/Trinity/.env` (set DEPLOY_ENV=local, etc.)

**Step 1: Audit Trinity install script**

```bash
cat ~/Trinity/install.sh
cat ~/Trinity/docker-compose.yml
```

**Step 2: Configure .env**

```bash
cp ~/Trinity/.env.example ~/Trinity/.env
# edit appropriately
```

**Step 3: docker compose up**

```bash
cd ~/Trinity
docker compose up -d
docker compose ps          # all containers healthy
```

**Step 4: Smoke test — Trinity health endpoint**

```bash
curl -s http://localhost:{TRINITY_PORT}/health | jq .
```

**Step 5: Commit local config**

```bash
cd ~/Trinity
git checkout -b personal-config
git push -u origin personal-config
# .env is gitignored; commit any non-sensitive config tweaks
```

---

### Task 18: Wire Cornelius to Trinity MCP

**Step 1: Add Trinity MCP server to Cornelius `.mcp.json`**

```bash
cp ~/Cornelius/.mcp.json.template ~/Cornelius/.mcp.json
# edit to add trinity server URL + auth
```

**Step 2: Verify mcp__trinity__list_agents tool surfaces**

In Claude Code: confirm tool appears in deferred tools.

**Step 3: Smoke call list_agents — confirm Cornelius can see Trinity agents**

---

### Task 19: Neo4j stand-up

**Step 1: Add neo4j to Trinity docker-compose.yml (if not already)**

```yaml
neo4j:
  image: neo4j:5
  environment:
    NEO4J_AUTH: neo4j/changeme
  ports: ["7474:7474", "7687:7687"]
  volumes:
    - neo4j-data:/data
```

**Step 2: docker compose up neo4j**

```bash
docker compose up -d neo4j
docker compose logs neo4j | head -20
```

**Step 3: Smoke test — Cypher hello world**

```bash
docker compose exec neo4j cypher-shell -u neo4j -p changeme "RETURN 1"
```

---

### Task 20: Export BDG → Cypher (TDD)

**Files:**
- Create: `~/Cornelius/resources/brain-graph/export_to_cypher.py`
- Create: `~/Cornelius/resources/brain-graph/test_export_to_cypher.py`

**Step 1: Failing test for node export**

```python
def test_export_creates_node_statements():
    bdg_json = {"nodes": [{"id": "atom-1", "layer": "insight", "title": "T"}]}
    cypher = export_to_cypher(bdg_json)
    assert "CREATE (:Atom {id: 'atom-1', layer: 'insight', title: 'T'})" in cypher
```

**Step 2: Run — expect FAIL**

**Step 3: Implement minimal**

```python
def export_to_cypher(bdg: dict) -> str:
    lines = []
    for node in bdg.get("nodes", []):
        props = ", ".join(f"{k}: {v!r}" for k, v in node.items() if k != "id")
        lines.append(f"CREATE (:Atom {{id: {node['id']!r}, {props}}})")
    return "\n".join(lines)
```

**Step 4: Add failing test for edges**

```python
def test_export_creates_edge_statements():
    bdg = {
      "nodes": [{"id": "a"}, {"id": "b"}],
      "edges": [{"from": "a", "to": "b", "type": "derives-from"}]
    }
    cypher = export_to_cypher(bdg)
    assert "MATCH (a:Atom {id: 'a'}), (b:Atom {id: 'b'}) CREATE (a)-[:DERIVES_FROM]->(b)" in cypher
```

**Step 5: Implement edge handling**

**Step 6: Commit**

```bash
git add resources/brain-graph/
git commit -m "feat(brain-graph): export to Cypher with TDD coverage"
```

---

### Task 21: Load Neo4j from BDG

**Step 1: Generate BDG snapshot**

```bash
cd ~/Cornelius/resources/brain-graph
./run_brain_graph.sh export-json > bdg_snapshot.json
```

**Step 2: Convert to Cypher**

```bash
python export_to_cypher.py bdg_snapshot.json > bdg.cypher
wc -l bdg.cypher
```

**Step 3: Load into Neo4j**

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p changeme < bdg.cypher
```

**Step 4: Smoke query — count nodes**

```bash
docker compose exec neo4j cypher-shell -u neo4j -p changeme \
  "MATCH (n) RETURN count(n) AS total"
```

Expected: matches BDG node count.

---

### Task 22: Qdrant stand-up

**Step 1: Add qdrant to Trinity docker-compose.yml**

```yaml
qdrant:
  image: qdrant/qdrant:latest
  ports: ["6333:6333"]
  volumes:
    - qdrant-data:/qdrant/storage
```

**Step 2: docker compose up qdrant**

**Step 3: Smoke test**

```bash
curl -s http://localhost:6333/collections | jq .
```

---

### Task 23: Migrate FAISS → Qdrant (TDD)

**Files:**
- Create: `~/Cornelius/resources/local-brain-search/qdrant_backend.py`
- Create: `~/Cornelius/resources/local-brain-search/test_qdrant_backend.py`

**Step 1: Failing test for upsert**

```python
def test_qdrant_upsert(qdrant_client):
    backend = QdrantBackend(client=qdrant_client, collection="brain")
    backend.upsert(id="note-1", vector=[0.1]*384, payload={"path": "p.md"})
    result = qdrant_client.retrieve(collection_name="brain", ids=["note-1"])
    assert result[0].payload["path"] == "p.md"
```

**Step 2: Implement minimal**

```python
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct

class QdrantBackend:
    def __init__(self, client, collection):
        self.client = client
        self.collection = collection

    def upsert(self, id, vector, payload):
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=id, vector=vector, payload=payload)],
        )
```

**Step 3: Add search test**

```python
def test_qdrant_search_returns_nearest():
    backend.upsert("a", [1,0,0]+ [0]*381, {"t":"A"})
    backend.upsert("b", [0,1,0]+ [0]*381, {"t":"B"})
    hits = backend.search(query=[1,0,0]+ [0]*381, limit=1)
    assert hits[0].payload["t"] == "A"
```

**Step 4: Implement search**

**Step 5: Migration script — re-embed Brain into Qdrant**

`migrate_faiss_to_qdrant.py` reads FAISS index, copies vectors + payloads into Qdrant.

**Step 6: Commit**

```bash
git add resources/local-brain-search/
git commit -m "feat(lbs): Qdrant backend with parity to FAISS"
```

---

### Task 24: Parity validation (BDG/Neo4j, FAISS/Qdrant)

**Step 1: Run 20-query benchmark against both backends**

`benchmark_parity.py` runs same queries through both BDG+Neo4j, compares top-10 result sets.

**Step 2: Run 20-query benchmark FAISS vs Qdrant**

Same idea — semantic search results should overlap >95%.

**Step 3: Document deltas**

If parity <95% on either, debug before cutover.

---

### Task 25: Cutover — update Cornelius wrapper scripts

**Files:**
- Modify: `~/Cornelius/resources/local-brain-search/run_search.sh` — flip backend to qdrant
- Modify: `~/Cornelius/resources/brain-graph/run_brain_graph.sh` — flip to neo4j

**Step 1: Update each wrapper to call new backend**

Add env var `BACKEND=qdrant` (or neo4j). Default stays FAISS/file for safety. Flip when ready.

**Step 2: Run `/coherence-sweep` against new backends**

```
/coherence-sweep
```

Expected: same staleness/lifecycle/tension report as pre-cutover (within noise).

**Step 3: Commit + push**

```bash
git add resources/
git commit -m "feat: cutover wrapper scripts to Qdrant + Neo4j backends"
git push
```

**Step 4: Update Brain `05-Meta/CHANGELOG.md`**

Note the cutover date, parity benchmark results, rollback procedure.

---

## Verification (overall)

Phase D done when:
- [ ] `~/Desktop/Brain/02-Permanent/` count = 3,677 + N (N from dry-run report)
- [ ] All migrated notes have Brain-required frontmatter
- [ ] NIKLAS has `READONLY.md` at root
- [ ] `~/Cornelius/resources/niklas-migration/` committed to `personal-config`
- [ ] FAISS + BDG re-indexed

Phase E done when:
- [ ] New project workspace at `~/Desktop/BERT/6-2026_{NAME}/`
- [ ] `~/.bert/active_project.json` points at new project
- [ ] All 6 dev/ stages have at least one version file
- [ ] MAP authored by Erich at L1 root
- [ ] MOC + project output + atoms in Brain
- [ ] Brain repo pushed

Phase F done when:
- [ ] Trinity Docker stack healthy
- [ ] Neo4j loaded from BDG with node count parity
- [ ] Qdrant loaded from FAISS with >95% search parity
- [ ] Cornelius wrappers cutover, `/coherence-sweep` passes
- [ ] Backend swap documented in `05-Meta/CHANGELOG.md`

---

## Anti-Goals

- Do not migrate NIKLAS `raw/` source layer — only `wiki/atoms/`. Sources stay frozen in NIKLAS as historical archive.
- Do not delete the `~/Cornelius/Brain/` original after migration to `~/Desktop/Brain/` — keep as untracked backup for 30 days, then user moves to Trash (NEVER `rm`).
- Do not stand up Trinity/Neo4j/Qdrant unless one of the three triggers fires (>20K notes, Cypher needed, demo).
- Do not commit secrets (`.env`, `.mcp.json`, API keys). Cornelius `.gitignore` already covers these.
- Do not push Brain content to public repos. zeus-brain stays private.
- Do not skip Stage 5 (moonshot) or Stage 6 (pressure-test) in BERT — IRON LAW.
- Do not let Bert auto-generate the MAP — Erich authors. IRON LAW.

---

## Execution Notes

**Dependencies / blocking order:**
- Phase D Tasks 1-6 sequential (each task feeds the next)
- Phase E Tasks 7-16 sequential (POSIT pipeline order matters)
- Phase F Tasks 17-25 mostly sequential, but Task 23 (Qdrant migrate) can run in parallel with Task 20-21 (Neo4j load)

**Branch strategy:**
- All Cornelius infra code goes to `personal-config` branch
- Brain content commits go to zeus-brain main branch
- Trinity tweaks go to Trinity's `personal-config` (when forked)

**Skill references:**
- @superpowers:executing-plans for task-by-task execution
- @superpowers:subagent-driven-development for parallel task dispatch
- @superpowers:test-driven-development for Tasks 2, 3, 4, 20, 23
- Cornelius `/graduate-insights` for atom promotion in Phase E
- Cornelius `/coherence-sweep` for Phase F validation
- `moonshot:02-whatif`, `moonshot:03-axiom`, `moonshot:10-premortem` for Phase E Stages 5-6
- `bert-chat` skill for the entire Phase E POSIT loop

**Estimated wall-clock effort (active engineering time):**
- Phase D: 4-6 hours (most in dry-run review)
- Phase E: 8-20 hours depending on project scope (brainstorm depth varies)
- Phase F: 8-12 hours (Docker + migrations + parity testing)
