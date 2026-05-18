#!/usr/bin/env python3
"""Read-only live healthcheck for the Zeus Brain finish-line milestone.

This script only reads paths, local HTTP endpoints, Docker state, and Neo4j
counts. It never rewrites config, rebuilds local-brain-search, or prints secret
values loaded from environment files.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
BRAIN_GRAPH_DIR = SCRIPT_PATH.parents[1]
RESOURCES_DIR = BRAIN_GRAPH_DIR.parent
CORNELIUS_ROOT = RESOURCES_DIR.parent

CANONICAL_BRAIN_ROOT = Path(
    os.environ.get(
        "BRAIN_ROOT",
        "/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain",
    )
)
CANONICAL_WIKI = CANONICAL_BRAIN_ROOT / "wiki"
SOURCE_CATALOG = CANONICAL_BRAIN_ROOT / ".brain" / "source_catalog.yaml"
GRAPH_ENRICHMENTS = BRAIN_GRAPH_DIR / "data" / "graph_enrichments.json"
LBS_DIR = RESOURCES_DIR / "local-brain-search"
LBS_DATA_DIR = LBS_DIR / "data"
BRAIN_CONSOLE_DIR = RESOURCES_DIR / "brain-console"
ENV_FILE = BRAIN_GRAPH_DIR / ".env"

SECRET_KEY_PARTS = ("PASS", "PASSWORD", "TOKEN", "SECRET", "KEY")


class Check:
    def __init__(self, status: str, name: str, detail: str, data: dict[str, Any] | None = None):
        self.status = status
        self.name = name
        self.detail = detail
        self.data = data or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "name": self.name,
            "detail": self.detail,
            "data": self.data,
        }


def run(cmd: list[str], *, timeout: float = 5.0, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def redact_env_value(key: str, value: str | None) -> str:
    if value is None or value == "":
        return "unset"
    if any(part in key.upper() for part in SECRET_KEY_PARTS):
        return "set"
    return value


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        try:
            value = shlex.split(raw_value, comments=False, posix=True)
            values[key] = value[0] if value else ""
        except ValueError:
            values[key] = raw_value.strip().strip("'\"")
    return values


def env_lookup(env_file_values: dict[str, str], *keys: str, default: str = "") -> tuple[str, str | None]:
    for key in keys:
        if os.environ.get(key):
            return os.environ[key], key
    for key in keys:
        if env_file_values.get(key):
            return env_file_values[key], key
    return default, None


def count_markdown(root: Path) -> int:
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", ".obsidian", ".trash", "__pycache__"}]
        count += sum(1 for name in filenames if name.lower().endswith((".md", ".markdown")))
    return count


def check_wiki_and_repo(wiki_path: Path) -> list[Check]:
    checks: list[Check] = []
    if not wiki_path.exists():
        return [
            Check("FAIL", "canonical Brain wiki", f"missing: {wiki_path}"),
            Check("FAIL", "Brain wiki git", "skipped because canonical wiki path is missing"),
        ]
    if not wiki_path.is_dir():
        return [
            Check("FAIL", "canonical Brain wiki", f"exists but is not a directory: {wiki_path}"),
            Check("FAIL", "Brain wiki git", "skipped because canonical wiki path is not a directory"),
        ]

    md_count = count_markdown(wiki_path)
    checks.append(Check("OK", "canonical Brain wiki", f"{wiki_path} ({md_count} markdown files)", {"markdown_count": md_count}))

    inside = run(["git", "-C", str(wiki_path), "rev-parse", "--is-inside-work-tree"], timeout=3)
    if inside.returncode != 0:
        checks.append(Check("FAIL", "Brain wiki git", "not a git repository or git unavailable", {"stderr": inside.stderr.strip()}))
        return checks

    branch = run(["git", "-C", str(wiki_path), "branch", "--show-current"], timeout=3)
    remote = run(["git", "-C", str(wiki_path), "remote", "-v"], timeout=3)
    remote_lines = sorted(set(line.strip() for line in remote.stdout.splitlines() if line.strip()))
    detail = f"branch={branch.stdout.strip() or '(detached/unknown)'}; remotes={len(remote_lines)}"
    checks.append(Check("OK", "Brain wiki git", detail, {"branch": branch.stdout.strip(), "remotes": remote_lines}))
    return checks


def load_yaml(path: Path) -> tuple[Any | None, str | None]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None, "PyYAML is not installed"
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def find_source_count(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("sources", "source_roots", "roots"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return len(candidate)
            if isinstance(candidate, dict):
                return len(candidate)
        counts = [count for child in value.values() if (count := find_source_count(child)) is not None]
        return max(counts) if counts else None
    if isinstance(value, list):
        return len(value)
    return None


def check_source_catalog(path: Path) -> Check:
    if not path.exists():
        return Check("WARN", "source_catalog.yaml", f"not present: {path}")
    data, error = load_yaml(path)
    if error:
        return Check("FAIL", "source_catalog.yaml", f"present but not loadable: {error}", {"path": str(path)})
    source_count = find_source_count(data)
    version = data.get("version") if isinstance(data, dict) else None
    detail = f"loaded from {path}"
    if source_count is not None:
        detail += f"; sources={source_count}"
    if version is not None:
        detail += f"; version={version}"
    return Check("OK", "source_catalog.yaml", detail, {"path": str(path), "sources": source_count, "version": version})


def check_graph_enrichments(path: Path) -> Check:
    if not path.exists():
        return Check("FAIL", "graph_enrichments.json", f"missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return Check("FAIL", "graph_enrichments.json", f"present but not parseable: {type(exc).__name__}: {exc}")
    nodes = data.get("nodes") if isinstance(data, dict) else None
    edges = data.get("edges") if isinstance(data, dict) else None
    atom_count = len(nodes) if hasattr(nodes, "__len__") else None
    edge_count = len(edges) if hasattr(edges, "__len__") else None
    status = "OK" if atom_count is not None and edge_count is not None else "WARN"
    detail = f"atoms={atom_count if atom_count is not None else 'unknown'}; edges={edge_count if edge_count is not None else 'unknown'}"
    return Check(status, "graph_enrichments.json", detail, {"path": str(path), "atoms": atom_count, "edges": edge_count})


def check_docker_container(timeout: float) -> Check:
    docker = run(
        ["docker", "ps", "--filter", "name=zeus-brain", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
        timeout=timeout,
    )
    if docker.returncode != 0:
        return Check("WARN", "Neo4j container", f"docker ps failed: {docker.stderr.strip() or docker.stdout.strip()}")
    lines = [line for line in docker.stdout.splitlines() if line.strip()]
    if not lines:
        return Check("FAIL", "Neo4j container", "no running zeus-brain container found")
    preferred = next((line for line in lines if line.startswith("zeus-brain-neo4j\t")), lines[0])
    name, status, ports = (preferred.split("\t", 2) + ["", ""])[:3]
    health_status = "healthy" if "healthy" in status.lower() else "unknown"
    check_status = "OK" if "up" in status.lower() else "FAIL"
    return Check(check_status, "Neo4j container", f"{name}: {status}; ports={ports or '(none)'}", {"container": name, "health": health_status, "ports": ports})


def check_neo4j_counts(env_file_values: dict[str, str], timeout: float) -> Check:
    uri, uri_key = env_lookup(env_file_values, "NEO4J_URI", "BRAIN_NEO4J_URI", default="bolt://localhost:7689")
    user, user_key = env_lookup(env_file_values, "NEO4J_USER", "BRAIN_NEO4J_USER", default="neo4j")
    password, pass_key = env_lookup(env_file_values, "NEO4J_PASS", "BRAIN_NEO4J_PASS", default="")
    env_data = {
        "uri": redact_env_value(uri_key or "NEO4J_URI", uri),
        "user": redact_env_value(user_key or "NEO4J_USER", user),
        "password": redact_env_value(pass_key or "NEO4J_PASS", password),
        "password_source": pass_key or "unset",
    }
    if not password:
        return Check("FAIL", "Neo4j counts", "password env is not configured; counts skipped", env_data)
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError as exc:
        return Check("FAIL", "Neo4j counts", f"neo4j Python driver unavailable: {exc}", env_data)
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=timeout)
        try:
            with driver.session() as session:
                atoms = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
                edges = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
                labeled_atoms = session.run("MATCH (n:Atom) RETURN count(n) AS count").single()["count"]
        finally:
            driver.close()
    except Exception as exc:  # noqa: BLE001
        return Check("FAIL", "Neo4j counts", f"query failed via {uri}: {type(exc).__name__}: {exc}", env_data)
    detail = f"nodes={atoms}; relationships={edges}; Atom-labeled={labeled_atoms}; uri={uri}"
    return Check("OK", "Neo4j counts", detail, {**env_data, "nodes": atoms, "relationships": edges, "atom_label": labeled_atoms})


def http_get(url: str, *, timeout: float, accept: str = "application/json") -> tuple[str, int | None, str]:
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "zeus-brain-healthcheck/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(512).decode("utf-8", errors="replace")
            return "ok", response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(512).decode("utf-8", errors="replace")
        return "http", exc.code, body
    except Exception as exc:  # noqa: BLE001
        return "error", None, f"{type(exc).__name__}: {exc}"


def check_mcp(timeout: float) -> Check:
    url = "http://127.0.0.1:8788/mcp"
    kind, code, body = http_get(url, timeout=timeout, accept="application/json")
    if kind == "ok":
        return Check("OK", "MCP 8788", f"{url} returned HTTP {code}", {"url": url, "http_status": code})
    if kind == "http" and code == 406:
        return Check(
            "OK",
            "MCP 8788",
            "reachable; HTTP 406 is expected for plain JSON probes without text/event-stream",
            {"url": url, "http_status": code, "body_preview": body[:160]},
        )
    if kind == "http":
        return Check("WARN", "MCP 8788", f"reachable but returned HTTP {code}", {"url": url, "http_status": code, "body_preview": body[:160]})
    return Check("FAIL", "MCP 8788", f"not reachable: {body}", {"url": url})


def file_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": stat.st_size,
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
    }


def check_lbs_artifacts() -> list[Check]:
    checks: list[Check] = []
    required = {
        "FAISS index": LBS_DATA_DIR / "brain.faiss",
        "metadata": LBS_DATA_DIR / "brain_metadata.pkl",
        "graph pickle": LBS_DATA_DIR / "brain_graph.pkl",
    }
    missing = [label for label, path in required.items() if not path.exists()]
    data = {label: file_summary(path) for label, path in required.items()}
    if missing:
        checks.append(Check("FAIL", "local-brain-search artifacts", f"missing: {', '.join(missing)}", data))
    else:
        sizes = ", ".join(f"{label}={summary['bytes']}B" for label, summary in data.items())
        checks.append(Check("OK", "local-brain-search artifacts", sizes, data))

    metadata_path = required["metadata"]
    if not metadata_path.exists():
        checks.append(Check("WARN", "local-brain-search metadata paths", "metadata missing; stale path detection skipped"))
        return checks
    try:
        with metadata_path.open("rb") as handle:
            metadata = pickle.load(handle)
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("FAIL", "local-brain-search metadata paths", f"metadata not parseable: {type(exc).__name__}: {exc}"))
        return checks

    filepaths = [str(item.get("filepath", "")) for item in metadata if isinstance(item, dict) and item.get("filepath")]
    unique_paths = sorted(set(filepaths))
    stale_patterns = [
        "/Users/erichroepke/Desktop/Brain/",
        "/Users/erichroepke/Cornelius/",
        "/Users/erichroepke/Desktop/Brain-replica/",
        "/Volumes/ZEUS DRIVE/Zeus/Knowledge/",
    ]
    stale_hits = {pattern: sum(1 for path in unique_paths if pattern in path) for pattern in stale_patterns}
    canonical_prefix = str(CANONICAL_WIKI) + "/"
    outside_brain = sum(1 for path in unique_paths if path.startswith("/") and not path.startswith(canonical_prefix))
    missing_samples = [path for path in unique_paths[:5000] if path.startswith("/") and not Path(path).exists()][:5]
    status = "WARN" if any(stale_hits.values()) or outside_brain or missing_samples else "OK"
    detail = (
        f"{len(metadata)} chunks; {len(unique_paths)} unique files; "
        f"stale_hits={sum(stale_hits.values())}; outside_brain={outside_brain}; "
        f"missing_samples={len(missing_samples)}"
    )
    checks.append(
        Check(
            status,
            "local-brain-search metadata paths",
            detail,
            {
                "chunks": len(metadata),
                "unique_files": len(unique_paths),
                "stale_patterns": stale_hits,
                "outside_brain": outside_brain,
                "missing_samples_first_5000": missing_samples,
            },
        )
    )
    return checks


def check_lbs_health(timeout: float) -> Check:
    port = os.environ.get("BRAIN_DAEMON_PORT", "7437")
    url = f"http://127.0.0.1:{port}/health"
    kind, code, body = http_get(url, timeout=timeout)
    if kind == "ok":
        parsed: Any
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body[:160]
        return Check("OK", "local-brain-search health", f"{url} returned HTTP {code}", {"url": url, "response": parsed})
    if kind == "http":
        return Check("WARN", "local-brain-search health", f"{url} returned HTTP {code}", {"url": url, "body_preview": body[:160]})
    return Check("WARN", "local-brain-search health", f"daemon not reachable at {url}: {body}", {"url": url})


def check_brain_console(timeout: float) -> list[Check]:
    checks: list[Check] = []
    required = [BRAIN_CONSOLE_DIR / "server.py", BRAIN_CONSOLE_DIR / "static" / "index.html"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        checks.append(Check("FAIL", "Brain Console files", f"missing: {', '.join(missing)}"))
    else:
        checks.append(Check("OK", "Brain Console files", f"present: {BRAIN_CONSOLE_DIR}", {"path": str(BRAIN_CONSOLE_DIR)}))

    url = "http://127.0.0.1:8789"
    kind, code, body = http_get(url, timeout=timeout, accept="text/html,application/json")
    if kind == "ok":
        checks.append(Check("OK", "Brain Console HTTP", f"{url} returned HTTP {code}", {"url": url}))
    elif kind == "http":
        checks.append(Check("WARN", "Brain Console HTTP", f"{url} returned HTTP {code}", {"url": url, "body_preview": body[:160]}))
    else:
        checks.append(Check("WARN", "Brain Console HTTP", f"not reachable at {url}: {body}", {"url": url}))
    return checks


def render(checks: list[Check]) -> str:
    width = max(len(check.name) for check in checks)
    lines = ["ZEUS Brain live healthcheck (read-only)", f"Cornelius: {CORNELIUS_ROOT}", ""]
    for check in checks:
        lines.append(f"[{check.status:<4}] {check.name:<{width}}  {check.detail}")
    failures = sum(1 for check in checks if check.status == "FAIL")
    warnings = sum(1 for check in checks if check.status == "WARN")
    lines.append("")
    lines.append(f"Summary: {failures} fail, {warnings} warn, {len(checks) - failures - warnings} ok")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only one-command live Brain healthcheck for ERI-133/ERI-293.",
        epilog=(
            "Examples:\n"
            "  scripts/live_brain_healthcheck.py\n"
            "  scripts/live_brain_healthcheck.py --json\n\n"
            "Exit code is 1 when hard failures are found. Secrets from .env/env are only reported as set/unset."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of the concise text report")
    parser.add_argument("--timeout", type=float, default=3.0, help="timeout in seconds for Docker, HTTP, and Neo4j probes")
    parser.add_argument("--wiki-path", type=Path, default=CANONICAL_WIKI, help=f"canonical Brain wiki path (default: {CANONICAL_WIKI})")
    args = parser.parse_args(argv)

    env_file_values = parse_env_file(ENV_FILE)
    checks: list[Check] = []
    checks.extend(check_wiki_and_repo(args.wiki_path))
    checks.append(check_source_catalog(SOURCE_CATALOG))
    checks.append(check_graph_enrichments(GRAPH_ENRICHMENTS))
    checks.append(check_docker_container(args.timeout))
    checks.append(check_neo4j_counts(env_file_values, args.timeout))
    checks.append(check_mcp(args.timeout))
    checks.extend(check_lbs_artifacts())
    checks.append(check_lbs_health(args.timeout))
    checks.extend(check_brain_console(args.timeout))

    if args.json:
        print(json.dumps({"checks": [check.as_dict() for check in checks]}, indent=2, sort_keys=True))
    else:
        print(render(checks))

    return 1 if any(check.status == "FAIL" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
