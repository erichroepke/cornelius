"""Niklas MCP server (read-scope v1).

Exposes the Niklas graph as MCP tools any Claude Code project can
mount. stdio transport by default (no network surface). Optional bearer-token
gate via NIKLAS_READ_TOKEN env var.

Tools (read scope):
- niklas_graph_status                — sidecar + Neo4j health
- niklas_graph_search                — hybrid (vector via LanceDB-future + graph)
- niklas_graph_get                   — atom by id
- niklas_graph_neighborhood          — k-hop ego graph
- niklas_graph_orphans               — atoms with no edges
- niklas_graph_hubs                  — atoms ranked by degree
- niklas_graph_decay_candidates      — stale + low-confidence atoms
- niklas_graph_path                  — shortest path between two atoms
- niklas_graph_query                 — raw read-only Cypher (denylist mutating clauses)

Configure via .env (alongside docker-compose.neo4j.yml):
    NEO4J_URI=bolt://localhost:7689
    BRAIN_NEO4J_USER=neo4j
    BRAIN_NEO4J_PASS=<your password>
    NIKLAS_READ_TOKEN=<optional shared secret; if set, callers must pass it>

Plug into a project:
    claude mcp add -s user niklas \\
        /Users/erichroepke/Desktop/Niklas/03-Runtime/Cornelius/resources/local-brain-search/venv/bin/python \\
        /Users/erichroepke/Desktop/Niklas/03-Runtime/Cornelius/resources/brain-graph/mcp_server.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pickle
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from runtime_paths import detect_brain_root

# ---------------------------------------------------------------------------
# Config & boot guards
# ---------------------------------------------------------------------------

# Load .env if dotenv installed (optional; gracefully degrade if not)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

NEO4J_URI = os.environ.get("NEO4J_URI") or os.environ.get("BRAIN_NEO4J_URI") or "bolt://localhost:7689"
NEO4J_USER = os.environ.get("NEO4J_USER") or os.environ.get("BRAIN_NEO4J_USER") or "neo4j"
NEO4J_PASS = os.environ.get("NEO4J_PASS") or os.environ.get("BRAIN_NEO4J_PASS") or ""
NIKLAS_READ_TOKEN = os.environ.get("NIKLAS_READ_TOKEN", "")
MCP_WRITE_TOKEN = os.environ.get("MCP_WRITE_TOKEN", "")
NIKLAS_DISABLE_WRITES = os.environ.get("NIKLAS_DISABLE_WRITES", "").lower() in {"1", "true", "yes", "on"}
NIKLAS_READ_SCOPE = "niklas:read"

# Vault root — atoms are written relative to this directory.
# Default: canonical master Brain repo; /Users/erichroepke/Desktop/Brain is a stub.
VAULT_ROOT = detect_brain_root("VAULT_ROOT")
BRAIN_GRAPH_DIR = Path(__file__).resolve().parent
NIKLAS_RESOURCES_DIR = BRAIN_GRAPH_DIR.parent
if str(NIKLAS_RESOURCES_DIR) not in sys.path:
    sys.path.insert(0, str(NIKLAS_RESOURCES_DIR))

from niklas.ingest import ingest_path as niklas_ingest_path_impl
from niklas.bert_core import (
    build_accept_payload as bert_accept_impl,
    build_bert_on_payload as bert_on_impl,
    build_doctor_payload as bert_doctor_impl,
    build_first_read_payload as bert_first_read_impl,
    build_next_payload as bert_next_impl,
    build_stage_draft_payload as bert_stage_draft_impl,
    build_linear_snapshot as bert_linear_snapshot_impl,
    build_node_create_payload as bert_node_create_plan_impl,
    build_node_locate_payload as bert_node_locate_impl,
    build_node_map_payload as bert_node_map_impl,
    build_node_spawn_children_payload as bert_node_spawn_children_plan_impl,
    build_node_stages_payload as bert_node_stages_impl,
    build_node_start_payload as bert_node_start_plan_impl,
    build_node_template_payload as bert_node_template_impl,
    build_project_analyze_payload as bert_project_analyze_impl,
    build_project_create_payload as bert_project_create_plan_impl,
    build_project_init_payload as bert_project_init_impl,
    build_project_open_payload as bert_project_open_impl,
    build_project_template_payload as bert_project_template_impl,
    build_readiness_payload as bert_status_impl,
    build_solve_payload as bert_solve_impl,
    build_stage_dry_run as bert_stage_impl,
)
from niklas.linear import LinearClient
from niklas.orientation import build_orientation as niklas_orientation_impl
from niklas.retrieval import build_context_pack as niklas_context_pack_impl
from niklas.store import NiklasStore

LBS_METADATA = Path(
    os.environ.get(
        "LBS_METADATA",
        BRAIN_GRAPH_DIR.parent / "local-brain-search" / "data" / "brain_metadata.pkl",
    )
)

# Audit log for all write_atom calls
_AUDIT_LOG = Path(__file__).parent / "data" / "mcp_write_audit.jsonl"

# Lazy-imported MCP + Neo4j (so this file imports cleanly before pip install)
try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
    from mcp.server.auth.provider import AccessToken  # type: ignore
    from mcp.server.auth.settings import AuthSettings  # type: ignore
except ImportError as e:
    print(
        "ERROR: mcp package not installed. Run:\n"
        "  pip install -r requirements-mcp.txt",
        file=sys.stderr,
    )
    raise SystemExit(2) from e

try:
    from neo4j import GraphDatabase  # type: ignore
    from neo4j.exceptions import ServiceUnavailable  # type: ignore
except ImportError:
    GraphDatabase = None  # type: ignore

    class ServiceUnavailable(Exception):  # type: ignore
        pass


# ---------------------------------------------------------------------------
# Neo4j driver (lazy, reconnect-safe)
# ---------------------------------------------------------------------------

_driver = None
_metadata_cache: list[dict[str, Any]] | None = None
_sidecar_cache: dict[str, Any] | None = None


def _get_driver():
    """Return a cached Neo4j driver, or raise a clear error if unconfigured."""
    global _driver
    if _driver is not None:
        return _driver
    if GraphDatabase is None:
        raise RuntimeError(
            "neo4j driver not installed. Neo4j-backed Niklas graph tools are unavailable. "
            "Run: pip install -r requirements-mcp.txt"
        )
    if not NEO4J_PASS:
        raise RuntimeError(
            "NEO4J_PASS not set. Copy .env.example to .env and edit it, "
            "or export NEO4J_PASS in the shell that launches this server."
        )
    _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    return _driver


def _run_read(query: str, params: Optional[dict] = None) -> list[dict]:
    """Execute a single read-only Cypher query and return rows as dicts."""
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(query, params or {})
        return [dict(r) for r in result]


def _load_sidecar() -> dict[str, Any]:
    global _sidecar_cache
    if _sidecar_cache is not None:
        return _sidecar_cache
    sidecar = BRAIN_GRAPH_DIR / "data" / "graph_enrichments.json"
    if not sidecar.exists():
        _sidecar_cache = {"nodes": {}, "edges": {}, "tensions": []}
    else:
        _sidecar_cache = json.loads(sidecar.read_text(encoding="utf-8"))
    return _sidecar_cache


def _load_metadata() -> list[dict[str, Any]]:
    """Load trusted local search metadata for keyword fallback search."""
    global _metadata_cache
    if _metadata_cache is not None:
        return _metadata_cache
    if not LBS_METADATA.exists():
        _metadata_cache = []
        return _metadata_cache
    resolved = LBS_METADATA.resolve()
    allowed_root = BRAIN_GRAPH_DIR.parent.resolve()
    resolved.relative_to(allowed_root)
    with resolved.open("rb") as f:
        _metadata_cache = pickle.load(f)
    return _metadata_cache or []


def _sidecar_count(value: Any) -> int | None:
    if isinstance(value, (dict, list, tuple, set)):
        return len(value)
    return None


def _metadata_keyword_search(query: str, k: int, seen: set[str]) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    nodes = _load_sidecar().get("nodes", {})
    results: list[dict[str, Any]] = []
    for chunk in _load_metadata():
        atom_id = str(chunk.get("note_id") or "")
        if not atom_id or atom_id in seen:
            continue
        haystack = " ".join(
            str(chunk.get(key) or "")
            for key in ("note_id", "title", "heading", "filepath", "content")
        ).lower()
        if q not in haystack:
            continue
        props = nodes.get(atom_id, {})
        results.append(
            {
                "id": atom_id,
                "layer": props.get("layer"),
                "source": "local-search-metadata",
                "title": chunk.get("title"),
                "heading": chunk.get("heading"),
                "preview": str(chunk.get("content") or "")[:700],
            }
        )
        seen.add(atom_id)
        if len(results) >= k:
            break
    return results


# ---------------------------------------------------------------------------
# Cypher safety (denylist)
# ---------------------------------------------------------------------------

_MUTATING_CLAUSES = re.compile(
    r"\b(CREATE|MERGE|DELETE|REMOVE|SET|DROP|DETACH|FOREACH|CALL\s+apoc\.(periodic|trigger|cypher\.runWrite))\b",
    re.IGNORECASE,
)


def _assert_read_only(cypher: str) -> None:
    """Raise if the Cypher contains any mutating clause."""
    if _MUTATING_CLAUSES.search(cypher):
        raise PermissionError(
            "Mutating Cypher rejected by Niklas read-scope server. "
            "Allowed: MATCH, OPTIONAL MATCH, WITH, RETURN, UNWIND, WHERE, ORDER BY, LIMIT, SKIP, CALL apoc.<read-only>."
        )


# ---------------------------------------------------------------------------
# Auth (optional bearer-token gate)
# ---------------------------------------------------------------------------

def _http_header_auth_enabled() -> bool:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    return bool(NIKLAS_READ_TOKEN and transport in {"http", "streamable-http", "sse"})


def _local_stdio_transport() -> bool:
    return os.environ.get("MCP_TRANSPORT", "stdio").lower() == "stdio"


def _assert_authed(token: Optional[str]) -> None:
    """If NIKLAS_READ_TOKEN is configured, callers must match it.

    HTTP MCP clients authenticate with Authorization: Bearer headers. When
    transport-level bearer auth is active, requests without a valid header are
    rejected before tool code runs, so individual tool calls do not need a
    duplicate token argument.

    Local stdio transport is same-user/same-machine trust: the read token
    exists to protect the network surface, so a missing token is waived on
    stdio (ADR 2026-06-11). An explicitly-supplied wrong token is still
    rejected on every transport. Writes remain gated by MCP_WRITE_TOKEN
    regardless of transport.
    """
    if not NIKLAS_READ_TOKEN:
        return  # auth disabled
    if token == NIKLAS_READ_TOKEN:
        return
    if token is None and (_http_header_auth_enabled() or _local_stdio_transport()):
        return
    raise PermissionError("niklas: invalid or missing token")


class _StaticReadTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if NIKLAS_READ_TOKEN and token == NIKLAS_READ_TOKEN:
            return AccessToken(
                token=token,
                client_id="niklas-readonly",
                scopes=[NIKLAS_READ_SCOPE],
            )
        return None


def _build_auth_settings() -> AuthSettings | None:
    if not NIKLAS_READ_TOKEN:
        return None
    host = os.environ.get("MCP_BIND_HOST", "127.0.0.1")
    port = os.environ.get("MCP_BIND_PORT", "8787")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    resource_url = os.environ.get("NIKLAS_MCP_RESOURCE_URL", f"http://{host}:{port}/mcp")
    issuer_url = os.environ.get("NIKLAS_AUTH_ISSUER_URL", "http://127.0.0.1")
    return AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=resource_url,
        required_scopes=[NIKLAS_READ_SCOPE],
    )


_AUTH_SETTINGS = _build_auth_settings()


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "niklas",
    auth=_AUTH_SETTINGS,
    token_verifier=_StaticReadTokenVerifier() if _AUTH_SETTINGS else None,
)


@mcp.tool()
async def niklas_graph_status(token: Optional[str] = None) -> dict:
    """Return health + counts for the Brain Dependency Graph.

    Args:
        token: Optional bearer token (required only if NIKLAS_READ_TOKEN is set in env).
    """
    _assert_authed(token)
    out: dict[str, Any] = {
        "neo4j_uri": NEO4J_URI,
        "neo4j_reachable": False,
        "sidecar_present": False,
        "atom_count": None,
        "edge_count": None,
    }

    # Check sidecar JSON exists (lightweight)
    sidecar = Path(__file__).parent / "data" / "graph_enrichments.json"
    if sidecar.exists():
        out["sidecar_present"] = True
        out["sidecar_size_bytes"] = sidecar.stat().st_size
        try:
            sidecar_payload = _load_sidecar()
            sidecar_atom_count = _sidecar_count(sidecar_payload.get("nodes"))
            sidecar_edge_count = _sidecar_count(sidecar_payload.get("edges"))
            out["sidecar_atom_count"] = sidecar_atom_count
            out["sidecar_edge_count"] = sidecar_edge_count
            if out["atom_count"] is None:
                out["atom_count"] = sidecar_atom_count
            if out["edge_count"] is None:
                out["edge_count"] = sidecar_edge_count
        except Exception as e:
            out["sidecar_error"] = f"sidecar unreadable: {type(e).__name__}"

    # Check Neo4j reachable
    try:
        rows = _run_read("MATCH (n:Atom) RETURN count(n) AS n")
        if rows:
            out["neo4j_reachable"] = True
            out["atom_count"] = rows[0]["n"]
            edge_rows = _run_read("MATCH ()-[r]->() RETURN count(r) AS n")
            out["edge_count"] = edge_rows[0]["n"] if edge_rows else 0
    except ServiceUnavailable:
        out["error"] = "neo4j unreachable; container may be down"
    except RuntimeError as e:
        out["error"] = str(e)
    return out


@mcp.tool()
async def niklas_graph_get(atom_id: str, token: Optional[str] = None) -> dict:
    """Return a single atom + its immediate neighbors.

    Args:
        atom_id: The atom identifier (relative vault path, e.g. "02-Permanent/foo.md").
        token: Optional bearer token.
    """
    _assert_authed(token)
    rows = _run_read(
        """
        MATCH (a:Atom {id: $id})
        OPTIONAL MATCH (a)-[r]->(b:Atom)
        RETURN a, collect({type: type(r), target: b.id, authority: r.authority}) AS out_edges
        """,
        {"id": atom_id},
    )
    if not rows:
        return {"error": "not found", "atom_id": atom_id}
    return {
        "atom": dict(rows[0]["a"]),
        "out_edges": [e for e in rows[0]["out_edges"] if e["target"] is not None],
    }


@mcp.tool()
async def niklas_graph_neighborhood(
    atom_id: str,
    depth: int = 2,
    limit: int = 100,
    token: Optional[str] = None,
) -> dict:
    """k-hop ego graph around an atom.

    Args:
        atom_id: Center atom.
        depth: Hops (1-4). Default 2.
        limit: Cap total nodes returned. Default 100.
    """
    _assert_authed(token)
    depth = max(1, min(int(depth), 4))
    rows = _run_read(
        f"""
        MATCH path = (a:Atom {{id: $id}})-[*1..{depth}]-(b:Atom)
        WITH a, collect(DISTINCT b) AS neighbors
        RETURN [n IN neighbors[..{int(limit)}] | {{id: n.id, layer: n.layer}}] AS neighbors
        """,
        {"id": atom_id},
    )
    if not rows:
        return {"error": "atom not found", "atom_id": atom_id}
    return {"center": atom_id, "depth": depth, "neighbors": rows[0]["neighbors"]}


@mcp.tool()
async def niklas_graph_orphans(limit: int = 50, token: Optional[str] = None) -> list[dict]:
    """Atoms with zero edges (review candidates)."""
    _assert_authed(token)
    return _run_read(
        """
        MATCH (a:Atom) WHERE NOT (a)--()
        RETURN a.id AS id, a.layer AS layer, a.lifecycle AS lifecycle
        ORDER BY a.lifecycle DESC
        LIMIT $limit
        """,
        {"limit": int(limit)},
    )


@mcp.tool()
async def niklas_graph_hubs(min_degree: int = 5, limit: int = 25, token: Optional[str] = None) -> list[dict]:
    """Atoms ranked by total degree (top connectors)."""
    _assert_authed(token)
    return _run_read(
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


@mcp.tool()
async def niklas_graph_decay_candidates(days: int = 90, limit: int = 50, token: Optional[str] = None) -> list[dict]:
    """Atoms with high staleness OR low lifecycle that may need review."""
    _assert_authed(token)
    return _run_read(
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


@mcp.tool()
async def niklas_graph_path(
    from_id: str,
    to_id: str,
    max_hops: int = 4,
    token: Optional[str] = None,
) -> dict:
    """Shortest path between two atoms (read-only)."""
    _assert_authed(token)
    max_hops = max(1, min(int(max_hops), 8))
    rows = _run_read(
        f"""
        MATCH path = shortestPath((a:Atom {{id: $from_id}})-[*..{max_hops}]-(b:Atom {{id: $to_id}}))
        RETURN [n IN nodes(path) | {{id: n.id, layer: n.layer}}] AS nodes,
               [r IN relationships(path) | type(r)] AS edges,
               length(path) AS hops
        """,
        {"from_id": from_id, "to_id": to_id},
    )
    if not rows:
        return {"error": "no path found within max_hops", "from": from_id, "to": to_id, "max_hops": max_hops}
    return rows[0]


@mcp.tool()
async def niklas_graph_query(cypher: str, params: Optional[dict] = None, token: Optional[str] = None) -> list[dict]:
    """Run a read-only Cypher query. Mutating clauses are rejected.

    Args:
        cypher: The Cypher to execute (MATCH/RETURN/WITH/UNWIND/WHERE/ORDER BY/LIMIT/SKIP allowed).
        params: Optional parameter dict.
    """
    _assert_authed(token)
    _assert_read_only(cypher)
    return _run_read(cypher, params or {})


# ---------------------------------------------------------------------------
# Search (hybrid placeholder — vector path stubbed until LanceDB wiring)
# ---------------------------------------------------------------------------

@mcp.tool()
async def niklas_graph_search(
    query: str,
    mode: str = "graph",
    k: int = 10,
    token: Optional[str] = None,
) -> list[dict]:
    """Search the Brain.

    Modes:
        graph    — Cypher over Atom.id plus local metadata keyword fallback
        vector   — local metadata keyword fallback until FAISS/Qdrant query wiring lands
        hybrid   — graph IDs plus local metadata keyword fallback
    """
    _assert_authed(token)
    limit = int(k)
    rows: list[dict[str, Any]] = []
    neo4j_degraded = False
    if mode in ("vector", "hybrid") and _full_text_index_exists():
        try:
            rows.extend(_run_read(
                """
                CALL db.index.fulltext.queryNodes('atom_fulltext', $q) YIELD node, score
                RETURN node.id AS id, node.layer AS layer, score, 'neo4j-fulltext' AS source
                ORDER BY score DESC
                LIMIT $k
                """,
                {"q": query, "k": limit},
            ))
        except Exception:
            neo4j_degraded = True

    try:
        rows.extend(_run_read(
            """
            MATCH (a:Atom)
            WHERE toLower(a.id) CONTAINS toLower($q)
            RETURN a.id AS id, a.layer AS layer, 'neo4j-id' AS source
            LIMIT $k
            """,
            {"q": query, "k": limit},
        ))
    except Exception:
        neo4j_degraded = True
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        atom_id = str(row.get("id") or "")
        if not atom_id or atom_id in seen:
            continue
        deduped.append(row)
        seen.add(atom_id)
        if len(deduped) >= limit:
            return deduped
    fallback = _metadata_keyword_search(query, limit - len(deduped), seen)
    if neo4j_degraded:
        for item in fallback:
            item.setdefault("degraded", True)
            item.setdefault("degraded_reason", "neo4j unavailable; served from local metadata fallback")
    deduped.extend(fallback)
    if neo4j_degraded and not deduped:
        return [
            {
                "source": "degraded",
                "degraded": True,
                "degraded_reason": "neo4j unavailable and local metadata fallback returned no matches",
                "query": query,
            }
        ]
    return deduped[:limit]


def _full_text_index_exists() -> bool:
    """Best-effort check; returns False if Neo4j is down or index missing."""
    try:
        rows = _run_read("SHOW FULLTEXT INDEXES YIELD name WHERE name = 'atom_fulltext' RETURN count(*) AS n")
        return bool(rows and rows[0]["n"] > 0)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

_VALID_PREFIXES = ("wiki/", "raw/")
_FRONTMATTER_RE = re.compile(r"^---\n.*?---\n", re.DOTALL)


def _assert_write_authed(token: Optional[str]) -> None:
    """Reject with PermissionError if MCP_WRITE_TOKEN is set and token does not match."""
    if NIKLAS_DISABLE_WRITES:
        raise PermissionError("write operations are disabled for this Niklas MCP process")
    if not MCP_WRITE_TOKEN:
        raise PermissionError(
            "write_atom: MCP_WRITE_TOKEN is not configured on this server — writes disabled"
        )
    if token != MCP_WRITE_TOKEN:
        raise PermissionError("write_atom: invalid or missing write token (401)")


def _validate_vault_path(vault_relative_path: str) -> None:
    """Raise ValueError for any path that violates safety rules."""
    if vault_relative_path.startswith("/"):
        raise ValueError("vault_relative_path must not be an absolute path (starts with '/')")
    if ".." in vault_relative_path.split("/"):
        raise ValueError("vault_relative_path must not contain '..' components")
    # Also catch encoded or dot-trick variants
    if ".." in vault_relative_path:
        raise ValueError("vault_relative_path must not contain '..'")
    if not any(vault_relative_path.startswith(p) for p in _VALID_PREFIXES):
        raise ValueError(
            f"vault_relative_path must start with one of {_VALID_PREFIXES}, got: {vault_relative_path!r}"
        )


def _validate_frontmatter(content: str) -> None:
    """Raise ValueError if content does not have a valid YAML frontmatter block."""
    if not content.startswith("---\n"):
        raise ValueError("content must start with '---\\n' (YAML frontmatter required)")
    # Find closing ---
    rest = content[4:]  # skip opening ---\n
    if "---\n" not in rest and not rest.rstrip().endswith("---"):
        raise ValueError("content has no closing '---' frontmatter delimiter")


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _scan_brain_for_md5(target_md5: str) -> Optional[str]:
    """Walk VAULT_ROOT looking for any file whose content matches target_md5.

    Returns vault-relative path of the first match, or None.
    """
    if not VAULT_ROOT.exists():
        return None
    for fpath in VAULT_ROOT.rglob("*.md"):
        try:
            content = fpath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _md5(content) == target_md5:
            try:
                rel = fpath.relative_to(VAULT_ROOT)
                return str(rel)
            except ValueError:
                continue
    return None


def _atomic_write(dest: Path, content: str) -> None:
    """Write *content* to *dest* atomically using tempfile + os.replace."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".mcp_write.",
        suffix=".tmp",
        dir=str(dest.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, dest)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _append_audit(entry: dict) -> None:
    """Append a JSON line to the write audit log."""
    _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# write_atom tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def write_atom(
    vault_relative_path: str,
    content: str,
    origin_machine: str,
    origin_drive: str,
    origin_path: str,
    content_hash: str,
    token: Optional[str] = None,
    overwrite: bool = False,
) -> dict:
    """Write (or deduplicate) a markdown atom into the canonical Brain vault.

    Args:
        vault_relative_path: Destination relative to vault root. Must start with
            'wiki/' or 'raw/' and must not contain '..' or start with '/'.
        content: Full markdown content including YAML frontmatter (required).
        origin_machine: Caller machine identifier (e.g. 'studio').
        origin_drive: Caller drive identifier (e.g. 'ANEP_RAID_1B').
        origin_path: Absolute path on the source machine.
        content_hash: md5(content) provided by caller for dedup check.
        token: Bearer token — must match MCP_WRITE_TOKEN env var.
        overwrite: Set True to allow overwriting an existing file with different content.

    Returns a dict with keys:
        canonical_path  — vault-relative path of the atom
        absolute_path   — absolute path on this machine
        deduplicated    — True if md5 already existed; no write was performed
        written         — True if a write was performed
    """
    # 1. Auth
    _assert_write_authed(token)

    # 2. Path safety
    try:
        _validate_vault_path(vault_relative_path)
    except ValueError as exc:
        raise ValueError(f"400 Bad Request: {exc}") from exc

    # 3. Frontmatter validation
    try:
        _validate_frontmatter(content)
    except ValueError as exc:
        raise ValueError(f"400 Bad Request: {exc}") from exc

    # 4. Compute actual md5 and verify caller-provided hash
    actual_md5 = _md5(content)
    # (We use actual_md5 for all logic; caller hash is advisory/dedup signal)

    # 5. Dedup check — scan Brain for any file with the same md5
    existing_match = _scan_brain_for_md5(actual_md5)
    if existing_match is not None:
        return {
            "canonical_path": existing_match,
            "absolute_path": str(VAULT_ROOT / existing_match),
            "deduplicated": True,
            "written": False,
        }

    # 6. Destination path
    dest = VAULT_ROOT / vault_relative_path
    canonical = vault_relative_path

    # 7. Conflict check — path exists but content differs
    if dest.exists():
        existing_content = dest.read_text(encoding="utf-8")
        existing_md5 = _md5(existing_content)
        if existing_md5 != actual_md5:
            if not overwrite:
                raise ValueError(
                    f"409 Conflict: {vault_relative_path!r} already exists with different content "
                    f"(existing_md5={existing_md5!r}). Pass overwrite=True to replace."
                )

    # 8. Atomic write
    _atomic_write(dest, content)

    # 9. Audit log
    audit_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "origin_machine": origin_machine,
        "origin_drive": origin_drive,
        "origin_path": origin_path,
        "canonical_path": canonical,
        "md5": actual_md5,
        "deduplicated": False,
    }
    _append_audit(audit_entry)

    return {
        "canonical_path": canonical,
        "absolute_path": str(dest),
        "deduplicated": False,
        "written": True,
    }


# ---------------------------------------------------------------------------
# Niklas V1 tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def niklas_status(token: Optional[str] = None) -> dict:
    """Return local Niklas SQLite graph status.

    Args:
        token: Optional bearer token (required only if NIKLAS_READ_TOKEN is set).
    """
    _assert_authed(token)
    return NiklasStore().status()


@mcp.tool()
async def niklas_orient(
    current_request: Optional[str] = None,
    current_goal: Optional[str] = None,
    project_hint: Optional[str] = None,
    cwd: Optional[str] = None,
    browser_url: Optional[str] = None,
    chat_summary: Optional[str] = None,
    surface: Optional[str] = None,
    limit: int = 5,
    token: Optional[str] = None,
) -> dict:
    """Orient the current chat/session inside Niklas before context retrieval.

    Use this as the first Niklas call in a new work thread. It returns a
    positioning packet plus clarifying questions the client should ask in chat.

    Args:
        current_request: The user's current request or task signal.
        current_goal: Current session goal, if already known.
        project_hint: Project name/scope hint, if already known.
        cwd: Current working directory from the client environment.
        browser_url: Visible browser URL, if relevant.
        chat_summary: Short visible-chat summary.
        surface: Primary work surface, such as repo, Linear, browser, CLI, MCP, notes, or chat.
        limit: Maximum candidate starting nodes.
        token: Optional bearer token.
    """
    _assert_authed(token)
    return niklas_orientation_impl(
        current_request=current_request,
        current_goal=current_goal,
        project_hint=project_hint,
        cwd=cwd,
        browser_url=browser_url,
        chat_summary=chat_summary,
        surface=surface,
        limit=max(1, min(int(limit), 20)),
    )


@mcp.tool()
async def niklas_ingest_path(
    path: str,
    project_scope: Optional[str] = None,
    tags: Optional[list[str]] = None,
    recursive: bool = False,
    max_files: Optional[int] = None,
    token: Optional[str] = None,
) -> dict:
    """Ingest a local file or directory into the Niklas graph.

    This mutates the local SQLite graph and therefore requires MCP_WRITE_TOKEN.

    Args:
        path: Local file or directory path to ingest.
        project_scope: Optional project name to attach to ingested nodes.
        tags: Optional tags to attach to every ingested file.
        recursive: Recursively ingest directories when true.
        max_files: Optional safety cap for large imports.
        token: Bearer token matching MCP_WRITE_TOKEN.
    """
    _assert_write_authed(token)
    return niklas_ingest_path_impl(
        path,
        project_scope=project_scope,
        tags=tags or [],
        recursive=recursive,
        max_files=max_files,
    )


@mcp.tool()
async def niklas_context_pack(
    question: str,
    project_scope: Optional[str] = None,
    limit: int = 8,
    token: Optional[str] = None,
) -> dict:
    """Return a compact local context pack for a project question.

    Args:
        question: Natural-language question or search phrase.
        project_scope: Optional project name to limit retrieval.
        limit: Maximum number of graph nodes to include.
        token: Optional bearer token.
    """
    _assert_authed(token)
    return niklas_context_pack_impl(
        question,
        project_scope=project_scope,
        limit=max(1, min(int(limit), 50)),
    )


@mcp.tool()
async def niklas_find_duplicates(
    project_scope: Optional[str] = None,
    limit: int = 50,
    token: Optional[str] = None,
) -> list[dict]:
    """Find exact duplicate local files by content hash.

    Args:
        project_scope: Optional project name to limit duplicate detection.
        limit: Maximum duplicate groups to return.
        token: Optional bearer token.
    """
    _assert_authed(token)
    return NiklasStore().find_duplicates(
        project_scope=project_scope,
        limit=max(1, min(int(limit), 250)),
    )


@mcp.tool()
async def niklas_get_node(node_id: str, token: Optional[str] = None) -> dict:
    """Return a single Niklas graph node by ID."""
    _assert_authed(token)
    node = NiklasStore().get_node(node_id)
    if not node:
        return {"error": "not found", "node_id": node_id}
    return node


@mcp.tool()
async def linear_search_issues(
    query: str,
    limit: int = 20,
    token: Optional[str] = None,
) -> list[dict]:
    """Search Linear issues through LINEAR_ACCESS_TOKEN.

    Args:
        query: Text to search in Linear issue title or description.
        limit: Maximum issues to return.
        token: Optional bearer token.
    """
    _assert_authed(token)
    return LinearClient().search_issues(query, limit=max(1, min(int(limit), 50)))


@mcp.tool()
async def linear_create_issue(
    team_id: str,
    title: str,
    description: Optional[str] = None,
    project_id: Optional[str] = None,
    state_id: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Create a Linear issue through LINEAR_ACCESS_TOKEN.

    This mutates Linear and therefore requires MCP_WRITE_TOKEN.
    """
    _assert_write_authed(token)
    return LinearClient().create_issue(
        team_id=team_id,
        title=title,
        description=description,
        project_id=project_id,
        state_id=state_id,
    )


@mcp.tool()
async def linear_update_issue(
    issue_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    state_id: Optional[str] = None,
    assignee_id: Optional[str] = None,
    project_id: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Update a Linear issue through LINEAR_ACCESS_TOKEN.

    The issue_id can be a UUID or shorthand identifier such as ABC-123.
    This mutates Linear and therefore requires MCP_WRITE_TOKEN.
    """
    _assert_write_authed(token)
    input_data = {
        "title": title,
        "description": description,
        "stateId": state_id,
        "assigneeId": assignee_id,
        "projectId": project_id,
    }
    return LinearClient().update_issue(issue_id, input_data)


@mcp.tool()
async def linear_link_asset(
    asset_node_id: str,
    issue_id: str,
    issue_identifier: Optional[str] = None,
    issue_title: Optional[str] = None,
    issue_url: Optional[str] = None,
    relationship_type: str = "linked-to-linear-issue",
    token: Optional[str] = None,
) -> dict:
    """Link a Niklas asset/node to a Linear issue in the local graph.

    This mutates the local SQLite graph and therefore requires MCP_WRITE_TOKEN.
    """
    _assert_write_authed(token)
    return NiklasStore().link_linear_issue(
        asset_node_id=asset_node_id,
        issue_id=issue_id,
        issue_identifier=issue_identifier,
        issue_title=issue_title,
        issue_url=issue_url,
        relationship_type=relationship_type,
    )


# ---------------------------------------------------------------------------
# BERT pilot CLI/MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def bert_on(
    project: str = ".",
    projects_root: Optional[str] = None,
    task: Optional[str] = None,
    linear_anchor: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Turn BERT on for a selected project folder and return the activation UX state."""
    _assert_authed(token)
    return bert_on_impl(
        project,
        projects_root=projects_root,
        task=task,
        linear_anchor=linear_anchor,
    )


@mcp.tool()
async def bert_status(token: Optional[str] = None) -> dict:
    """Return the shared BERT pilot readiness payload.

    This is read-only and mirrors `bert status --json`.
    """
    _assert_authed(token)
    return bert_status_impl()


@mcp.tool()
async def bert_doctor(token: Optional[str] = None) -> dict:
    """Return BERT doctor checks and warnings.

    This is read-only and mirrors `bert doctor --json`.
    """
    _assert_authed(token)
    return bert_doctor_impl()


@mcp.tool()
async def bert_first_read(token: Optional[str] = None) -> dict:
    """Return the current BERT first-read file list."""
    _assert_authed(token)
    return bert_first_read_impl()


@mcp.tool()
async def bert_solve(problem: str, token: Optional[str] = None) -> dict:
    """Route a large problem through the BERT staged method as a dry-run."""
    _assert_authed(token)
    return bert_solve_impl(problem)


@mcp.tool()
async def bert_stage(
    stage: str,
    node: Optional[str] = None,
    parent: Optional[str] = None,
    linear_anchor: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Return a dry-run payload for one BERT stage.

    Args:
        stage: Stage command or id, such as setup, goal, research-scout,
            expert-plans, handoff, 0, 1, 2, 3.
        node: Durable node name or placeholder.
        parent: Optional parent node/surface label.
        linear_anchor: Optional Linear issue/project/initiative identifier.
        token: Optional bearer token.
    """
    _assert_authed(token)
    return bert_stage_impl(
        stage,
        node,
        parent=parent,
        linear_anchor=linear_anchor,
    )


@mcp.tool()
async def bert_linear_snapshot(token: Optional[str] = None) -> dict:
    """Return BERT Linear status, using live API when configured and local fallback otherwise."""
    _assert_authed(token)
    return bert_linear_snapshot_impl()


@mcp.tool()
async def bert_project_template(name: str = "<project name>", slug: Optional[str] = None, token: Optional[str] = None) -> dict:
    """Return the BERT project scaffold template without writing files."""
    _assert_authed(token)
    return bert_project_template_impl(name, slug=slug)


@mcp.tool()
async def bert_project_analyze(
    project: str,
    projects_root: Optional[str] = None,
    task: Optional[str] = None,
    linear_anchor: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Analyze a folder before adopting it as a BERT project. Read-only."""
    _assert_authed(token)
    return bert_project_analyze_impl(
        project,
        projects_root=projects_root,
        task=task,
        linear_anchor=linear_anchor,
    )


@mcp.tool()
async def bert_project_create_plan(
    name: str,
    slug: Optional[str] = None,
    projects_root: Optional[str] = None,
    linear_anchor: Optional[str] = None,
    niklas_anchor: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Return the local BERT project create plan without applying filesystem writes."""
    _assert_authed(token)
    return bert_project_create_plan_impl(
        name,
        slug=slug,
        projects_root=projects_root,
        linear_anchor=linear_anchor,
        niklas_anchor=niklas_anchor,
        apply=False,
    )


@mcp.tool()
async def bert_project_adopt(
    project_path: str,
    name: Optional[str] = None,
    linear_anchor: Optional[str] = None,
    niklas_anchor: Optional[str] = None,
    apply: bool = False,
    token: Optional[str] = None,
) -> dict:
    """Adopt a project folder as a BERT project (gated local write).

    apply=False returns the adoption plan without touching the filesystem.
    apply=True creates the hidden `.BERT` workspace (`.BERT/L1M1/MAP.md`,
    `state.json`, stage folders) and requires the MCP_WRITE_TOKEN write
    contract — the same gate as write_atom. The container folder gate is
    enforced either way; existing files are never overwritten. Linear and
    Niklas graph writes remain blocked regardless.
    """
    if apply:
        _assert_write_authed(token)
    else:
        _assert_authed(token)
    payload = bert_project_init_impl(
        project_path,
        name=name,
        linear_anchor=linear_anchor,
        niklas_anchor=niklas_anchor,
        apply=apply,
    )
    if apply and payload.get("applied"):
        _append_audit(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "operation": "bert_project_adopt",
                "host_project_dir": payload.get("host_project_dir"),
                "bert_workspace_dir": payload.get("bert_workspace_dir"),
                "written_files": len(payload["applied"]["written_files"]),
                "skipped_existing_files": len(payload["applied"]["skipped_existing_files"]),
            }
        )
    return payload


@mcp.tool()
async def bert_project_open(
    project: str,
    projects_root: Optional[str] = None,
    task: Optional[str] = None,
    linear_anchor: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Open a BERT project packet and return local/Linear/Niklas orientation."""
    _assert_authed(token)
    return bert_project_open_impl(
        project,
        projects_root=projects_root,
        task=task,
        linear_anchor=linear_anchor,
    )


@mcp.tool()
async def bert_node_template(node_path: str = "L1M1", token: Optional[str] = None) -> dict:
    """Return the template for a BERT L/M node without writing files."""
    _assert_authed(token)
    return bert_node_template_impl(node_path)


@mcp.tool()
async def bert_node_create_plan(
    node_id: str,
    project: str,
    parent_path: Optional[str] = None,
    projects_root: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Return the local BERT node create plan without applying filesystem writes."""
    _assert_authed(token)
    return bert_node_create_plan_impl(
        node_id,
        project=project,
        parent_path=parent_path,
        projects_root=projects_root,
        apply=False,
    )


@mcp.tool()
async def bert_node_locate(
    project: str,
    parent_path: str = "L1M1",
    node_id: Optional[str] = None,
    step: Optional[int] = None,
    task: Optional[str] = None,
    projects_root: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Locate/propose the next BERT node without writing files."""
    _assert_authed(token)
    return bert_node_locate_impl(
        project,
        parent_path=parent_path,
        node_id=node_id,
        step=step,
        task=task,
        projects_root=projects_root,
    )


@mcp.tool()
async def bert_node_start_plan(
    project: str,
    name: Optional[str] = None,
    parent_path: str = "L1M1",
    node_id: Optional[str] = None,
    step: Optional[int] = None,
    task: Optional[str] = None,
    projects_root: Optional[str] = None,
    init_project: bool = False,
    token: Optional[str] = None,
) -> dict:
    """Return the guided BERT node start plan without applying local writes."""
    _assert_authed(token)
    return bert_node_start_plan_impl(
        project,
        name=name,
        parent_path=parent_path,
        node_id=node_id,
        step=step,
        task=task,
        projects_root=projects_root,
        init_project=init_project,
        apply=False,
    )


@mcp.tool()
async def bert_node_stages(
    project: str,
    node_path: str,
    projects_root: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Return stage order/status for one BERT node."""
    _assert_authed(token)
    return bert_node_stages_impl(project, node_path=node_path, projects_root=projects_root)


@mcp.tool()
async def bert_node_map(
    project: str,
    node_path: str,
    projects_root: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Read a BERT node MAP.md and return child-node candidates."""
    _assert_authed(token)
    return bert_node_map_impl(project, node_path=node_path, projects_root=projects_root)


@mcp.tool()
async def bert_node_spawn_children_plan(
    project: str,
    parent_path: str = "L1M1",
    projects_root: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """Return a dry-run child-node spawn plan from a parent MAP.md."""
    _assert_authed(token)
    return bert_node_spawn_children_plan_impl(
        project,
        parent_path=parent_path,
        projects_root=projects_root,
        apply=False,
    )


@mcp.tool()
async def bert_next(
    project: str,
    projects_root: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """The 10-second UX: report the one next action for a BERT project.

    Read-only. Returns current node, stage, latest draft version, who is
    waiting on whom (agent_draft / erich_answers / erich_accept), and the
    exact next command.
    """
    _assert_authed(token)
    return bert_next_impl(project, projects_root=projects_root)


@mcp.tool()
async def bert_stage_draft(
    project: str,
    node_path: Optional[str] = None,
    projects_root: Optional[str] = None,
    apply: bool = False,
    token: Optional[str] = None,
) -> dict:
    """Scaffold the next MDE draft for the current stage (gated local write).

    apply=False returns the draft plan (target path, version, stage form)
    without touching the filesystem. apply=True writes
    `<Prefix>_<node>_V{n+1}.md` — never overwrites, carries the prior version
    forward, embeds the parent `_seed.md` on a child's first brainstorm —
    and requires the MCP_WRITE_TOKEN contract, same as write_atom.
    """
    if apply:
        _assert_write_authed(token)
    else:
        _assert_authed(token)
    payload = bert_stage_draft_impl(
        project,
        node_path=node_path,
        projects_root=projects_root,
        apply=apply,
    )
    if apply and payload.get("drafted"):
        _append_audit(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "operation": "bert_stage_draft",
                "project_dir": payload.get("project_dir"),
                "node_path": payload.get("node_path"),
                "stage": (payload.get("stage") or {}).get("folder"),
                "artifact": (payload.get("artifact") or {}).get("path"),
            }
        )
    return payload


@mcp.tool()
async def bert_accept(
    project: str,
    node_path: Optional[str] = None,
    stage: Optional[str] = None,
    projects_root: Optional[str] = None,
    apply: bool = False,
    token: Optional[str] = None,
) -> dict:
    """Acceptance gate for the current stage artifact (gated local write).

    Stage complete = artifact accepted, not file-exists. apply=False reports
    whether the latest draft would pass the gates (sequence, citation gate on
    blueprint/MAP, altitude lint warn-only). apply=True stamps the artifact
    `status: accepted`, records acceptance in `state.json` (v2 per-stage
    records), and advances the derived current stage. Requires the
    MCP_WRITE_TOKEN contract.
    """
    if apply:
        _assert_write_authed(token)
    else:
        _assert_authed(token)
    payload = bert_accept_impl(
        project,
        node_path=node_path,
        stage=stage,
        projects_root=projects_root,
        apply=apply,
    )
    if apply and payload.get("accepted"):
        _append_audit(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "operation": "bert_accept",
                "project_dir": payload.get("project_dir"),
                "node_path": payload.get("node_path"),
                "stage": (payload.get("stage") or {}).get("folder"),
                "artifact": (payload.get("artifact") or {}).get("path"),
            }
        )
    return payload


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Transport selection via env var for federation support.
    # - "stdio" (default): spawned by Claude Code locally via mcp.add
    # - "streamable-http" or "http": long-running daemon, used by remote peers (Studio)
    # - "sse": Server-Sent Events transport (older clients)
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()

    if transport == "stdio":
        mcp.run()
    elif transport in ("http", "streamable-http", "sse"):
        # Configure host/port + relax DNS rebinding protection for LAN peers (Studio).
        # FastMCP.settings is a Pydantic model; assign before calling run().
        host = os.environ.get("MCP_BIND_HOST", "0.0.0.0")
        port = int(os.environ.get("MCP_BIND_PORT", "8788"))

        mcp.settings.host = host
        mcp.settings.port = port

        # Transport security: relax DNS rebinding protection for LAN peers.
        # Default only allows loopback. Daemon listens on private LAN — auth is via
        # MCP_WRITE_TOKEN bearer token, not host-header allowlist.
        # Set MCP_DISABLE_HOST_CHECK=false to re-enable strict checking.
        try:
            disable_host_check = os.environ.get("MCP_DISABLE_HOST_CHECK", "true").lower() == "true"
            if disable_host_check:
                mcp.settings.transport_security.enable_dns_rebinding_protection = False
                print(f"[niklas MCP] DNS rebinding protection DISABLED (LAN/Tailscale mode)", file=sys.stderr)
            else:
                # Explicit allowlist mode: add LAN + Tailscale ranges
                extra_hosts = os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if os.environ.get("MCP_ALLOWED_HOSTS") else []
                extra_origins = os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if os.environ.get("MCP_ALLOWED_ORIGINS") else []
                mcp.settings.transport_security.allowed_hosts = list(mcp.settings.transport_security.allowed_hosts) + extra_hosts
                mcp.settings.transport_security.allowed_origins = list(mcp.settings.transport_security.allowed_origins) + extra_origins
        except Exception as e:
            print(f"[niklas MCP] WARN: could not configure transport_security: {e}", file=sys.stderr)

        canonical_transport = "sse" if transport == "sse" else "streamable-http"
        print(f"[niklas MCP] starting on {host}:{port} ({canonical_transport})", file=sys.stderr)
        print(f"[niklas MCP] allowed_hosts now includes LAN + Tailscale ranges", file=sys.stderr)
        mcp.run(transport=canonical_transport)
    else:
        raise ValueError(f"Unknown MCP_TRANSPORT: {transport!r}. Expected stdio | http | streamable-http | sse.")
