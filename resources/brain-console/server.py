#!/usr/bin/env python3
"""Local ZEUS Brain Console.

Read-only operator dashboard for the git-backed Brain wiki, FAISS/BDG files,
and Neo4j projection. Credentials stay server-side; the browser never receives
the Neo4j password.
"""
from __future__ import annotations

import json
import os
import pickle
import stat
import subprocess
import threading
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

try:
    from neo4j import GraphDatabase
except ImportError as exc:  # pragma: no cover - boot guard
    print("ERROR: neo4j package missing. Install brain-graph requirements.", file=sys.stderr)
    raise SystemExit(2) from exc


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
HOME = Path.home()


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def first_existing_dir(candidates: list[Path], required_child: str | None = None) -> Path:
    """Return the first candidate directory that exists, optionally with a child."""
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            if required_child is None or (candidate / required_child).exists():
                return candidate
    return candidates[0]


CORNELIUS_ROOT = APP_DIR.parents[1]
SETTINGS_PATH = CORNELIUS_ROOT / ".claude" / "settings.md"
SETTINGS = load_env_file(SETTINGS_PATH)
_settings_brain_root = Path(SETTINGS["VAULT_BASE_PATH"]).expanduser() if SETTINGS.get("VAULT_BASE_PATH") else None
_brain_candidates = [
    *([_settings_brain_root] if _settings_brain_root else []),
    HOME / "Desktop" / "Brain",
    HOME / "Desktop" / "ZEUS-BRAIN-STARTUP-2026-05-17" / "Brain",
    HOME / "Desktop" / "Brain-replica",
    HOME / "Desktop" / "NIKLAS",
]
BRAIN_ROOT = Path(os.environ["BRAIN_ROOT"]) if os.environ.get("BRAIN_ROOT") else first_existing_dir(_brain_candidates, "wiki")
WIKI_ROOT = BRAIN_ROOT / "wiki"
BRAIN_GRAPH_DIR = Path(os.environ["BRAIN_GRAPH_DIR"]) if os.environ.get("BRAIN_GRAPH_DIR") else first_existing_dir(
    [
        CORNELIUS_ROOT / "resources" / "brain-graph",
        HOME / "Cornelius" / "resources" / "brain-graph",
        HOME / "Desktop" / "Cornelius" / "resources" / "brain-graph",
    ]
)
LBS_DIR = Path(os.environ["LBS_DIR"]) if os.environ.get("LBS_DIR") else first_existing_dir(
    [
        CORNELIUS_ROOT / "resources" / "local-brain-search",
        HOME / "Cornelius" / "resources" / "local-brain-search",
        HOME / "Desktop" / "Cornelius" / "resources" / "local-brain-search",
    ]
)
GRAPH_ENRICHMENTS = BRAIN_GRAPH_DIR / "data" / "graph_enrichments.json"
LBS_METADATA = LBS_DIR / "data" / "brain_metadata.pkl"
LBS_FAISS = LBS_DIR / "data" / "brain.faiss"
ENV_PATH = BRAIN_GRAPH_DIR / ".env"
REGISTRY_PATH = WIKI_ROOT / "Meta" / "consolidation-registry-2026-05-17.json"


ENV = load_env_file(ENV_PATH)
NEO4J_URI = ENV.get("NEO4J_URI") or os.environ.get("NEO4J_URI") or "bolt://localhost:7689"
NEO4J_USER = ENV.get("NEO4J_USER") or ENV.get("BRAIN_NEO4J_USER") or os.environ.get("NEO4J_USER") or "neo4j"
NEO4J_PASS = ENV.get("NEO4J_PASS") or ENV.get("BRAIN_NEO4J_PASS") or os.environ.get("NEO4J_PASS") or ""
HOST = os.environ.get("BRAIN_CONSOLE_HOST", "127.0.0.1")
PORT = int(os.environ.get("BRAIN_CONSOLE_PORT", "8789"))
REDIRECT_PORT = int(os.environ.get("BRAIN_CONSOLE_REDIRECT_PORT", "7476"))
PUBLIC_URL = os.environ.get("BRAIN_CONSOLE_PUBLIC_URL", f"http://127.0.0.1:{PORT}/")


_driver = None
_driver_lock = threading.Lock()
_graph_cache: dict[str, Any] | None = None
_graph_cache_mtime = 0.0
_graph_lock = threading.Lock()
_metadata_cache: list[dict[str, Any]] | None = None
_metadata_cache_mtime = 0.0
_metadata_lock = threading.Lock()


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def text_response(handler: BaseHTTPRequestHandler, body: bytes, content_type: str, status: int = 200) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def get_driver():
    global _driver
    if _driver is None:
        with _driver_lock:
            if _driver is None:
                if not NEO4J_PASS:
                    raise RuntimeError("Neo4j password not configured in brain-graph .env")
                _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    return _driver


def run_cypher(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with get_driver().session() as session:
        return [dict(row) for row in session.run(query, params or {})]


def load_graph() -> dict[str, Any]:
    global _graph_cache, _graph_cache_mtime
    if not GRAPH_ENRICHMENTS.exists():
        return {"nodes": {}, "edges": {}, "tensions": []}
    mtime = GRAPH_ENRICHMENTS.stat().st_mtime
    if _graph_cache is None or mtime != _graph_cache_mtime:
        with _graph_lock:
            if _graph_cache is None or mtime != _graph_cache_mtime:
                _graph_cache = json.loads(GRAPH_ENRICHMENTS.read_text(encoding="utf-8"))
                _graph_cache_mtime = mtime
    return _graph_cache


def assert_trusted_metadata_file(path: Path) -> None:
    resolved = path.resolve()
    resolved.relative_to(LBS_DIR.resolve())
    mode = resolved.stat().st_mode
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError(f"Refusing writable pickle metadata file: {resolved}")


def load_metadata() -> list[dict[str, Any]]:
    global _metadata_cache, _metadata_cache_mtime
    if not LBS_METADATA.exists():
        return []
    mtime = LBS_METADATA.stat().st_mtime
    if _metadata_cache is None or mtime != _metadata_cache_mtime:
        with _metadata_lock:
            if _metadata_cache is None or mtime != _metadata_cache_mtime:
                assert_trusted_metadata_file(LBS_METADATA)
                with LBS_METADATA.open("rb") as f:
                    _metadata_cache = pickle.load(f)
                _metadata_cache_mtime = mtime
    return _metadata_cache or []


def git_output(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(BRAIN_ROOT), *args],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except Exception:
        return ""


def is_indexable_markdown(path: Path) -> bool:
    """True for real markdown notes; false for macOS AppleDouble and git sidecars."""
    return path.suffix == ".md" and not any(part.startswith("._") or part == ".git" for part in path.parts)


def markdown_paths() -> list[Path]:
    if not BRAIN_ROOT.exists():
        return []
    return sorted(p for p in BRAIN_ROOT.rglob("*.md") if is_indexable_markdown(p))


def rel_to_brain(path: Path) -> str:
    try:
        return path.relative_to(BRAIN_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_brain_file(atom_id: str) -> Path | None:
    path = (BRAIN_ROOT / atom_id).resolve()
    try:
        path.relative_to(BRAIN_ROOT.resolve())
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def read_note_text(atom_id: str, max_chars: int | None = None) -> str:
    path = resolve_brain_file(atom_id)
    if path is None:
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return f.read(max_chars) if max_chars is not None else f.read()


def read_note_preview(atom_id: str, max_chars: int = 2400) -> str:
    return read_note_text(atom_id, max_chars)


def index_coverage() -> dict[str, Any]:
    graph = load_graph()
    indexed = set(graph.get("nodes", {}).keys())
    all_md = {rel_to_brain(p) for p in markdown_paths()}
    missing = sorted(all_md - indexed)
    extra = sorted(indexed - all_md)
    return {
        "total_markdown": len(all_md),
        "graph_nodes": len(indexed),
        "missing_from_graph": missing[:200],
        "missing_count": len(missing),
        "graph_without_file_count": len(extra),
        "graph_without_file": extra[:50],
    }


def api_status() -> dict[str, Any]:
    graph = load_graph()
    metadata = load_metadata()
    coverage = index_coverage()
    neo4j: dict[str, Any] = {"reachable": False, "uri": NEO4J_URI}
    try:
        rows = run_cypher("MATCH (n:Atom) RETURN count(n) AS atoms")
        rels = run_cypher("MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY count DESC")
        layers = run_cypher("MATCH (n:Atom) RETURN n.layer AS layer, count(n) AS count ORDER BY count DESC")
        neo4j.update({"reachable": True, "atoms": rows[0]["atoms"], "relationships": rels, "layers": layers})
    except Exception as exc:
        neo4j["error"] = str(exc)

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "paths": {
            "brain_root": str(BRAIN_ROOT),
            "wiki_root": str(WIKI_ROOT),
            "graph_enrichments": str(GRAPH_ENRICHMENTS),
            "faiss_index": str(LBS_FAISS),
            "metadata": str(LBS_METADATA),
        },
        "git": {
            "branch": git_output(["branch", "--show-current"]),
            "head": git_output(["log", "-1", "--oneline", "--decorate"]),
            "status": git_output(["status", "--short"]),
        },
        "files": coverage,
        "faiss": {
            "exists": LBS_FAISS.exists(),
            "size_bytes": LBS_FAISS.stat().st_size if LBS_FAISS.exists() else 0,
            "chunk_count": len(metadata),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(LBS_FAISS.stat().st_mtime)) if LBS_FAISS.exists() else None,
        },
        "bdg": {
            "exists": GRAPH_ENRICHMENTS.exists(),
            "last_bootstrap": graph.get("last_bootstrap"),
            "nodes": len(graph.get("nodes", {})),
            "edges": len(graph.get("edges", {})),
            "tensions": len(graph.get("tensions", [])),
        },
        "neo4j": neo4j,
        "registry": {
            "exists": REGISTRY_PATH.exists(),
            "path": str(REGISTRY_PATH),
        },
    }


def api_search(query: str, limit: int) -> dict[str, Any]:
    q = query.strip().lower()
    if not q:
        return {"query": query, "results": []}

    graph = load_graph()
    nodes = graph.get("nodes", {})
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        rows = run_cypher(
            """
            MATCH (a:Atom)
            WHERE toLower(a.id) CONTAINS $q
            WITH a, COUNT { (a)--() } AS degree
            RETURN a.id AS id, a.layer AS layer, a.lifecycle AS lifecycle,
                   a.staleness_score AS staleness, degree
            ORDER BY degree DESC, id ASC
            LIMIT $limit
            """,
            {"q": q, "limit": limit},
        )
        for row in rows:
            row["source"] = "neo4j-id"
            row["preview"] = read_note_preview(row["id"], 700)
            results.append(row)
            seen.add(row["id"])
    except Exception:
        pass

    if len(results) < limit:
        for chunk in load_metadata():
            atom_id = chunk.get("note_id") or ""
            if not atom_id or atom_id in seen:
                continue
            content = chunk.get("content") or ""
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
                    "lifecycle": props.get("lifecycle"),
                    "staleness": props.get("staleness_score"),
                    "degree": None,
                    "source": "semantic-index",
                    "title": chunk.get("title"),
                    "heading": chunk.get("heading"),
                    "preview": content[:700],
                }
            )
            seen.add(atom_id)
            if len(results) >= limit:
                break

    return {"query": query, "results": results[:limit]}


def api_node(atom_id: str) -> dict[str, Any]:
    graph = load_graph()
    props = graph.get("nodes", {}).get(atom_id, {})
    outgoing: list[dict[str, Any]] = []
    incoming: list[dict[str, Any]] = []
    for key, edge in graph.get("edges", {}).items():
        if "||" not in key:
            continue
        src, dst = key.split("||", 1)
        record = {"source": src, "target": dst, **edge}
        if src == atom_id:
            outgoing.append(record)
        elif dst == atom_id:
            incoming.append(record)
        if len(outgoing) + len(incoming) >= 120:
            break
    return {
        "id": atom_id,
        "props": props,
        "content": read_note_preview(atom_id, 7000),
        "outgoing": outgoing[:60],
        "incoming": incoming[:60],
    }


def api_graph(atom_id: str, limit: int) -> dict[str, Any]:
    try:
        rows = run_cypher(
            """
            MATCH (center:Atom {id: $id})
            OPTIONAL MATCH (center)-[r]-(n:Atom)
            WITH center, collect({id: n.id, layer: n.layer, rel: type(r)})[..$limit] AS neighbors
            RETURN center.id AS center, center.layer AS layer, neighbors
            """,
            {"id": atom_id, "limit": limit},
        )
        if rows:
            neighbors = [n for n in rows[0]["neighbors"] if n.get("id")]
            return {"center": {"id": rows[0]["center"], "layer": rows[0]["layer"]}, "neighbors": neighbors}
    except Exception as exc:
        return {"error": str(exc), "center": {"id": atom_id}, "neighbors": []}
    return {"center": {"id": atom_id}, "neighbors": []}


def api_sources() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"sources": [], "error": "registry file not found"}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            sources = data.get("sources") or data.get("items") or []
        else:
            sources = data
        return {"sources": sources}
    except Exception as exc:
        return {"sources": [], "error": str(exc)}


class RedirectHandler(BaseHTTPRequestHandler):
    server_version = "ZeusBrainConsoleRedirect/0.1"

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", PUBLIC_URL)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[brain-console-redirect] {self.address_string()} {fmt % args}")


class Handler(BaseHTTPRequestHandler):
    server_version = "ZeusBrainConsole/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path == "/api/status":
                return json_response(self, api_status())
            if path == "/api/search":
                return json_response(self, api_search(params.get("q", [""])[0], int(params.get("limit", ["25"])[0])))
            if path == "/api/node":
                return json_response(self, api_node(unquote(params.get("id", [""])[0])))
            if path == "/api/graph":
                return json_response(self, api_graph(unquote(params.get("id", [""])[0]), int(params.get("limit", ["40"])[0])))
            if path == "/api/sources":
                return json_response(self, api_sources())
            if path == "/api/unindexed":
                return json_response(self, index_coverage())
            if path in ("/", "/index.html"):
                return self.serve_static("index.html", "text/html; charset=utf-8")
            if path == "/styles.css":
                return self.serve_static("styles.css", "text/css; charset=utf-8")
            if path == "/app.js":
                return self.serve_static("app.js", "application/javascript; charset=utf-8")
            return json_response(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def serve_static(self, name: str, content_type: str) -> None:
        target = STATIC_DIR / name
        if not target.exists():
            return json_response(self, {"error": f"missing static asset: {name}"}, HTTPStatus.NOT_FOUND)
        text_response(self, target.read_bytes(), content_type)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[brain-console] {self.address_string()} {fmt % args}")


def start_redirect_server() -> None:
    if REDIRECT_PORT == PORT:
        return
    try:
        redirect = ThreadingHTTPServer((HOST, REDIRECT_PORT), RedirectHandler)
    except OSError as exc:
        print(f"ZEUS Brain Console redirect disabled on {HOST}:{REDIRECT_PORT}: {exc}", file=sys.stderr)
        return
    print(f"ZEUS Brain Console redirect: http://{HOST}:{REDIRECT_PORT} -> {PUBLIC_URL}")
    thread = threading.Thread(target=redirect.serve_forever, name="brain-console-redirect", daemon=True)
    thread.start()


def main() -> None:
    print(f"ZEUS Brain Console: http://{HOST}:{PORT}")
    print(f"Brain root: {BRAIN_ROOT}")
    start_redirect_server()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
