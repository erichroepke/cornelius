"""Brain Dependency Graph -> Neo4j Cypher exporter.

Reads `data/graph_enrichments.json` (BDG sidecar) and emits MERGE-based Cypher
statements that can be piped into `cypher-shell` for idempotent Neo4j loads.

Schema (mirrors BDG, see BRAIN-DEPENDENCY-GRAPH-ARCHITECTURE.md):
  Node labels: :Atom plus one of :Signal/:Impression/:Insight/:Framework/:Lens/:Synthesis/:Index
  Node id:     the relative vault path (e.g. "02-Permanent/foo.md")
  Edge types:  DERIVES_FROM / INSTANTIATES / REFERENCES / ASSOCIATES / TENSION / SUPERSEDES
  Tensions:    materialized as :TENSION relationships with `description` + `similarity` props

Usage:
    python export_to_cypher.py data/graph_enrichments.json > bdg.cypher
    cat bdg.cypher | docker exec -i <neo4j-container> cypher-shell -u neo4j -p <pw>

The output is idempotent: re-running against an unchanged BDG produces the same
graph state. Re-running after BDG updates upserts changed nodes/edges.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# =============================================================================
# MAPPINGS
# =============================================================================

_LAYER_TO_LABEL = {
    "signal": "Signal",
    "impression": "Impression",
    "insight": "Insight",
    "framework": "Framework",
    "lens": "Lens",
    "synthesis": "Synthesis",
    "index": "Index",
}

_EDGE_TYPE_TO_REL = {
    "derives-from": "DERIVES_FROM",
    "instantiates": "INSTANTIATES",
    "references": "REFERENCES",
    "associates": "ASSOCIATES",
    "tension": "TENSION",
    "supersedes": "SUPERSEDES",
}


# =============================================================================
# FORMATTING HELPERS
# =============================================================================

def _escape_cypher_string(s: str) -> str:
    """Escape single quotes for Cypher string literals (double them)."""
    return s.replace("'", "''")


def _format_value(v: Any) -> str:
    """Format a Python value as a Cypher literal."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return f"'{_escape_cypher_string(v)}'"
    if isinstance(v, (list, dict)):
        return f"'{_escape_cypher_string(json.dumps(v))}'"
    return f"'{_escape_cypher_string(str(v))}'"


def _props_set_clause(prefix: str, props: dict[str, Any], skip_keys: set[str] | None = None) -> str:
    """Build a comma-separated SET clause for properties."""
    skip = skip_keys or set()
    parts = [
        f"{prefix}.{k} = {_format_value(v)}"
        for k, v in props.items()
        if k not in skip and v is not None
    ]
    return ", ".join(parts)


# =============================================================================
# EXPORT
# =============================================================================

def export_to_cypher(bdg: dict) -> str:
    """Convert a BDG sidecar dict to a Cypher script.

    The script:
      1. Declares unique-id constraint on :Atom
      2. MERGEs all nodes with their layer-secondary label
      3. MERGEs all edges (skipping any whose endpoints aren't in nodes)
      4. MERGEs tension records as :TENSION relationships
    """
    statements: list[str] = []

    # --- Schema ---
    statements.append(
        "CREATE CONSTRAINT atom_id IF NOT EXISTS FOR (a:Atom) REQUIRE a.id IS UNIQUE;"
    )

    # --- Nodes ---
    nodes: dict[str, dict] = bdg.get("nodes", {})
    for atom_id, props in nodes.items():
        layer = props.get("layer", "insight")
        label = _LAYER_TO_LABEL.get(layer, "Insight")
        set_clause = _props_set_clause("n", props)
        id_lit = _format_value(atom_id)
        if set_clause:
            statements.append(
                f"MERGE (n:Atom:{label} {{id: {id_lit}}}) "
                f"ON CREATE SET {set_clause} "
                f"ON MATCH SET {set_clause};"
            )
        else:
            statements.append(f"MERGE (n:Atom:{label} {{id: {id_lit}}});")

    # --- Edges ---
    edges: dict[str, dict] = bdg.get("edges", {})
    for key, edge_props in edges.items():
        if "||" not in key:
            continue
        src, dst = key.split("||", 1)
        # Skip dangling edges (endpoint not in nodes)
        if src not in nodes or dst not in nodes:
            continue
        edge_type = edge_props.get("edge_type", "associates")
        rel = _EDGE_TYPE_TO_REL.get(edge_type, "ASSOCIATES")
        set_clause = _props_set_clause("r", edge_props, skip_keys={"edge_type"})
        src_lit = _format_value(src)
        dst_lit = _format_value(dst)
        stmt = (
            f"MATCH (s:Atom {{id: {src_lit}}}), (t:Atom {{id: {dst_lit}}}) "
            f"MERGE (s)-[r:{rel}]->(t)"
        )
        if set_clause:
            stmt += f" SET {set_clause}"
        statements.append(stmt + ";")

    # --- Tensions ---
    tensions: list[dict] = bdg.get("tensions", [])
    for tension in tensions:
        a = tension.get("note_a")
        b = tension.get("note_b")
        if not a or not b or a not in nodes or b not in nodes:
            continue
        props_for_set = {k: v for k, v in tension.items() if k not in {"note_a", "note_b"}}
        set_clause = _props_set_clause("r", props_for_set)
        a_lit = _format_value(a)
        b_lit = _format_value(b)
        stmt = (
            f"MATCH (s:Atom {{id: {a_lit}}}), (t:Atom {{id: {b_lit}}}) "
            f"MERGE (s)-[r:TENSION]->(t)"
        )
        if set_clause:
            stmt += f" SET {set_clause}"
        statements.append(stmt + ";")

    return "\n".join(statements)


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python export_to_cypher.py <graph_enrichments.json>", file=sys.stderr)
        sys.exit(1)
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"Error: {src} not found", file=sys.stderr)
        sys.exit(1)
    with src.open() as f:
        bdg = json.load(f)
    print(export_to_cypher(bdg))


if __name__ == "__main__":
    main()
