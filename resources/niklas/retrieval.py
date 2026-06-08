"""Context-pack retrieval for Niklas."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .store import NiklasStore, utcnow


def build_context_pack(
    question: str,
    *,
    project_scope: str | None = None,
    limit: int = 8,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a compact, auditable context pack for a project question."""
    store = NiklasStore(db_path)
    nodes = store.search_nodes(question, project_scope=project_scope, limit=limit)
    node_ids = [node["id"] for node in nodes]
    relationships = store.get_relationships_for_nodes(node_ids, limit=max(25, limit * 4))
    duplicates = store.find_duplicates(project_scope=project_scope, limit=5)
    return {
        "question": question,
        "project_scope": project_scope,
        "generated_at": utcnow(),
        "method": "niklas-local-sqlite-keyword-v1",
        "nodes": nodes,
        "relationships": relationships,
        "duplicate_suggestions": duplicates,
    }
