"""zeus_brain.Client — direct-to-Neo4j client for in-process use."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

try:
    from neo4j import GraphDatabase  # type: ignore
except ImportError as e:
    raise ImportError(
        "zeus_brain requires the `neo4j` driver. Install via:\n"
        "  pip install -r resources/brain-graph/requirements-mcp.txt"
    ) from e

try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    load_dotenv = None  # type: ignore


_MUTATING_CLAUSES = re.compile(
    r"\b(CREATE|MERGE|DELETE|REMOVE|SET|DROP|DETACH|FOREACH|CALL\s+apoc\.(periodic|trigger|cypher\.runWrite))\b",
    re.IGNORECASE,
)


class Client:
    """Synchronous Neo4j-backed Brain client.

    Construct via `Client.from_env()` to pick up NEO4J_URI / NEO4J_USER / NEO4J_PASS
    from environment (or the brain-graph/.env file). For tests, pass values directly.
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        if not password:
            raise ValueError("Client requires a non-empty password")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._uri = uri

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "Client":
        """Build a Client from environment vars (.env supported if dotenv installed)."""
        if load_dotenv is not None:
            target = env_file or (Path(__file__).resolve().parents[2] / ".env")
            if target.exists():
                load_dotenv(target)
        return cls(
            uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            user=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASS", ""),
        )

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- core read ---------------------------------------------------------

    def _read(self, cypher: str, params: Optional[dict] = None) -> list[dict]:
        with self._driver.session() as session:
            result = session.run(cypher, params or {})
            return [dict(r) for r in result]

    # -- public API -------------------------------------------------------

    def status(self) -> dict:
        """Atom + edge counts."""
        atoms = self._read("MATCH (n:Atom) RETURN count(n) AS n")[0]["n"]
        edges = self._read("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
        return {"uri": self._uri, "atom_count": atoms, "edge_count": edges}

    def get(self, atom_id: str) -> Optional[dict]:
        """Fetch a single atom with its outbound edges."""
        rows = self._read(
            """
            MATCH (a:Atom {id: $id})
            OPTIONAL MATCH (a)-[r]->(b:Atom)
            RETURN a, collect({type: type(r), target: b.id, authority: r.authority}) AS out_edges
            """,
            {"id": atom_id},
        )
        if not rows:
            return None
        return {
            "atom": dict(rows[0]["a"]),
            "out_edges": [e for e in rows[0]["out_edges"] if e["target"] is not None],
        }

    def neighborhood(self, atom_id: str, depth: int = 2, limit: int = 100) -> list[dict]:
        """k-hop neighbors."""
        depth = max(1, min(int(depth), 4))
        rows = self._read(
            f"""
            MATCH path = (a:Atom {{id: $id}})-[*1..{depth}]-(b:Atom)
            WITH collect(DISTINCT b) AS neighbors
            RETURN [n IN neighbors[..{int(limit)}] | {{id: n.id, layer: n.layer}}] AS neighbors
            """,
            {"id": atom_id},
        )
        return rows[0]["neighbors"] if rows else []

    def orphans(self, limit: int = 50) -> list[dict]:
        return self._read(
            """
            MATCH (a:Atom) WHERE NOT (a)--()
            RETURN a.id AS id, a.layer AS layer, a.lifecycle AS lifecycle
            ORDER BY a.lifecycle DESC
            LIMIT $limit
            """,
            {"limit": int(limit)},
        )

    def hubs(self, min_degree: int = 5, limit: int = 25) -> list[dict]:
        return self._read(
            """
            MATCH (a:Atom)
            WITH a, COUNT { (a)--() } AS degree
            WHERE degree >= $min_degree
            RETURN a.id AS id, a.layer AS layer, degree
            ORDER BY degree DESC
            LIMIT $limit
            """,
            {"min_degree": int(min_degree), "limit": int(limit)},
        )

    def decay_candidates(self, days: int = 90, limit: int = 50) -> list[dict]:
        return self._read(
            """
            MATCH (a:Atom)
            WHERE a.staleness_score >= 0.3 OR a.lifecycle < 0.2
            RETURN a.id AS id, a.layer AS layer,
                   a.lifecycle AS lifecycle,
                   a.staleness_score AS staleness
            ORDER BY a.staleness_score DESC, a.lifecycle ASC
            LIMIT $limit
            """,
            {"limit": int(limit)},
        )

    def path(self, from_id: str, to_id: str, max_hops: int = 4) -> Optional[dict]:
        max_hops = max(1, min(int(max_hops), 8))
        rows = self._read(
            f"""
            MATCH path = shortestPath((a:Atom {{id: $from_id}})-[*..{max_hops}]-(b:Atom {{id: $to_id}}))
            RETURN [n IN nodes(path) | {{id: n.id, layer: n.layer}}] AS nodes,
                   [r IN relationships(path) | type(r)] AS edges,
                   length(path) AS hops
            """,
            {"from_id": from_id, "to_id": to_id},
        )
        return rows[0] if rows else None

    def graph_query(self, cypher: str, params: Optional[dict] = None) -> list[dict]:
        """Raw read-only Cypher (mutating clauses rejected)."""
        if _MUTATING_CLAUSES.search(cypher):
            raise PermissionError(
                "Mutating Cypher rejected by zeus_brain.Client. "
                "Use the Neo4j Bolt driver directly if you need write access."
            )
        return self._read(cypher, params)
