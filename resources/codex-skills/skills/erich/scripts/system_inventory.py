#!/usr/bin/env python3
"""Inventory Erich's local tools without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


SECRET_RE = re.compile(
    r"(token|secret|password|passwd|key|api[_-]?key|credential|auth|bearer|cookie)",
    re.IGNORECASE,
)

TEXT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".txt",
    ".json",
    ".jsonl",
    ".toml",
    ".yaml",
    ".yml",
    ".csv",
    ".html",
}

CLI_VERSION_ARGS = {
    "codex": ["--version"],
    "claude": ["--version"],
    "gh": ["--version"],
    "git": ["--version"],
    "python3": ["--version"],
    "node": ["--version"],
    "npm": ["--version"],
    "pnpm": ["--version"],
    "bun": ["--version"],
    "uv": ["--version"],
    "docker": ["--version"],
    "rclone": ["version"],
    "ffmpeg": ["-version"],
    "playwright": ["--version"],
    "gemini": ["--version"],
    "opencode": ["--version"],
    "cursor": ["--version"],
    "stripe": ["--version"],
    "netlify": ["--version"],
    "vercel": ["--version"],
    "supabase": ["--version"],
    "render": ["--version"],
    "aws": ["--version"],
    "gcloud": ["--version"],
    "jq": ["--version"],
    "rg": ["--version"],
    "sqlite3": ["--version"],
}

TOOL_TERMS = {
    "Variant.com": ["variant.com"],
    "Magic Patterns": ["Magic Patterns", "magicpatterns.com", "magicpatterns"],
    "MagicPath": ["MagicPath", "magicpath.ai", "MagicPath AI"],
    "Refero": ["Refero", "refero.design", "styles.refero.design"],
    "21st.dev": ["21st.dev", "21st dev"],
    "UIVerse": ["UIVerse", "uiverse.io", "UI Verse"],
    "Mobbin": ["Mobbin", "mobbin.com"],
    "Inspo.page": ["inspo.page", "Website Inspo"],
    "Awwwards": ["Awwwards", "awwwards.com"],
    "Godly": ["Godly", "godly.website"],
    "Land-book": ["Land-book", "land-book.com", "landbook"],
    "Lapa Ninja": ["Lapa Ninja", "lapa.ninja"],
    "Nicely Done": ["Nicely Done", "nicelydone.club"],
    "Builder.io": ["Builder.io", "Visual Copilot", "builder.io"],
    "Relume": ["Relume", "relume.io"],
    "Subframe": ["Subframe", "subframe.com"],
    "Pageflows": ["Pageflows", "pageflows.com"],
    "Same.new": ["same.new"],
    "Lovable": ["Lovable", "lovable.dev"],
    "Bolt": ["Bolt.new", "bolt.new"],
    "v0": ["v0.dev"],
}

VERSION_SKIP = {
    "netlify": "installed; version not checked because this CLI touches the user preference file",
}


@dataclass
class CliTool:
    name: str
    available: bool
    path: str | None = None
    version: str | None = None
    error: str | None = None


@dataclass
class McpServer:
    name: str
    source: str
    transport: str = "unknown"
    command: str | None = None
    url: str | None = None


@dataclass
class DependencyManifest:
    path: str
    kind: str
    dependencies: list[str] = field(default_factory=list)


@dataclass
class ToolEvidence:
    tool: str
    path: str
    line: int
    text: str


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[redacted-url]"
    if not parsed.scheme or not parsed.netloc:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            cleaned[key] = "[redacted]" if SECRET_RE.search(str(key)) else redact(child)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if SECRET_RE.search(value):
            return "[redacted]"
        if value.startswith(("http://", "https://")):
            return redact_url(value)
    return value


def safe_read(path: Path, max_bytes: int = 2_000_000) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_config(path: Path) -> dict[str, Any] | None:
    text = safe_read(path)
    if text is None:
        return None
    try:
        if path.suffix == ".json":
            return json.loads(text)
        if path.suffix == ".toml" and tomllib is not None:
            return tomllib.loads(text)
    except Exception:
        return None
    return None


def summarize_mcp_config(name: str, config: Any, source: str) -> McpServer:
    if not isinstance(config, dict):
        return McpServer(name=name, source=source)
    cleaned = redact(config)
    command = cleaned.get("command")
    url = cleaned.get("url") or cleaned.get("endpoint")
    transport = cleaned.get("transport") or ("http" if url else "stdio" if command else "unknown")
    return McpServer(
        name=name,
        source=source,
        transport=str(transport),
        command=Path(str(command)).name if command else None,
        url=redact_url(str(url)) if isinstance(url, str) else None,
    )


def find_mcp_servers(obj: Any, source: str) -> list[McpServer]:
    servers: list[McpServer] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {"mcpServers", "mcp_servers"} and isinstance(value, dict):
                for server_name, config in value.items():
                    servers.append(summarize_mcp_config(str(server_name), config, source))
            else:
                servers.extend(find_mcp_servers(value, source))
    elif isinstance(obj, list):
        for item in obj:
            servers.extend(find_mcp_servers(item, source))
    return servers


def mcp_config_candidates(workspace: Path | None) -> list[Path]:
    home = Path.home()
    paths = [
        home / ".codex" / "config.toml",
        home / ".codex" / "mcp.json",
        home / ".claude.json",
        home / ".claude" / "mcp.json",
        home / ".cursor" / "mcp.json",
        home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
    ]
    if workspace:
        paths.extend([workspace / ".mcp.json", workspace / "mcp.json"])
    return paths


def collect_mcp_servers(workspace: Path | None) -> list[McpServer]:
    seen: set[tuple[str, str]] = set()
    servers: list[McpServer] = []
    for path in mcp_config_candidates(workspace):
        if not path.exists():
            continue
        data = parse_config(path)
        if data is None:
            continue
        for server in find_mcp_servers(data, str(path)):
            key = (server.name, server.source)
            if key not in seen:
                seen.add(key)
                servers.append(server)
    return servers


def cli_version(name: str, executable: str) -> tuple[str | None, str | None]:
    args = CLI_VERSION_ARGS.get(name, ["--version"])
    try:
        result = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
    except Exception as exc:
        return None, str(exc)
    output = (result.stdout or result.stderr).strip()
    if not output:
        return None, f"exit {result.returncode}"
    return output.splitlines()[0][:240], None


def collect_clis() -> list[CliTool]:
    tools: list[CliTool] = []
    for name in sorted(CLI_VERSION_ARGS):
        path = shutil.which(name)
        if not path:
            tools.append(CliTool(name=name, available=False))
            continue
        if name in VERSION_SKIP:
            tools.append(CliTool(name=name, available=True, path=path, version=VERSION_SKIP[name]))
            continue
        version, error = cli_version(name, path)
        tools.append(CliTool(name=name, available=True, path=path, version=version, error=error))
    return tools


def plugin_cache() -> list[str]:
    root = Path.home() / ".codex" / "plugins" / "cache"
    if not root.exists():
        return []
    try:
        return sorted(item.name for item in root.iterdir() if item.is_dir())
    except OSError:
        return []


def package_json_dependencies(path: Path) -> list[str]:
    text = safe_read(path)
    if text is None:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = data.get(key)
        if isinstance(value, dict):
            deps.update(value.keys())
    return sorted(deps)[:80]


def pyproject_dependencies(path: Path) -> list[str]:
    data = parse_config(path)
    if not isinstance(data, dict):
        return []
    deps: set[str] = set()
    project_deps = data.get("project", {}).get("dependencies", [])
    if isinstance(project_deps, list):
        deps.update(str(dep).split()[0] for dep in project_deps)
    optional = data.get("project", {}).get("optional-dependencies", {})
    if isinstance(optional, dict):
        for values in optional.values():
            if isinstance(values, list):
                deps.update(str(dep).split()[0] for dep in values)
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    if isinstance(poetry_deps, dict):
        deps.update(poetry_deps.keys())
    return sorted(deps)[:80]


def requirements_dependencies(path: Path) -> list[str]:
    text = safe_read(path)
    if text is None:
        return []
    deps = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        deps.append(re.split(r"[<>=~!; ]", stripped, maxsplit=1)[0])
    return sorted(set(deps))[:80]


def should_skip_dir(path: Path) -> bool:
    return path.name in {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


def collect_dependency_manifests(workspace: Path | None, max_depth: int = 4) -> list[DependencyManifest]:
    if not workspace or not workspace.exists():
        return []
    manifests: list[DependencyManifest] = []
    root_depth = len(workspace.parts)
    for current, dirs, files in os.walk(workspace):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if not should_skip_dir(current_path / name)]
        if len(current_path.parts) - root_depth > max_depth:
            dirs[:] = []
            continue
        for filename in files:
            if filename not in {"package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod"}:
                continue
            path = current_path / filename
            deps: list[str] = []
            if filename == "package.json":
                deps = package_json_dependencies(path)
            elif filename == "pyproject.toml":
                deps = pyproject_dependencies(path)
            elif filename == "requirements.txt":
                deps = requirements_dependencies(path)
            manifests.append(DependencyManifest(path=str(path), kind=filename, dependencies=deps))
    return manifests


def evidence_roots(workspace: Path | None) -> list[Path]:
    roots = [
        Path.home() / ".claude" / "plans",
        Path.home() / ".claude" / "zeus" / "INBOX",
        Path.home() / ".claude" / "skills",
        Path.home() / ".codex" / "skills",
    ]
    if workspace:
        roots.append(workspace)
    return [root for root in roots if root.exists()]


def iter_text_files(root: Path, max_files: int = 4000):
    count = 0
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if not should_skip_dir(current_path / name)]
        for filename in files:
            path = current_path / filename
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            count += 1
            if count > max_files:
                return
            yield path


def collect_tool_evidence(workspace: Path | None) -> list[ToolEvidence]:
    evidence: list[ToolEvidence] = []
    seen: set[tuple[str, str, int]] = set()
    lowered_terms = {
        tool: [term.lower() for term in terms]
        for tool, terms in TOOL_TERMS.items()
    }
    for root in evidence_roots(workspace):
        for path in iter_text_files(root):
            text = safe_read(path, max_bytes=1_500_000)
            if text is None:
                continue
            lines = text.splitlines()
            for index, line in enumerate(lines, start=1):
                lowered = line.lower()
                for tool, terms in lowered_terms.items():
                    if not any(term in lowered for term in terms):
                        continue
                    key = (tool, str(path), index)
                    if key in seen:
                        continue
                    seen.add(key)
                    evidence.append(ToolEvidence(tool=tool, path=str(path), line=index, text=line.strip()[:260]))
                    if len(evidence) >= 120:
                        return evidence
    return evidence


def build_inventory(workspace: Path | None) -> dict[str, Any]:
    clis = collect_clis()
    mcp_servers = collect_mcp_servers(workspace)
    manifests = collect_dependency_manifests(workspace)
    evidence = collect_tool_evidence(workspace)
    return {
        "workspace": str(workspace) if workspace else None,
        "mcp_servers": [asdict(server) for server in mcp_servers],
        "mcp_server_count": len(mcp_servers),
        "clis": [asdict(tool) for tool in clis],
        "available_cli_count": sum(1 for tool in clis if tool.available),
        "plugin_cache": plugin_cache(),
        "dependency_manifests": [asdict(manifest) for manifest in manifests],
        "tool_evidence": [asdict(hit) for hit in evidence],
        "subscription_rule": "Billing/subscription status is unknown unless confirmed by receipt, invoice, billing email, or account page evidence.",
    }


def write_markdown(path: Path, inventory: dict[str, Any]) -> None:
    lines = ["# Erich System Inventory", ""]
    lines.append(f"- Workspace: `{inventory.get('workspace') or 'none'}`")
    lines.append(f"- MCP servers found: `{inventory['mcp_server_count']}`")
    lines.append(f"- Available CLIs: `{inventory['available_cli_count']}`")
    lines.append(f"- Subscription rule: {inventory['subscription_rule']}")
    lines.append("")
    lines.append("## MCP Servers")
    lines.append("")
    if inventory["mcp_servers"]:
        for server in inventory["mcp_servers"]:
            details = []
            if server.get("transport"):
                details.append(server["transport"])
            if server.get("command"):
                details.append(f"command `{server['command']}`")
            if server.get("url"):
                details.append(f"url `{server['url']}`")
            suffix = f" ({', '.join(details)})" if details else ""
            lines.append(f"- `{server['name']}`{suffix} — `{server['source']}`")
    else:
        lines.append("- None found in checked local configs")
    lines.append("")
    lines.append("## CLIs")
    lines.append("")
    for tool in inventory["clis"]:
        if tool["available"]:
            version = f" — {tool['version']}" if tool.get("version") else ""
            lines.append(f"- `{tool['name']}` available at `{tool['path']}`{version}")
    unavailable = [tool["name"] for tool in inventory["clis"] if not tool["available"]]
    if unavailable:
        lines.append("")
        lines.append("Unavailable checked CLIs: " + ", ".join(f"`{name}`" for name in unavailable))
    lines.append("")
    lines.append("## Codex Plugin Cache")
    lines.append("")
    if inventory["plugin_cache"]:
        for name in inventory["plugin_cache"]:
            lines.append(f"- `{name}`")
    else:
        lines.append("- None found")
    lines.append("")
    lines.append("## Dependency Manifests")
    lines.append("")
    if inventory["dependency_manifests"]:
        for manifest in inventory["dependency_manifests"]:
            deps = ", ".join(f"`{dep}`" for dep in manifest["dependencies"][:20])
            lines.append(f"- `{manifest['kind']}` at `{manifest['path']}`")
            if deps:
                lines.append(f"  Dependencies: {deps}")
    else:
        lines.append("- None found in workspace")
    lines.append("")
    lines.append("## Tool And Subscription Evidence")
    lines.append("")
    if inventory["tool_evidence"]:
        for hit in inventory["tool_evidence"][:80]:
            lines.append(f"- `{hit['tool']}` — `{hit['path']}:{hit['line']}` — {hit['text']}")
    else:
        lines.append("- No local evidence hits for tracked tool terms")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inventory MCPs, CLIs, dependencies, plugins, and local tool evidence.")
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument("--out", default="/tmp/erich-system-inventory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else None
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory(workspace)
    json_path = out / "system.json"
    md_path = out / "system.md"
    json_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, inventory)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
