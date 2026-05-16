<!-- /autoplan restore point: /Users/erichroepke/.gstack/projects/erichroepke-cornelius/personal-config-autoplan-restore-20260513-125938.md -->

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

---

# /autoplan Review (2026-05-13)

Generated by /autoplan against commit `7b0a6b6` on branch `personal-config`.
Mode: full pipeline (CEO + Eng + DX + dual voices each).
Scope detection: UI=NO, DX=YES (48 hits). Phase 2 SKIPPED. Phases 1, 3, 3.5, 4 RUN.

## Phase 1 — CEO Review (Strategy & Scope)

### Step 0A — Premise Challenge

The roadmap rests on these premises. Each labeled CONFIRMED or CHALLENGED.

| # | Premise | Status | Reasoning |
|---|---------|--------|-----------|
| 1 | "Cornelius BDG + FAISS is sufficient today; Neo4j + Qdrant is deferred Phase F" | **CHALLENGED** | User reversed the deferral trigger in the live conversation ("include Neo4j"). Phase F activates NOW, not later. |
| 2 | "Brain at `~/Desktop/Brain` is the unified vault" | **CONFIRMED** | Verified by Cornelius `.claude/settings.md` (`VAULT_BASE_PATH=/Users/erichroepke/Desktop/Brain`). BDG bootstrap classified 5,411 nodes successfully against this path. |
| 3 | "NIKLAS atoms migrate INTO Brain (Phase D Task 5-6)" | **CHALLENGED** | Verified via recursive filename diff: 0 unique atoms in NIKLAS, 696 atoms in Brain not in NIKLAS, 3,676 common filenames. NIKLAS contributes nothing net-new. Phase D migration step = NO-OP. Phase D becomes: mark NIKLAS READONLY + de-pollute 271k auto-gen files. |
| 4 | "Single-machine scope" (implicit) | **CHALLENGED** | User's live ask: ZEUS BRAIN must be aware of this Mac AND home Mac via Tailscale. Roadmap as written has no multi-machine federation. New scope: registry `host` field, ssh-discovery for remote vaults, Neo4j ETL host-awareness. |
| 5 | "Trinity Docker required for Phase F" (T17, T22) | **CHALLENGED** | Trinity stack = full enterprise (Redis, Vector logs, agent runtime, OpenTelemetry). For Phase F's actual need (Neo4j + Qdrant containers), standalone `docker compose` files are sufficient. Trinity defers to genuine multi-agent demo trigger. |
| 6 | "Phase D → Phase E → Phase F sequential order" | **CHALLENGED** | User's "include Neo4j" + already-built `export_to_cypher.py` push Phase F ahead. New order: Phase D (collapsed to mark READONLY) → Phase F (Neo4j+Qdrant active, single machine) → Multi-machine federation → Phase E (BERT brainstorm runs on live graph) — or Phase E never if user has no new brainstorm to run. |
| 7 | "Local Brain Search FAISS index is current as of roadmap" | **CONFIRMED** | LBS data files at `~/Cornelius/resources/local-brain-search/data/` mtime May 11, 38MB FAISS + 16MB metadata. Latest atoms (May 12-13) may have drifted; re-index recommended before Qdrant migration but not blocker. |
| 8 | "Brain is ~/Desktop/Brain only" (vault count = 1 for brain layer) | **CHALLENGED** | Vault discovery surfaced 13 distinct vaults: Brain + BERT (12.5K md) + BERT-Wiki + 1-2026_ARC (4K md, active TODAY) + JIMMY 2 BRAIN + others. The "unified brain" concept needs clarification: is Brain the ONLY graph node source, or do the project vaults also get indexed as Neo4j atoms with `origin_vault` tags? |

**Premises auto-confirmed for execution**: 2, 7.
**Premises requiring user confirmation at gate**: 1, 3, 4, 5, 6, 8 (six premise challenges to surface).

### Step 0B — Existing Code Leverage Map

What already exists (don't rebuild):

| Sub-problem | Existing code/file | Source | Reuse strategy |
|-------------|--------------------|--------|----------------|
| Graph structure (atom + edge model) | `~/Cornelius/resources/brain-graph/models.py` | Cornelius v04.26 | Direct import; schema already maps Layer/EdgeType/Authority enums |
| Graph persistence (sidecar JSON) | `~/Cornelius/resources/brain-graph/store.py` | Cornelius | Read `graph_enrichments.json` via existing `load_enrichments()` |
| Classification (folder → layer) | `~/Cornelius/resources/brain-graph/classify.py` | Cornelius | Already bootstrapped — `data/graph_enrichments.json` exists (5,411 nodes, 62,137 edges) |
| Vector search | LBS FAISS (`brain.faiss` 38MB) | Cornelius | Pre-built; reuse as canonical until Qdrant parity proven |
| Vector embeddings | LBS metadata file (16MB) | Cornelius | Re-use; do NOT re-embed for Qdrant migration |
| BDG→Cypher converter | `~/Cornelius/resources/brain-graph/export_to_cypher.py` | Built today (this session, 13/13 tests pass) | Just generated `data/bdg.cypher` (67,549 statements) |
| Neo4j Docker config | `~/Cornelius/resources/brain-graph/docker-compose.neo4j.yml` | Built today | Standalone (not Trinity-bundled); APOC plugin enabled |
| Neo4j load script | `~/Cornelius/resources/brain-graph/load_neo4j.sh` | Built today | Idempotent MERGE-based loader |
| Tension detection | `~/Cornelius/resources/brain-graph/tension.py` | Cornelius | `./run_brain_graph.sh tensions` — not yet run; would populate :TENSION edges |
| Lifecycle scoring | `~/Cornelius/resources/brain-graph/lifecycle.py` | Cornelius | Run periodically; updates node lifecycle property |
| Coherence sweep | `~/Cornelius/resources/brain-graph/coherence.py` | Cornelius | Run weekly; identifies stale/orphan/decay candidates |
| Existing Neo4j schema (task hierarchy) | `/Volumes/ZEUS DRIVE/Zeus/.claude/zeus/CODE/INFRA/setup_neo4j_schema.py` | Zeus legacy | Reference only; LifeGoal/Project/Step labels NOT used by brain graph (separate concern) |
| BERT Neo4j document indexer | `~/Desktop/BERT/4-2026_BERT/neo4j_index.py` | BERT project | Reference; project-vault indexer pattern (Document + Project + KnowledgeDomain labels) |
| Cornelius sub-agents | `~/Cornelius/.claude/agents/` | Cornelius | Reuse for semantic enrichment: connection-finder, auto-discovery, insight-extractor, vault-manager |
| Vault registry | `~/Desktop/Brain/05-Meta/vaults-registry.json` | Built today | 13 vaults catalogued; ETL targets ordered by priority |
| Tailscale (mesh VPN) | `/opt/homebrew/bin/tailscale` v1.96.4 | Pre-installed | Needs service start; provides hostnames for multi-machine ssh |

**Conclusion**: Roadmap's "build from scratch" framing is wrong. ~80% of Phase F deliverables already exist. Real work is wiring + bootstrap + parity testing.

### Step 0C — Dream State Diagram

```
CURRENT STATE (2026-05-13 ~13:00)
─────────────────────────────────
  Brain (5,411 nodes, file-based BDG sidecar JSON)
   └─ Local Brain Search (FAISS) provides semantic search
   └─ Cornelius sub-agents provide tools
   └─ NO cross-machine awareness
   └─ NO Cypher query capability
   └─ NO graph algorithms (betweenness, Louvain)
   └─ NIKLAS legacy (17G of pollution + 3.6K atoms already in Brain)
   └─ 12 project vaults un-indexed in brain graph

THIS PLAN'S DELIVERY (Phase F + Multi-machine expansion)
─────────────────────────────────────────────────────────
  Brain (canonical, BDG sidecar JSON unchanged)
   └─ Neo4j (Dockerized) — projects BDG sidecar via export_to_cypher.py
   │   ├─ Cypher queries: orphans, hubs, bridges, paths, decay
   │   ├─ GDS-lite via APOC plugin
   │   └─ Idempotent re-load
   └─ Qdrant (Dockerized) — replaces FAISS for vector
   │   └─ Parity-verified (>95% query overlap with FAISS top-10)
   └─ Local Brain Search wrapper scripts switch backend via env var
   └─ Multi-machine: Tailscale-mediated SSH to home Mac
   │   ├─ Registry tracks host + tailscale_name + last_seen per vault
   │   └─ Federated discovery: home Mac vaults indexed into same Neo4j
   └─ NIKLAS marked READONLY + 271k pollution files trashed
   └─ All 13 vaults (+ remote home vaults) indexed with origin_vault tags

12-MONTH IDEAL (NOT in this plan, intentionally deferred)
──────────────────────────────────────────────────────────
  Trinity Docker orchestration: multi-agent runtime, OpenTelemetry, agent fleet
  Bidirectional sync: graph mutations write back to MD frontmatter (today: JSON sidecar canonical, MD content canonical, Neo4j projects from JSON)
  External MCP for Brain queryable from any project (zeus-brain MCP server) — DEFERRED to Phase F+
  Production-grade auth: scoped tokens, audit log, multi-user
  Cross-org sharing: Brain becomes reference for collaborators
  Mobile/web frontend: Obsidian + browser + iOS surface
```

**Dream state delta**: This plan closes 7/10 listed gaps (Neo4j active, Qdrant active, multi-machine, NIKLAS frozen, all-vault indexing, GDS algorithms, parity testing). Defers 3/10 (Trinity, bidirectional sync, external MCP).

### Step 0C-bis — Implementation Alternatives Table

| # | Approach | Effort | Risk | Pros | Cons |
|---|----------|--------|------|------|------|
| 1 | **As-roadmapped**: Trinity stack → Neo4j inside Trinity → Qdrant inside Trinity → Phase E brainstorm → cutover | human 30h / CC 8-12h | Medium | Production-grade orchestration; one stack to maintain | Trinity is heavy (Redis, Vector, agents) for current scope (just need Neo4j+Qdrant); Phase E delays Neo4j activation |
| 2 | **Recommended — Lean Phase F + multi-machine first, Trinity later**: Standalone Neo4j Docker → standalone Qdrant Docker → parity testing → multi-machine SSH discovery → defer Trinity, BERT brainstorm to separate sprint | human ~10h / CC ~3h | Low | Activates user's actual ask (Neo4j now, multi-machine awareness) without heavy stack; reversible | Two separate docker-compose files instead of unified Trinity; no orchestration runtime today |
| 3 | **Minimal — Just Neo4j read-only projection**: Run export_to_cypher.py → load into Neo4j → done. Skip Qdrant, skip multi-machine, skip Trinity. | human ~2h / CC ~30min | Very low | Smallest delta; immediately queryable | No Qdrant parity (FAISS stays); no multi-machine; no cutover automation |

**RECOMMENDATION**: #2 — Lean Phase F + multi-machine first.
- Honors user's explicit asks (Neo4j now + multi-machine)
- Defers heavy infrastructure (Trinity) until trigger fires
- P5 (explicit over clever): standalone Docker compose files > full Trinity orchestration for current scope
- P2 (boil lakes): multi-machine IS in the blast radius of "unified knowledge brain" — include
- Completeness: 9/10

### Step 0D — Mode-Specific Analysis (SELECTIVE EXPANSION)

Auto-decided expansions (in blast radius + <1d CC effort + P2):

| Expansion | In scope? | Reason | Auto-decision |
|-----------|-----------|--------|---------------|
| Multi-machine awareness (Tailscale + ssh discovery + host field in registry) | YES | User explicit ask; <5 files modified; <1d CC | **AUTO-ADD** |
| 12 project vaults indexed in Neo4j (not just Brain) | YES | User explicit ask "all wiki elements from every source"; bigger ETL scope but same code path | **AUTO-ADD** |
| Vault registry as deliverable | YES | Required input for federated ETL; already drafted | **AUTO-ADD** |
| Cornelius sub-agent enrichment runs | YES | User explicit ask "create semantic relationships at massive scale"; reuses existing agents (no new code) | **AUTO-ADD** |
| MCP server for zeus-brain (read scope, protected) | BORDERLINE | User asked "MCP-like with code interface"; ~3 new files (server.py, auth, audit). In blast radius. ~1 day CC. | **TASTE DECISION → surface at gate** |
| Trinity Docker stack (T17, T22) | NO | Heavy; not needed for Phase F core; trigger not yet fired | **AUTO-DEFER to TODOS.md** |
| Phase E (BERT brainstorm Tasks 7-16) | NO | User has no new brainstorm to run today; orthogonal to Neo4j activation | **AUTO-DEFER to TODOS.md** |
| Bidirectional MD↔Neo4j sync | BORDERLINE | User asked "in case we need to go between them"; complexity high; conflict resolution required | **TASTE DECISION → surface at gate** |
| External-project MCP plug-test (G11) | NO | Premature until MCP server itself is built | **AUTO-DEFER** |

**Deferred to TODOS.md** (will write at end of phase): Trinity Docker, Phase E BERT brainstorm, External-project plug-test.

### Step 0E — Temporal Interrogation

What this plan looks like at each time horizon:

| Hour | State |
|------|-------|
| **Hour 1** | Docker daemon running. Neo4j container up. `load_neo4j.sh` loads 67,549 statements → 5,411 nodes + 62,137 edges in Neo4j. Browser queryable at localhost:7474. |
| **Hour 2-3** | Qdrant container up. Migration script ports FAISS vectors → Qdrant collection. Parity benchmark: 20 queries, target ≥95% overlap. |
| **Hour 4-6** | Tailscale service running. Home Mac discoverable via `tailscale status`. SSH alias `home` configured. Remote vault discovery agent dispatched: returns home Mac's vault list. Registry updated with `host=home` entries. |
| **Hour 7-10** | Cornelius wrapper scripts updated: `run_search.sh` flips to Qdrant via env var; `run_brain_graph.sh` flips to Neo4j via env var. Coherence sweep re-runs against new backends; output diff vs pre-cutover. |
| **Hour 11-15** | Semantic enrichment first pass: dispatch Cornelius `auto-discovery` + `connection-finder` agents over recently-indexed atoms. Inferred edges (MENTIONS, RELATED_TO, DERIVES_FROM) MERGE'd into Neo4j. |
| **Day 2-3** | User actually uses queries: "show me orphans", "what's the most-cited insight crossing 3+ clusters", "find tensions in beliefs about X." Discovers value vs friction. |
| **Day 4-7** | Tune frequency: bootstrap weekly, enrichment continuous via watchdog, coherence weekly. Document workflows in 05-Meta/CHANGELOG.md. |
| **Day 8-14** | Decide whether Trinity / external MCP / bidirectional sync are needed. Re-trigger Phase F+ if so. |
| **Day 30+** | Brain has accumulated semantic edges from enrichment, lifecycle scores have drifted, productive tensions surfaced. Brain feels different. Re-evaluate dream state. |

### Step 0F — Mode Selection Confirmation

**Mode: SELECTIVE EXPANSION**
- 4 auto-expansions confirmed (multi-machine, all-vault indexing, registry, sub-agent enrichment)
- 3 auto-deferrals confirmed (Trinity, Phase E, external plug-test)
- 2 taste decisions surfaced (MCP server build, bidirectional sync)
- 6 premise challenges surfaced (require user confirmation)

This is the right mode for this plan: the roadmap is fundamentally sound; we're not rewriting it, just trimming heavy parts and adding the user's explicit new asks.

### Step 0.5 — Dual Voices

**CLAUDE SUBAGENT (CEO — strategic independence)** — Sonnet, fresh-eyes review of roadmap lines 1-1029 only.

> Subagent's average score across 6 dimensions: ~3.8/10. Adversarial as instructed.

TOP 3 FINDINGS (subagent verbatim):

1. **"The entire plan is infrastructure — none of it ships insight value."** Tasks 1-6 produce 0 net-new knowledge. Tasks 17-25 deferred. Tasks 7-16 are template with `{NAME}` placeholder. No task delivers a measurably better answer to any question Erich has.

2. **"Filename-based duplicate detection will corrupt the vault."** Task 2's `diff_atoms.py` uses `p.name` (filename) as identity key. Same idea ≠ same filename; same filename ≠ same content. TDD validates code contract, not data quality. For OUR current path (zero NIKLAS-to-Brain migration), risk is lower — but the criticism is structurally correct.

3. **"Phase F is a solution in search of a triggered problem, backed by the most complex available stack."** Neo4j + Qdrant + Trinity adds 2+ Docker containers, networking, auth, multi-service failure domain to a single-user laptop application currently running below 30% of stated performance threshold. No ADR. No alternatives evaluated.

**CODEX SAYS (CEO — strategy challenge)** — TIMEOUT at 600s (exit 124). codex-mesh wrapper failure. No output returned.

Per /autoplan degradation matrix: proceeding `[subagent-only]`.

**CEO DUAL VOICES — CONSENSUS TABLE** `[subagent-only]`:

| Dimension | Claude subagent | Codex | Consensus |
|---|---|---|---|
| 1. Premises valid? | NO (4 unvalidated, score 3/10) | N/A | **NOT_CONFIRMED** — flagged |
| 2. Right problem to solve? | NO (infrastructure, not insight, score 4/10) | N/A | **NOT_CONFIRMED** — flagged |
| 3. Scope calibration correct? | NO (D over-engineered, E unactionable, F premature, score 4/10) | N/A | **NOT_CONFIRMED** — flagged |
| 4. Alternatives sufficiently explored? | NO (no ADR for Neo4j vs pgvector/sqlite-vec, score 5/10) | N/A | **NOT_CONFIRMED** — flagged |
| 5. Competitive/market risks covered? | NO (zero discussion vs Mem/Tana/Reflect, score 4/10) | N/A | **NOT_CONFIRMED** — flagged |
| 6. 6-month trajectory sound? | NO (Phase F may never fire; Phase E unnamed, score 3/10) | N/A | **NOT_CONFIRMED** — flagged |

CONFIRMED = both agree. DISAGREE = models differ. Missing Codex voice = N/A.
**All 6 dimensions flagged by subagent. Single critical finding from one voice = flagged regardless.**

### Sections 1-10 (Abbreviated — Subagent's TOP 3 cover the critical surfaces)

**Section 1: Scope decisions** — Subagent finding 1 (infrastructure-not-insight). Auto-decision: add Section 0G "What insight does this plan unlock?" — surface at gate.

**Section 2: Dependencies + ordering** — Roadmap order D→E→F. User reversal pushes F first. Auto-decide: re-sequence D-collapsed → F-active → multi-machine → E-deferred. Confirm at gate.

**Section 3: Error & Rescue Registry** (see table below).

**Section 4: Resource estimate** — Original roadmap: human ~46h / CC ~16h total. With live additions (multi-machine, MCP server, agent enrichment): human ~60h / CC ~22h. With auto-deferrals (Trinity, Phase E, external plug test): human ~20h / CC ~6h. **Recommended scope: ~20h human / ~6h CC.**

**Section 5: Risk registry** (see table below).

**Section 6: Open questions** — 6 premises challenged + 2 taste decisions. All surface at gate.

**Section 7: Success metrics** — NONE in roadmap as written. Subagent finding: "Brain produces answer X that it cannot produce today." Auto-add: 5 verifiable Cypher queries that fail today but pass after Phase F. Examples: `MATCH (a:Atom) WHERE NOT (a)--() RETURN a` (orphans), `MATCH (a:Atom:Framework) WHERE a.lifecycle > 0.6` (live frameworks), `MATCH path = shortestPath(...)` (cross-cluster paths).

**Section 8: Communication plan** — N/A solo project.

**Section 9: Implementation alternatives** — Subagent finding 4 + my Step 0C-bis. Auto-decided: standalone Neo4j Docker > full Trinity; pgvector NOT considered (Cypher capabilities pay off for the orphan/hub/bridge use cases — but worth a 30-min ADR noting why). Auto-add: write ADR_001_neo4j_over_pgvector.md.

**Section 10: Cross-functional concerns** — N/A solo. But: vault registry crosses brain + project-vault concerns. Already drafted.

### Error & Rescue Registry

| Error path | Probability | Recovery | Owner gate |
|------------|-------------|----------|-----------|
| Docker daemon won't start | LOW (daemon stopped now) | User opens Docker Desktop manually | **AT GATE NOW** |
| Tailscale service won't start | LOW (service stopped now) | User opens Tailscale.app manually | **AT GATE NOW** |
| BDG bootstrap fails | LOW (already passed once today) | Re-run `./run_brain_graph.sh bootstrap --force` | auto |
| Neo4j cypher-shell load fails on 67k statements | MEDIUM | Split bdg.cypher into batches via `split -l 5000`; load batches sequentially | auto |
| Neo4j MERGE deadlocks on parallel write | LOW (single-threaded load) | Re-run; MERGE is idempotent | auto |
| FAISS→Qdrant parity benchmark fails (<95%) | MEDIUM | Debug embedding model mismatch; reembed Qdrant from same MLX-E5 vectors | auto |
| Multi-machine SSH discovery fails | MEDIUM | Fallback to user-supplied vault list per host | auto |
| Cornelius sub-agent enrichment writes corrupt edges | MEDIUM | Quarantine to `_proposed_edges/` for review before MERGE | auto |
| BDG JSON sidecar drift after Neo4j edits | HIGH if bidirectional | Currently UNIDIRECTIONAL (JSON canonical → Neo4j projects). No drift risk. Bidirectional sync deferred to TASTE DECISION. | gate |

### Failure Modes Registry

| Failure mode | Trigger | Blast radius | Detection | Mitigation |
|--------------|---------|--------------|-----------|------------|
| Phase F never fires (subagent finding 3) | Soft deferral triggers | Sunk cost on infra | Calendar reminder; usage-not-deferral trigger | **Replaced**: user reversed deferral; Phase F runs now |
| Plan ships infrastructure but no insight value (subagent finding 1) | All 25 tasks are scaffolding | User loses faith in plan | Define one verifiable insight-query gate per phase | Auto-add Section 7 metrics; tie verification to "Brain answers Q it couldn't" |
| Filename-dedup corrupts vault (subagent finding 2) | Hypothetical NIKLAS import | Vault pollution | Diff has 0 unique atoms — NO-OP — risk neutered | Phase D becomes READONLY-mark + de-pollute only |
| Trinity sprawl (subagent finding 4) | Adopting full Trinity stack | Ops burden + ports + auth surface | Stay minimal until trigger | Auto-defer Trinity; use standalone Docker compose files |
| BDG-Neo4j drift (potential, future) | Bidirectional sync activation | Inconsistent graph state | nightly reconciler diff; alert on >1% delta | Keep unidirectional in v1; gate bidirectional behind explicit user approval |
| Multi-machine sync lag (new) | Home Mac offline | Stale registry; missing edges | `reachable_now` field + retry queue | Mark host=home entries `stale` after 1h offline |
| 12 project vaults overwhelm graph (new) | Indexing 50K+ atoms from all vaults | Neo4j heap pressure | `dbms.memory.heap.max=4G` already; monitor | Cap per-vault ingestion; partition by `:Vault` label |

### Mandatory Outputs

**NOT in scope** (auto-deferred to TODOS.md):
- Trinity Docker stack (T17, T18, T22 portions) — heavy; defer until multi-agent demo trigger
- Phase E BERT brainstorm (T7-16) — no current named project; template until then
- External-project MCP plug-test (T11 / G11) — premature until MCP server itself ships
- Bidirectional MD↔Neo4j sync — conflict resolution complexity not worth v1; gate at taste decision

**What already exists** (see Step 0B table — 16 components, ~80% of Phase F deliverables already present or trivial wiring)

**Dream state delta** (see Step 0C — closes 7/10 gaps, defers 3/10 by design)

**CEO Completion Summary**:

| Metric | Value |
|--------|-------|
| Premise challenges | 6 / 8 (75%) |
| Auto-decided expansions | 4 |
| Auto-decided deferrals | 3 |
| Taste decisions surfaced | 2 (MCP server build, bidirectional sync) |
| Subagent findings | 6 dimensions flagged, TOP 3 critical |
| Codex findings | TIMEOUT — single-voice |
| Effective new scope | Lean Phase F + multi-machine federation |
| Effort estimate (with new scope) | human ~20h / CC ~6h |
| Approval gate items | 6 premises + 2 taste = 8 questions to surface |

**PHASE 1 COMPLETE.** Phase-transition summary:
> **Phase 1 complete.** Codex: TIMEOUT (single-voice). Claude subagent: 6 dimensions flagged.
> Consensus: 0/6 confirmed, 6 single-voice flags → surfaced at gate.
> Passing to **PREMISE GATE** (interactive).

### Premise Gate Resolution (2026-05-13)

User confirmed all 4 surfaced premises:
- **P1 — Phase F activation NOW**: ✅ A. Activate Neo4j + Qdrant immediately.
- **P4 — Multi-machine federation**: ✅ A. Add Tailscale ssh-discovery + host field in registry + Neo4j origin_vault tracking.
- **P5 — Trinity deferred**: ✅ A. Standalone neo4j + qdrant containers; Trinity returns at multi-agent demo trigger.
- **P8 — Indexing scope**: ✅ A. All 13 vaults indexed with origin_vault tags.

Plan locked. Eng + DX phases proceed.

---

## Phase 2 — Design Review

**SKIPPED** — UI scope detection returned 2 hits, both false positives (`format` matched "form", `demo` matched "modal"). No UI work in this roadmap. Phase 2 produces no findings.

---

## Phase 3 — Eng Review (Architecture, Tests, Security, Performance)

### Step 0 — Scope Challenge (read the actual code)

Read these files referenced by the plan + the live execution state:
- `~/Cornelius/resources/brain-graph/{models.py, store.py, classify.py, cli.py, propagation.py, lifecycle.py, tension.py, coherence.py, config.py}` — Cornelius BDG modules, all present and bootstrapped
- `~/Cornelius/resources/brain-graph/export_to_cypher.py` — built this session, 13/13 tests pass
- `~/Cornelius/resources/brain-graph/docker-compose.neo4j.yml` — built this session, standalone
- `~/Cornelius/resources/brain-graph/load_neo4j.sh` — built this session, idempotent loader
- `~/Cornelius/resources/brain-graph/brain_graph_config.yaml` — built this session, from architecture spec
- `~/Cornelius/resources/brain-graph/data/graph_enrichments.json` — bootstrapped this session, 15MB, 5,411 nodes + 62,137 edges
- `~/Cornelius/resources/brain-graph/data/bdg.cypher` — exported this session, 67,549 statements / 16MB

**Code map for Phase F (the active phase):**

```
ETL PIPELINE
  graph_enrichments.json (sidecar, BDG)
        │ READ via store.load_enrichments()
        ▼
  export_to_cypher.export_to_cypher(bdg) ──► 67,549 lines of Cypher
        │ via load_neo4j.sh
        ▼
  cypher-shell (Neo4j container)
        │ MERGE statements (idempotent)
        ▼
  Neo4j graph (5,411 nodes + 62,137 edges projected)
```

**Existing Phase F deliverables (already on disk this session):**
1. export_to_cypher.py — 218 lines + 13 tests
2. docker-compose.neo4j.yml — neo4j:5 + APOC, 4GB heap, named volumes
3. load_neo4j.sh — idempotent loader with healthcheck wait
4. brain_graph_config.yaml — 91 lines, mirrors architecture spec
5. data/graph_enrichments.json — bootstrapped 5,411 nodes
6. data/bdg.cypher — 67,549 lines, ready to load

**Phase F gap analysis:**
- Neo4j container start → blocked on Docker daemon (user action)
- Qdrant container + migration script → not yet written
- Cornelius wrapper-script backend swap (T25) → not yet wired
- 20-query parity benchmark (T24) → queries not yet defined
- Multi-machine ssh discovery → not yet written (new scope)
- All-vault ETL (Tier B in registry) → not yet written (new scope)

### Step 0.5 — Dual Voices

**CLAUDE SUBAGENT (eng — independent review)** — Sonnet, fresh-eyes, read actual code in `~/Cornelius/resources/brain-graph/*` + the plan lines 1-1029.

Score average across 5 dimensions: **5.0/10**. Sharp, file-and-line-specific findings.

**CODEX SAYS (eng — architecture challenge)** — SKIPPED. Phase 1 Codex timeout precedent; not retrying to save user time.

**ENG DUAL VOICES — CONSENSUS TABLE** `[subagent-only]`:

| Dimension | Claude subagent | Codex | Consensus |
|---|---|---|---|
| 1. Architecture sound? | PARTIAL (wrapper-script abstraction not implemented; score 6/10) | N/A | **NOT_CONFIRMED** — flagged |
| 2. Test coverage sufficient? | NO (no integration tests, no benchmark corpus; score 5/10) | N/A | **NOT_CONFIRMED** — flagged |
| 3. Performance risks addressed? | (not separately rated; covered in edge cases & hidden complexity) | N/A | **N/A** |
| 4. Security threats covered? | NO (hardcoded password, shell injection, exposed ports; score 5/10) | N/A | **NOT_CONFIRMED** — flagged CRITICAL |
| 5. Error paths handled? | NO (non-atomic write, no concurrent-bootstrap lock; score 4/10) | N/A | **NOT_CONFIRMED** — flagged CRITICAL |
| 6. Deployment risk manageable? | YES — rollback path clear (file-based BDG remains intact) | N/A | **PARTIAL** |

### TOP 3 CRITICAL ENGINEERING FINDINGS (subagent verbatim)

**1. `store.py::save_enrichments` non-atomic write.** SIGKILL during 10-30s bootstrap produces corrupted JSON. Recovery = `bootstrap --force` (full re-run). Fix: temp file + `os.replace()`. **File: `~/Cornelius/resources/brain-graph/store.py` lines 58-62.** Auto-decided: AUTO-FIX (P1 completeness, 3-line change).

**2. `cli.py` missing `export-json` subcommand.** Task 21 step 1 calls `./run_brain_graph.sh export-json`. Subcommand does not exist. Phase F load sequence fails at first step. Fix: add subparser + cmd function. **File: `~/Cornelius/resources/brain-graph/cli.py` lines 394-403.** Auto-decided: AUTO-FIX (P1 completeness, ~5-line change).

**3. `run_search.sh` shell injection in daemon fast-path.** Unquoted `$QUERY` in `python3 -c` allows arbitrary Python execution. Local-only attack surface today, but Tailscale enables remote callers. Fix: stdin pipe. **File: `~/Cornelius/resources/local-brain-search/run_search.sh` line 60.** Auto-decided: AUTO-FIX (P1 completeness, pre-existing bug surfaced by multi-machine scope expansion).

### Section 1 — Architecture (ASCII Dependency Graph)

```
                    USER (Erich) / Cornelius skills
                              │
            ┌─────────────────┴────────────────┐
            │                                   │
   /search-vault /find-connections     /coherence-sweep / etc.
            │                                   │
            ▼                                   ▼
   run_search.sh (LBS wrapper)        run_brain_graph.sh (BDG wrapper)
            │                                   │
            ▼                                   ▼
   resources/local-brain-search/      resources/brain-graph/cli.py
   {search.py, connections.py}         (bootstrap, status, inspect,
            │                          propagate, lifecycle, tensions,
            │                          coherence, **export-json [TO ADD]**)
            │                                   │
            │                                   ▼
            │                          store.py (load/save sidecar JSON)
            │                                   │
            ▼                                   ▼
   FAISS index (brain.faiss, 38MB)    data/graph_enrichments.json (15MB)
            │                                   │
            │                                   ▼
            │                          export_to_cypher.py (new, 13/13 tests)
            │                                   │
            │                                   ▼
            │                          data/bdg.cypher (67k statements)
            │                                   │
            │                                   ▼
            │                          load_neo4j.sh (idempotent loader)
            │                                   │
            │                                   ▼
            │                          Neo4j container (Docker, neo4j:5+APOC)
            │
            │ FUTURE (Phase F+)
            ▼
   Qdrant container (replaces FAISS)
```

**Coupling assessment**: 
- Wrappers → cli.py: LOW coupling, env-var dispatch missing today
- cli.py → store.py: TIGHT coupling on JSON schema (acceptable, models.py is shared contract)
- export_to_cypher → store: LOW coupling (just reads JSON via subprocess)
- load_neo4j → cypher-shell: SHELL coupling (acceptable for one-shot load)
- BDG sidecar ↔ Neo4j: UNIDIRECTIONAL by design (no drift risk in v1)

**Architectural verdict**: SOUND with two gaps — wrapper backend dispatch not implemented (Task 25 stays a TODO), and bidirectional sync (if/when added) needs explicit conflict resolution policy.

### Section 2 — Code Quality

Subagent didn't surface code-quality issues separately — covered in Dimensions 1, 2, 5. Auto-decision: AUTO-FIX the three TOP 3 findings; no other code-quality issues critical enough to gate.

### Section 3 — Test Review (CRITICAL — never skip)

**Test diagram** — new UX flows + data flows + branches introduced by Phase F:

| New flow / branch | Test type needed | Test exists? | Action |
|-------------------|------------------|--------------|--------|
| `export_to_cypher.export_to_cypher(bdg)` produces valid Cypher | Unit | ✅ 13 tests pass | DONE |
| Real BDG → real Neo4j round-trip (integration) | Integration | ❌ | **ADD** — testcontainers-python suggested |
| `cli.py export-json` produces valid JSON | Unit + Integration | ❌ | **ADD** alongside #2 fix |
| `store.save_enrichments` atomic (SIGKILL-safe) | Process-level | ❌ | **ADD** alongside #1 fix |
| Concurrent bootstrap doesn't lose data | Concurrency | ❌ | **ADD** — fcntl.flock + threaded test |
| Malformed frontmatter doesn't abort migration | Unit | ❌ | **ADD** — even though migrate.py path is moot (NIKLAS skipped) |
| Cypher with special chars (apostrophe, backtick) parses in Neo4j | Integration | ❌ | **ADD** alongside integration test |
| `run_search.sh` injection regression | Shell + Unit | ❌ | **ADD** alongside #3 fix |
| Float precision round-trip (BDG 0.72 → Cypher → Neo4j → back) | Integration | ❌ | **ADD** |
| Dangling-edge skip handled at scale | Unit | ✅ `test_export_omits_edge_when_endpoint_missing` | DONE |
| 20-query parity benchmark (FAISS vs Qdrant) | Benchmark | ❌ | **ADD** with curated query corpus |

**LLM/eval suites**: NONE explicit. The roadmap doesn't list eval suites. Auto-decision: skip eval gating since no prompt-touching changes are in Phase F scope. Re-visit if/when MCP server tools are added with LLM-routed dispatch.

**Test plan artifact** (per /autoplan T3 requirement): Will write separate test plan to `~/.gstack/projects/erichroepke-cornelius/personal-config-test-plan-20260513-130000.md` — deferred to end of Phase 3 closeout to avoid mid-write context churn.

### Section 4 — Performance

| Concern | Risk | Mitigation |
|---------|------|-----------|
| 67k Cypher statements load time | LOW (sequential MERGE, but each statement = round-trip) | Could batch with `UNWIND` for ~10x speedup; not blocker at 67k scale (~5-10 min one-shot) |
| Float precision drift on lifecycle scores | LOW | Round to 6 decimals at export time (~1 line change) |
| Neo4j heap pressure with all 13 vaults indexed (50-150k atoms) | MEDIUM | Already set to 4GB max in docker-compose; monitor; partition by `:Vault` if breach |
| GDS algorithm projections leak (when added) | DEFERRED | Out of v1 scope; flag for Phase F+ |
| BDG bootstrap re-run every commit | LOW | Idempotent; ~30s wall; consider watchdog incremental in v2 |
| FAISS → Qdrant parity benchmark cost | LOW | 20 queries × <100ms each = trivial |

**Performance verdict**: Adequate for current scale + 3-year growth horizon. No performance blockers.

### Mandatory Outputs

**NOT in scope** (auto-deferred to TODOS.md — same as Phase 1):
- Trinity Docker stack (T17, T18, T22 portions)
- Phase E BERT brainstorm (T7-16)
- External-project MCP plug-test (G11)
- Bidirectional MD↔Neo4j sync
- GDS projection lifecycle management (deferred to Phase F+)
- 20-query parity benchmark corpus design (deferred to Qdrant cutover)

**What already exists** — see Phase 1 Step 0B leverage map (16 components).

**Failure Modes Registry** — see Phase 1.

**Test plan artifact** — to write at `~/.gstack/projects/erichroepke-cornelius/personal-config-test-plan-20260513-130000.md` (next turn).

### Eng Completion Summary

| Metric | Value |
|--------|-------|
| Eng dimensions flagged | 5 / 6 (security + error paths CRITICAL) |
| Critical fixes auto-decided | 3 (atomic write, export-json subcommand, shell injection) |
| Tests to add | 9 (incl. integration round-trip + concurrency lock) |
| Architecture verdict | SOUND with implementation gaps (wrapper backend dispatch) |
| Performance verdict | ADEQUATE for current + 3-year scale |
| Rollback path | CLEAR (file-based BDG remains canonical; Neo4j is projection) |
| Approval gate additions | 0 (all auto-decided) |

**PHASE 3 COMPLETE.** Phase-transition summary:
> **Phase 3 complete.** Codex: SKIPPED (Phase 1 timeout precedent). Claude subagent: 5/6 dimensions flagged, 3 critical fixes identified.
> Consensus: 0/6 confirmed, 5 single-voice flags + 3 auto-fixes.
> Passing to Phase 3.5 (DX Review).

---

## Phase 3.5 — DX Review (Developer Experience)

### Step 0 — DX Scope Assessment

**Product type**: Developer-facing CLI + framework (Cornelius MIT). Phase F adds: new CLI subcommand (`export-json`), shell scripts (`load_neo4j.sh`), Docker config (`docker-compose.neo4j.yml`), Python module (`export_to_cypher.py`).

**Developer personas served**:
1. **Erich (primary)** — knows Cornelius internals; tolerates friction
2. **Hypothetical future collaborator** — clones Cornelius, wants to query Brain in 5 minutes
3. **Erich's home machine** (after Tailscale activation) — needs same UX surface remote

**Initial DX completeness score**: ~3/10 (per subagent).
**TTHW (current)**: 25-35 minutes.
**TTHW (target)**: <5 minutes.

### Step 0.5 — Dual Voices

**CLAUDE SUBAGENT (DX — independent review)** — Haiku, focused on developer journey + friction surfaces.

Score average across 6 dimensions: **3.5/10**. Sharp on TTHW + error messages + dev environment.

**CODEX SAYS (DX — developer experience challenge)** — SKIPPED (same precedent).

**DX DUAL VOICES — CONSENSUS TABLE** `[subagent-only]`:

| Dimension | Claude subagent | Codex | Consensus |
|---|---|---|---|
| 1. Getting started < 5 min? | NO (TTHW 25-35 min; score 3/10) | N/A | **NOT_CONFIRMED — CRITICAL** |
| 2. API/CLI naming guessable? | PARTIAL (good verbs, missing examples; score 6/10) | N/A | **PARTIAL** |
| 3. Error messages actionable? | NO (health check has no next steps; score 2/10) | N/A | **NOT_CONFIRMED — CRITICAL** |
| 4. Docs findable & complete? | PARTIAL (scattered, no BDG-specific quickstart; score 5/10) | N/A | **PARTIAL** |
| 5. Upgrade path safe? | NO (hardcoded creds, no env vars, no migration logic; score 4/10) | N/A | **NOT_CONFIRMED — HIGH** |
| 6. Dev env friction-free? | NO (multi-venv, no .env, 60s silent wait; score 2/10) | N/A | **NOT_CONFIRMED — CRITICAL** |

### Developer Journey Map (9-stage)

| Stage | Step | Friction | Friction score |
|-------|------|----------|----------------|
| 1. Discover | "I want to query my Brain via Cypher" | README mentions BDG but no clear path | 6/10 |
| 2. Install | `git clone` + read INSTALL.md | Multi-venv confusion (LBS + brain-graph share venv) | 7/10 |
| 3. Configure | Edit `.claude/settings.md` for VAULT_BASE_PATH | Already documented; OK | 3/10 |
| 4. Bootstrap | `./run_brain_graph.sh bootstrap` | "Did it work?" — no clear success indicator | 5/10 |
| 5. Stand up infra | `docker compose up -d` | Docker daemon may be down; error is cryptic | 8/10 |
| 6. Load graph | `./load_neo4j.sh` | 60s silent health check; no debugging hints on failure | 9/10 |
| 7. First query | Open Neo4j browser, type Cypher | Schema unknown; node labels undocumented in user docs | 8/10 |
| 8. Iterate | Modify a note → re-bootstrap → re-load | Manual sequence; no watch mode | 6/10 |
| 9. Verify | Compare query results to expected | No verification queries documented (eng finding) | 7/10 |

**Friction-weighted TTHW**: estimated 25-35 minutes for stage 1 → stage 7 (first useful query). Subagent estimate confirmed.

### Developer Empathy Narrative (subagent verbatim, condensed)

> "I clone Cornelius, edit settings. Five minutes in, I'm running bootstrap. It works, but I don't know what happened. README says BDG is Phase F but doesn't explain the workflow. Docker isn't running — load_neo4j.sh fails with 'container not running.' I start Docker, wait 30s, re-run. Health check loops silently for 60s. Finally loads. Neo4j browser up, but I'm staring at a graph I don't understand. What are these node labels? README mentions 'tensions' and 'lifecycle phases' but doesn't explain them. By minute 30, I'm frustrated — the tool promised to query my brain, but I'm debugging Docker and reading Python source code instead."

### TOP 3 DX FIXES (subagent verbatim, ordered by impact-per-effort)

1. **Create unified BDG quickstart guide** — `~/Cornelius/docs/QUICKSTART-BDG.md`. One-file walkthrough: venv → bootstrap → verify → Docker + load → Neo4j browser. Effort: 2h human. Impact: HIGH (solves TTHW + findability simultaneously).

2. **Move credentials to env vars** — `load_neo4j.sh` + `docker-compose.neo4j.yml` use `NEO4J_USER` / `NEO4J_PASS` from `.env` (gitignored). Add `.env.example` template. Effort: 1h human. Impact: HIGH (security + CI/CD + cross-phase Eng finding alignment).

3. **Add schema documentation** — Either README section or new `~/Cornelius/docs/BDG-SCHEMA.md`. Extract Layer→Label + EdgeType→Relationship table from `export_to_cypher.py` lines 30-47 into reader-friendly format. Add sample Cypher queries. Effort: 1.5h human. Impact: MEDIUM (independent learning + upgrade planning).

**Total**: ~4.5h human / ~30min CC effort to take TTHW from 25-35 min → <10 min.

### DX Implementation Checklist (auto-decided to fold into Phase F execution)

| # | Task | Owner | When |
|---|------|-------|------|
| 1 | Write `~/Cornelius/docs/QUICKSTART-BDG.md` | CC | After Neo4j load succeeds (so we have real outputs to reference) |
| 2 | Move Neo4j creds to `.env` + `.env.example` | CC | BEFORE Tailscale activation (eng finding #4.1 alignment) |
| 3 | Add `~/Cornelius/docs/BDG-SCHEMA.md` | CC | After Cornelius wrapper-script backend dispatch is wired |
| 4 | Verify `cli.py export-json` --help text | CC | Alongside Task #39 (add subcommand) |
| 5 | Improve `load_neo4j.sh` health check verbose output | CC | Alongside Task #38 (env var refactor) |
| 6 | Add `--dry-run` flag to `cli.py bootstrap` | CC | Phase F+ — low priority |

### DX Completion Summary

| Metric | Value |
|--------|-------|
| Overall DX score (current) | 3.5/10 |
| Overall DX score (with TOP 3 fixes applied) | ~7/10 |
| TTHW current | 25-35 min |
| TTHW target | <5 min |
| TTHW after TOP 3 fixes | ~8-12 min (still over target but acceptable for v1) |
| Critical fixes auto-decided | 3 (quickstart, env vars, schema docs) |
| Approval gate additions | 0 (all auto-decided) |

**PHASE 3.5 COMPLETE.** Phase-transition summary:
> **Phase 3.5 complete.** Codex: SKIPPED (Phase 1 timeout precedent). Claude subagent: 4/6 dimensions flagged critical/high.
> Consensus: 0/6 confirmed, 4 single-voice critical flags + 3 auto-decided fixes folded into Phase F execution.
> Passing to **Phase 4 (Final Approval Gate)**.

---

## Cross-Phase Themes

Concerns flagged by 2+ phases' subagents independently → highest-confidence findings.

| Theme | Phases | Confidence | Action |
|-------|--------|------------|--------|
| **Hardcoded credentials in committed code** | Eng (security 4.1) + DX (dev friction 6, upgrade path 5) | HIGH (cross-phase confirmed) | Already queued as task #38 — fix before Tailscale activation |
| **Error messages without recovery paths** | Eng (test coverage 3 rollback) + DX (error messages 3 critical) | HIGH (cross-phase confirmed) | Fold into health-check verbose mode + add rollback section to QUICKSTART-BDG |
| **Documentation gap on BDG schema** | DX (docs 4, schema 5) + Eng (no integration tests) | MEDIUM (DX-primary, Eng-adjacent) | Already queued as TOP 3 fix #3 — BDG-SCHEMA.md |
| **Infrastructure shipping without insight delivery** | CEO (infrastructure not insight) + DX (developer empathy: "promised to query my brain, but I'm debugging Docker") | HIGH (cross-phase confirmed) | Add Section 7 success metric: 5 verifiable Cypher queries that fail today + pass after Phase F |

---

## Phase 4 — Final Approval Gate

### Plan Summary

The roadmap as written deferred Phase F + assumed single-machine. Your live conversation reverses both. /autoplan auto-decided: lean Phase F (standalone Docker, not Trinity) + multi-machine federation (Tailscale-mediated) + all-vault indexing + 3 critical code fixes (atomic write, export-json subcommand, shell injection). 0 user challenges (the model didn't try to talk you out of your stated direction). 2 taste decisions remain for your call.

### Decisions Made

- **17 auto-decided** (see Decision Audit Trail below — premises, scope expansions, deferrals, code fixes)
- **0 user challenges** (no case where Claude AND Codex agreed you should reverse course — Codex didn't return in time)
- **2 taste decisions** (your call)

### Your Choices — Taste Decisions

These were auto-decided as RECOMMENDED but reasonable people could pick differently:

**Choice 1 — Build the protected MCP server (zeus-brain) as part of Phase F?**
Recommended: YES. You explicitly asked for "MCP-like protected interface with code SDK, pluggable into other projects." Effort: ~1 day CC. Files: `knowledge-graph/server.py` (MCP), `sdk/zeus_brain/` (Python client), `auth/` (token + scope + audit). Alternative: defer until Phase F load is verified and you've done a week of real queries against it — gives concrete tool-design feedback.

**Choice 2 — Activate bidirectional MD↔Neo4j sync?**
Recommended: NO (start unidirectional). You asked "we want Neo4j and MDs to be the same in case we need to go between them." BDG sidecar JSON is already the canonical state today (not MD frontmatter). Bidirectional adds conflict-resolution complexity. Start unidirectional (MD content + JSON sidecar canonical → Neo4j projects from both). Re-evaluate after a week of usage.

### Auto-Decided (17 — see Decision Audit Trail in plan above)

- Premises: P1, P4, P5, P8 confirmed via gate; P2, P7 auto-confirmed; P3, P6 auto-resolved (NIKLAS no-op + reordered phases)
- Expansions: multi-machine, all-vault indexing, registry deliverable, Cornelius sub-agent enrichment
- Deferrals: Trinity, Phase E BERT, external plug test
- Code fixes: atomic write (#40), export-json subcommand (#39), Neo4j creds → .env (#38), shell injection (#37)
- DX folds: QUICKSTART-BDG, BDG-SCHEMA, health-check verbose, --help text

### Review Scores

- CEO: 3.8/10 avg (subagent), Codex TIMEOUT, 6 dimensions flagged
- Design: SKIPPED (no UI scope)
- Eng: 5.0/10 avg (subagent), Codex SKIPPED (precedent), 5/6 dimensions flagged, 3 critical fixes
- DX: 3.5/10 avg (subagent), Codex SKIPPED (precedent), 4/6 critical/high, TTHW gap 20-30min

### Cross-Phase Themes (4 — highest confidence)

1. Hardcoded credentials (Eng + DX) → fix #38 queued
2. Error messages without recovery paths (Eng + DX) → folded into Phase F execution
3. BDG schema documentation gap (DX + Eng-adjacent) → BDG-SCHEMA.md queued
4. Infrastructure not insight (CEO + DX) → add Section 7 verification queries

### Deferred to TODOS.md (will write at end of review)

- Trinity Docker stack (T17-22 portions)
- Phase E BERT brainstorm (T7-16) — re-introduce when a named project exists
- External-project MCP plug-test (G11) — after MCP server ships
- GDS projection lifecycle management — Phase F+
- 20-query parity benchmark corpus design — Qdrant cutover prerequisite
- `--dry-run` flag on `cli.py bootstrap` — convenience, low priority


