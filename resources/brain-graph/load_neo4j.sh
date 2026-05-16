#!/usr/bin/env bash
# Load BDG sidecar JSON into Neo4j via export_to_cypher.py + cypher-shell.
# Idempotent: re-running upserts via MERGE.
#
# Prereqs:
#   1. Docker Desktop running
#   2. neo4j container started: docker compose -f docker-compose.neo4j.yml up -d
#   3. data/graph_enrichments.json exists (run ./run_brain_graph.sh bootstrap first)
#
# Usage:
#   ./load_neo4j.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source .env if present (gitignored; copy from .env.example)
if [[ -f .env ]]; then
    set -o allexport
    # shellcheck disable=SC1091
    source .env
    set +o allexport
fi

ENRICHMENTS="data/graph_enrichments.json"
CYPHER_OUT="data/bdg.cypher"
CONTAINER="zeus-brain-neo4j"
# Read BRAIN_NEO4J_* (not NEO4J_*) to avoid Neo4j's auto-translation gotcha.
# See docker-compose.neo4j.yml note.
NEO4J_USER="${BRAIN_NEO4J_USER:-neo4j}"
NEO4J_PASS="${BRAIN_NEO4J_PASS:-}"

if [[ -z "$NEO4J_PASS" ]]; then
    echo "ERROR: BRAIN_NEO4J_PASS not set. Copy .env.example to .env and edit." >&2
    exit 1
fi

# 1. Verify prereqs
if [[ ! -f "$ENRICHMENTS" ]]; then
    echo "ERROR: $ENRICHMENTS not found. Run ./run_brain_graph.sh bootstrap first." >&2
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: container ${CONTAINER} not running. Start with:" >&2
    echo "  docker compose -f docker-compose.neo4j.yml up -d" >&2
    exit 1
fi

# 2. Generate Cypher
echo "Exporting BDG -> Cypher..."
source ../local-brain-search/venv/bin/activate
python export_to_cypher.py "$ENRICHMENTS" > "$CYPHER_OUT"
lines=$(wc -l < "$CYPHER_OUT")
echo "  Wrote $lines lines to $CYPHER_OUT"

# 3. Wait for Neo4j ready
echo "Waiting for Neo4j healthy..."
for i in {1..30}; do
    if docker exec "$CONTAINER" cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASS" "RETURN 1" >/dev/null 2>&1; then
        echo "  Neo4j ready"
        break
    fi
    sleep 2
    if [[ $i -eq 30 ]]; then
        echo "ERROR: Neo4j did not become ready in 60s" >&2
        exit 1
    fi
done

# 4. Load Cypher
echo "Loading $lines Cypher statements into Neo4j..."
docker exec -i "$CONTAINER" cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASS" \
    --format plain \
    < "$CYPHER_OUT"

# 5. Verify counts
echo ""
echo "=== Post-load verification ==="
docker exec "$CONTAINER" cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASS" "
MATCH (n:Atom) RETURN count(n) AS atom_count;
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC;
"

echo ""
echo "Done. Browser: http://localhost:7474 (login as $NEO4J_USER)"
