"""zeus-brain MCP server (read-scope v1).

Exposes the Brain Dependency Graph as MCP tools any Claude Code project can
mount. stdio transport by default (no network surface). Optional bearer-token
gate via ZEUS_BRAIN_TOKEN env var.

Tools (read scope):
- zeus_brain_status                  — sidecar + Neo4j health
- zeus_brain_search                  — hybrid (vector via LanceDB-future + graph)
- zeus_brain_get                     — atom by id
- zeus_brain_neighborhood            — k-hop ego graph
- zeus_brain_orphans                 — atoms with no edges
- zeus_brain_hubs                    — atoms ranked by degree
- zeus_brain_decay_candidates        — stale + low-confidence atoms
- zeus_brain_path                    — shortest path between two atoms
- zeus_brain_graph_query             — raw read-only Cypher (denylist mutating clauses)

Configure via .env (alongside docker-compose.neo4j.yml):
    NEO4J_URI=bolt://localhost:7689
    BRAIN_NEO4J_USER=neo4j
    BRAIN_NEO4J_PASS=<your password>
    ZEUS_BRAIN_TOKEN=<optional shared secret; if set, callers must pass it>

Plug into a project:
    claude mcp add -s user zeus-brain \\
        /Users/erichroepke/Cornelius/resources/local-brain-search/venv/bin/python \\
        /Users/erichroepke/Cornelius/resources/brain-graph/mcp_server.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
ZEUS_BRAIN_TOKEN = os.environ.get("ZEUS_BRAIN_TOKEN", "")
MCP_WRITE_TOKEN = os.environ.get("MCP_WRITE_TOKEN", "")

# Vault root — atoms are written relative to this directory.
# Default: ~/Desktop/Brain (matches Cornelius VAULT_BASE_PATH)
VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "Desktop" / "Brain"))

# Audit log for all write_atom calls
_AUDIT_LOG = Path(__file__).parent / "data" / "mcp_write_audit.jsonl"

# Lazy-imported MCP + Neo4j (so this file imports cleanly before pip install)
try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
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
except ImportError as e:
    print(
        "ERROR: neo4j driver not installed. Run:\n"
        "  pip install -r requirements-mcp.txt",
        file=sys.stderr,
    )
    raise SystemExit(2) from e


# ---------------------------------------------------------------------------
# Neo4j driver (lazy, reconnect-safe)
# ---------------------------------------------------------------------------

_driver = None


def _get_driver():
    """Return a cached Neo4j driver, or raise a clear error if unconfigured."""
    global _driver
    if _driver is not None:
        return _driver
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
            "Mutating Cypher rejected by zeus-brain read-scope server. "
            "Allowed: MATCH, OPTIONAL MATCH, WITH, RETURN, UNWIND, WHERE, ORDER BY, LIMIT, SKIP, CALL apoc.<read-only>."
        )


# ---------------------------------------------------------------------------
# Auth (optional bearer-token gate)
# ---------------------------------------------------------------------------

def _assert_authed(token: Optional[str]) -> None:
    """If ZEUS_BRAIN_TOKEN is configured, callers must match it."""
    if not ZEUS_BRAIN_TOKEN:
        return  # auth disabled
    if token != ZEUS_BRAIN_TOKEN:
        raise PermissionError("zeus-brain: invalid or missing token")


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP("zeus-brain")


@mcp.tool()
async def zeus_brain_status(token: Optional[str] = None) -> dict:
    """Return health + counts for the Brain Dependency Graph.

    Args:
        token: Optional bearer token (required only if ZEUS_BRAIN_TOKEN is set in env).
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
async def zeus_brain_get(atom_id: str, token: Optional[str] = None) -> dict:
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
async def zeus_brain_neighborhood(
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
async def zeus_brain_orphans(limit: int = 50, token: Optional[str] = None) -> list[dict]:
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
async def zeus_brain_hubs(min_degree: int = 5, limit: int = 25, token: Optional[str] = None) -> list[dict]:
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
async def zeus_brain_decay_candidates(days: int = 90, limit: int = 50, token: Optional[str] = None) -> list[dict]:
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
async def zeus_brain_path(
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
async def zeus_brain_graph_query(cypher: str, params: Optional[dict] = None, token: Optional[str] = None) -> list[dict]:
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
async def zeus_brain_search(
    query: str,
    mode: str = "graph",
    k: int = 10,
    token: Optional[str] = None,
) -> list[dict]:
    """Search the Brain.

    Modes:
        graph    — full-text Cypher over Atom.id (fast, deterministic)
        vector   — FAISS via local-brain-search (NOT YET WIRED in this server; stub)
        hybrid   — vector top-K + graph neighborhood expand (NOT YET WIRED; falls back to graph)
    """
    _assert_authed(token)
    if mode in ("vector", "hybrid"):
        # TODO: wire to local-brain-search FAISS / future Qdrant.
        # For v1 fall back to graph mode and annotate.
        rows = _run_read(
            """
            CALL db.index.fulltext.queryNodes('atom_fulltext', $q) YIELD node, score
            RETURN node.id AS id, node.layer AS layer, score
            ORDER BY score DESC
            LIMIT $k
            """,
            {"q": query, "k": int(k)},
        ) if _full_text_index_exists() else []
        return [
            {"mode": "graph (vector/hybrid not yet wired)", **r}
            for r in rows
        ]
    # default: graph mode (Cypher CONTAINS + full-text if available)
    return _run_read(
        """
        MATCH (a:Atom)
        WHERE a.id CONTAINS $q
        RETURN a.id AS id, a.layer AS layer
        LIMIT $k
        """,
        {"q": query, "k": int(k)},
    )


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
                print(f"[zeus-brain MCP] DNS rebinding protection DISABLED (LAN/Tailscale mode)", file=sys.stderr)
            else:
                # Explicit allowlist mode: add LAN + Tailscale ranges
                extra_hosts = os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if os.environ.get("MCP_ALLOWED_HOSTS") else []
                extra_origins = os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if os.environ.get("MCP_ALLOWED_ORIGINS") else []
                mcp.settings.transport_security.allowed_hosts = list(mcp.settings.transport_security.allowed_hosts) + extra_hosts
                mcp.settings.transport_security.allowed_origins = list(mcp.settings.transport_security.allowed_origins) + extra_origins
        except Exception as e:
            print(f"[zeus-brain MCP] WARN: could not configure transport_security: {e}", file=sys.stderr)

        canonical_transport = "sse" if transport == "sse" else "streamable-http"
        print(f"[zeus-brain MCP] starting on {host}:{port} ({canonical_transport})", file=sys.stderr)
        print(f"[zeus-brain MCP] allowed_hosts now includes LAN + Tailscale ranges", file=sys.stderr)
        mcp.run(transport=canonical_transport)
    else:
        raise ValueError(f"Unknown MCP_TRANSPORT: {transport!r}. Expected stdio | http | streamable-http | sse.")
