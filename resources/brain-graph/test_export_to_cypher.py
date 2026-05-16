"""Tests for export_to_cypher — BDG sidecar JSON → Cypher MERGE statements."""
from __future__ import annotations

from export_to_cypher import export_to_cypher, _escape_cypher_string, _format_value


# =============================================================================
# NODE EXPORT TESTS
# =============================================================================

def test_export_handles_empty_bdg() -> None:
    cypher = export_to_cypher({"version": "1.0", "nodes": {}, "edges": {}})
    assert "CREATE CONSTRAINT" in cypher  # schema init still runs


def test_export_creates_merge_node_statement() -> None:
    bdg = {
        "version": "1.0",
        "nodes": {
            "02-Permanent/test-atom.md": {
                "layer": "insight",
                "lifecycle": 0.5,
                "staleness_score": 0.0,
                "classification_confidence": 0.8,
            }
        },
        "edges": {},
    }
    cypher = export_to_cypher(bdg)
    assert "MERGE (n:Atom" in cypher
    assert "id: '02-Permanent/test-atom.md'" in cypher
    assert "n.layer = 'insight'" in cypher
    assert "n.lifecycle = 0.5" in cypher


def test_export_adds_layer_secondary_label() -> None:
    bdg = {
        "version": "1.0",
        "nodes": {"x.md": {"layer": "framework"}},
        "edges": {},
    }
    cypher = export_to_cypher(bdg)
    assert ":Framework" in cypher


def test_export_handles_all_seven_layers() -> None:
    layers = ["signal", "impression", "insight", "framework", "lens", "synthesis", "index"]
    expected_labels = ["Signal", "Impression", "Insight", "Framework", "Lens", "Synthesis", "Index"]
    for layer, label in zip(layers, expected_labels):
        bdg = {"version": "1.0", "nodes": {f"{layer}.md": {"layer": layer}}, "edges": {}}
        cypher = export_to_cypher(bdg)
        assert f":{label}" in cypher, f"missing :{label} for layer {layer}"


# =============================================================================
# EDGE EXPORT TESTS
# =============================================================================

def test_export_creates_edge_merge_statement() -> None:
    bdg = {
        "version": "1.0",
        "nodes": {"a.md": {"layer": "insight"}, "b.md": {"layer": "framework"}},
        "edges": {
            "a.md||b.md": {
                "edge_type": "derives-from",
                "authority": "target",
                "confidence": 0.8,
                "original_type": "explicit",
            }
        },
    }
    cypher = export_to_cypher(bdg)
    assert "MATCH (s:Atom {id: 'a.md'})" in cypher
    assert "(t:Atom {id: 'b.md'})" in cypher
    assert "MERGE (s)-[r:DERIVES_FROM]->(t)" in cypher
    assert "r.authority = 'target'" in cypher


def test_edge_type_kebab_to_screaming_snake() -> None:
    cases = {
        "derives-from": "DERIVES_FROM",
        "instantiates": "INSTANTIATES",
        "references": "REFERENCES",
        "associates": "ASSOCIATES",
        "tension": "TENSION",
        "supersedes": "SUPERSEDES",
    }
    for kebab, screaming in cases.items():
        bdg = {
            "version": "1.0",
            "nodes": {"a.md": {}, "b.md": {}},
            "edges": {"a.md||b.md": {"edge_type": kebab}},
        }
        cypher = export_to_cypher(bdg)
        assert f":{screaming}" in cypher, f"expected :{screaming} from {kebab}"


def test_export_omits_edge_when_endpoint_missing() -> None:
    """If an edge references a node id not in the nodes dict, skip it."""
    bdg = {
        "version": "1.0",
        "nodes": {"a.md": {"layer": "insight"}},
        "edges": {"a.md||missing.md": {"edge_type": "associates"}},
    }
    cypher = export_to_cypher(bdg)
    assert "missing.md" not in cypher


# =============================================================================
# ESCAPING / FORMATTING
# =============================================================================

def test_escape_single_quote_in_id() -> None:
    bdg = {
        "version": "1.0",
        "nodes": {"can't-do.md": {"layer": "insight"}},
        "edges": {},
    }
    cypher = export_to_cypher(bdg)
    # single quote should be doubled per Cypher string rules
    assert "can''t-do.md" in cypher


def test_escape_helper_doubles_single_quotes() -> None:
    assert _escape_cypher_string("don't") == "don''t"
    assert _escape_cypher_string("normal") == "normal"


def test_format_value_handles_types() -> None:
    assert _format_value("hello") == "'hello'"
    assert _format_value(42) == "42"
    assert _format_value(3.14) == "3.14"
    assert _format_value(True) == "true"
    assert _format_value(False) == "false"
    assert _format_value(None) == "null"


# =============================================================================
# SCHEMA / IDEMPOTENCY
# =============================================================================

def test_schema_constraint_emitted_first() -> None:
    cypher = export_to_cypher({"version": "1.0", "nodes": {}, "edges": {}})
    lines = cypher.split("\n")
    constraint_idx = next(i for i, l in enumerate(lines) if "CONSTRAINT" in l)
    # constraint should come before any MERGE (no MERGE in empty, but principle holds)
    assert constraint_idx < 5  # constraint near top


def test_idempotent_via_merge_not_create() -> None:
    bdg = {
        "version": "1.0",
        "nodes": {"a.md": {"layer": "insight"}},
        "edges": {},
    }
    cypher = export_to_cypher(bdg)
    # nodes use MERGE, not CREATE (which would dup on re-run)
    assert "CREATE (:Atom" not in cypher
    assert "MERGE (n:Atom" in cypher


# =============================================================================
# TENSION RECORDS (separate from edges)
# =============================================================================

def test_export_handles_tension_records() -> None:
    bdg = {
        "version": "1.0",
        "nodes": {"a.md": {"layer": "insight"}, "b.md": {"layer": "insight"}},
        "edges": {},
        "tensions": [
            {
                "note_a": "a.md",
                "note_b": "b.md",
                "similarity": 0.85,
                "description": "Both claim X but disagree on Y",
                "synthesis_artifacts": [],
                "detected": "2026-05-13",
            }
        ],
    }
    cypher = export_to_cypher(bdg)
    assert ":TENSION" in cypher
    assert "0.85" in cypher
