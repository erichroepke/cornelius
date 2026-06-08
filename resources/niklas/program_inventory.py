"""Inventory prior programs and code surfaces for Niklas CLI-making."""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .store import slugify, utcnow


PROGRAM_MARKERS = {
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "setup.py",
    "requirements.txt",
    "Makefile",
    "README.md",
    "AGENTS.md",
}
STRONG_MARKERS = {
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "setup.py",
    "requirements.txt",
    "Makefile",
}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".cache",
    ".next",
    ".pytest_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}


DEFAULT_PROGRAM_ROOTS = [
    "/Users/erichroepke/Desktop/PROJECTS",
    "/Users/erichroepke/Desktop/Niklas",
]
STRADA_PROGRAM_ROOTS = [
    "/Volumes/StradaConnect/Erich’s Mac Studio/Desktop/PROJECTS",
    "/Volumes/StradaConnect/Erich’s Mac Studio/Documents/Wideframe",
]
MASTER_ARCHIVE_ROOTS = [
    "/Volumes/MASTER 140 TB 1/2026/05-2026 SKILLS",
    "/Volumes/MASTER 140 TB 1/Unsorted/UNSORTED DESKTOP",
]


@dataclass
class ProgramRecord:
    id: str
    name: str
    family: str
    path: str
    status: str
    languages: list[str]
    markers: list[str]
    cli_entrypoints: list[str]
    scripts: list[str]
    cli_routes: list[str]
    package_name: str | None = None
    summary: str | None = None
    cli_leverage: int = 0


@dataclass
class ProgramFamily:
    name: str
    count: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)
    top_programs: list[dict[str, Any]] = field(default_factory=list)


def build_program_inventory(
    roots: Iterable[str | Path] | None = None,
    *,
    include_strada: bool = False,
    include_master_archives: bool = False,
    max_files: int = 1500,
    max_depth: int = 6,
) -> dict[str, Any]:
    selected_roots = [Path(root).expanduser() for root in roots or DEFAULT_PROGRAM_ROOTS]
    if include_strada:
        selected_roots.extend(Path(root) for root in STRADA_PROGRAM_ROOTS)
    if include_master_archives:
        selected_roots.extend(Path(root) for root in MASTER_ARCHIVE_ROOTS)
    selected_roots = list(dict.fromkeys(selected_roots))

    marker_groups: dict[Path, set[str]] = {}
    roots_scanned: list[str] = []
    skipped_roots: list[str] = []
    files_seen = 0

    for root in selected_roots:
        if not root.exists():
            skipped_roots.append(str(root))
            continue
        roots_scanned.append(str(root))
        for marker in iter_program_markers(root, max_depth=max_depth):
            if files_seen >= max_files:
                break
            files_seen += 1
            marker_groups.setdefault(marker.parent, set()).add(marker.name)
        if files_seen >= max_files:
            break

    records = [inspect_program(path, markers) for path, markers in marker_groups.items()]
    records = [record for record in records if record.markers and is_program_like(record)]
    records.sort(key=lambda item: (item.cli_leverage, len(item.markers), item.name), reverse=True)
    families = summarize_families(records)
    return {
        "generated_at": utcnow(),
        "method": "niklas-program-inventory-v1",
        "roots_scanned": roots_scanned,
        "skipped_roots": skipped_roots,
        "marker_files_seen": files_seen,
        "program_count": len(records),
        "families": [asdict(family) for family in families],
        "programs": [asdict(record) for record in records],
    }


def iter_program_markers(root: Path, *, max_depth: int) -> Iterable[Path]:
    root = root.resolve(strict=False)
    if root.is_file():
        if root.name in PROGRAM_MARKERS:
            yield root
        return

    def ignore_walk_error(_: OSError) -> None:
        return None

    for current_dir, dirnames, filenames in os.walk(root, topdown=True, onerror=ignore_walk_error):
        current = Path(current_dir)
        try:
            current_depth = len(current.relative_to(root).parts)
        except ValueError:
            current_depth = len(current.parts)

        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in SKIP_DIRS and not dirname.startswith(".git")
        ]
        if current_depth >= max_depth - 1:
            dirnames[:] = []

        for filename in filenames:
            if filename not in PROGRAM_MARKERS:
                continue
            if current_depth + 1 <= max_depth:
                yield current / filename


def inspect_program(path: Path, markers: set[str]) -> ProgramRecord:
    package_json = read_package_json(path / "package.json") if "package.json" in markers else {}
    pyproject = read_pyproject(path / "pyproject.toml") if "pyproject.toml" in markers else {}
    scripts = sorted(package_json.get("scripts", {}).keys()) if isinstance(package_json.get("scripts"), dict) else []
    cli_entrypoints = detect_cli_entrypoints(path, markers, package_json, pyproject)
    package_name = infer_package_name(path, package_json, pyproject)
    summary = read_summary(path)
    languages = infer_languages(markers, path)
    family = infer_family(path)
    status = infer_status(path)
    leverage = score_cli_leverage(path, markers, scripts, cli_entrypoints, languages, status)
    cli_routes = suggest_cli_routes(path, family, status, scripts, cli_entrypoints)
    return ProgramRecord(
        id=slugify(str(path)),
        name=package_name or path.name,
        family=family,
        path=str(path),
        status=status,
        languages=languages,
        markers=sorted(markers),
        cli_entrypoints=cli_entrypoints,
        scripts=scripts[:24],
        cli_routes=cli_routes,
        package_name=package_name,
        summary=summary,
        cli_leverage=leverage,
    )


def read_package_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_pyproject(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def detect_cli_entrypoints(
    path: Path,
    markers: set[str],
    package_json: dict[str, Any],
    pyproject: dict[str, Any],
) -> list[str]:
    out: list[str] = []
    bin_field = package_json.get("bin")
    if isinstance(bin_field, str):
        out.append(f"node-bin:{bin_field}")
    elif isinstance(bin_field, dict):
        out.extend(f"node-bin:{name}" for name in sorted(bin_field))

    project = pyproject.get("project", {}) if isinstance(pyproject.get("project"), dict) else {}
    scripts = project.get("scripts", {}) if isinstance(project.get("scripts"), dict) else {}
    out.extend(f"py-script:{name}" for name in sorted(scripts))

    if (path / "cli").exists() or any(part.lower() == "cli" for part in path.parts):
        out.append("path:cli")
    if "Makefile" in markers:
        out.append("make")
    if "AGENTS.md" in markers:
        out.append("agent-aware")
    return sorted(dict.fromkeys(out))


def infer_package_name(path: Path, package_json: dict[str, Any], pyproject: dict[str, Any]) -> str | None:
    if isinstance(package_json.get("name"), str):
        return str(package_json["name"])
    project = pyproject.get("project", {}) if isinstance(pyproject.get("project"), dict) else {}
    if isinstance(project.get("name"), str):
        return str(project["name"])
    poetry = pyproject.get("tool", {}).get("poetry", {}) if isinstance(pyproject.get("tool"), dict) else {}
    if isinstance(poetry.get("name"), str):
        return str(poetry["name"])
    return None


def read_summary(path: Path) -> str | None:
    readme = path / "README.md"
    if not readme.exists():
        return None
    try:
        for line in readme.read_text(encoding="utf-8", errors="replace").splitlines()[:25]:
            text = line.strip()
            if text.startswith("# "):
                return text.lstrip("#").strip()
    except OSError:
        return None
    return None


def infer_languages(markers: set[str], path: Path) -> list[str]:
    languages: set[str] = set()
    if "package.json" in markers:
        languages.add("javascript/typescript")
    if "pyproject.toml" in markers or "requirements.txt" in markers or "setup.py" in markers:
        languages.add("python")
    if "Cargo.toml" in markers:
        languages.add("rust")
    if "go.mod" in markers:
        languages.add("go")
    if "Makefile" in markers:
        languages.add("make")
    if not languages and {"README.md", "AGENTS.md"} & markers:
        languages.add("docs/process")
    return sorted(languages)


def infer_family(path: Path) -> str:
    upper_parts = [part.upper() for part in path.parts]
    known = [
        "ARC",
        "STEPT",
        "CONDUCTOR",
        "TRINITY",
        "CORNELIUS",
        "NIKLAS",
        "NIKLAS-BUILDER",
        "BERT",
        "RONGBUK",
        "ZEUS-SYNC",
        "ZEUS-TOOLS",
        "SKILLS-AND-AGENTS",
        "HOLD-MY-LEG",
        "JIMMY-CHIN",
        "PARAMETER-GOLF",
        "ER-LINEAR",
    ]
    for name in known:
        if name in upper_parts:
            return name
    if "UNSORTED DESKTOP" in str(path).upper():
        return "UNSORTED-DESKTOP"
    return path.parent.name.upper() if path.parent.name else "UNKNOWN"


def infer_status(path: Path) -> str:
    text = str(path).lower()
    if "/worktrees/" in text or "/worktree" in text or "-wt" in text:
        return "worktree"
    if "/archive/" in text or "/07-archive/" in text or "/_zeus-archive/" in text:
        return "archive"
    if "/_inbox/" in text or "/unsorted/" in text:
        return "inbox"
    if "template" in text:
        return "template"
    return "active"


def score_cli_leverage(
    path: Path,
    markers: set[str],
    scripts: list[str],
    cli_entrypoints: list[str],
    languages: list[str],
    status: str,
) -> int:
    score = len(markers) * 2 + len(cli_entrypoints) * 8 + len(scripts)
    name = str(path).lower()
    if any(word in name for word in ("cli", "mcp", "tools", "sync", "ingest", "linear", "calendar", "bert")):
        score += 10
    if "python" in languages and "javascript/typescript" in languages:
        score += 6
    if status == "active":
        score += 5
    elif status == "archive":
        score -= 2
    return score


def suggest_cli_routes(
    path: Path,
    family: str,
    status: str,
    scripts: list[str],
    cli_entrypoints: list[str],
) -> list[str]:
    name = path.name.lower()
    path_text = str(path).lower()
    routes: list[str] = []

    if family == "ARC":
        routes.extend(["niklas arc repo doctor <path>", "niklas arc worktree audit <path>"])
        if status == "worktree":
            routes.append("niklas arc pr-packet summarize <path>")
    elif family in {"STEPT", "CONDUCTOR"}:
        if "calendar" in name or "calendar" in path_text:
            routes.extend(
                [
                    "niklas stept calendar scan-drive <path>",
                    "niklas stept calendar onboarding-check <path>",
                    "niklas stept calendar migrate-plan <path>",
                ]
            )
        elif "wrap-ingest" in path_text:
            routes.append("niklas stept wrap-ingest dryrun <path>")
        else:
            routes.append("niklas stept app doctor <path>")
    elif family == "TRINITY":
        routes.extend(["niklas trinity cli run <task>", "niklas trinity mcp doctor <path>"])
    elif family in {"BERT", "RONGBUK", "NIKLAS-BUILDER", "CORNELIUS"} or "bert" in path_text:
        routes.extend(
            [
                "niklas bert stage run <stage> --root <path>",
                "niklas bert packet build <path>",
                "niklas bert source audit <path>",
            ]
        )
    elif family == "ZEUS-TOOLS":
        if "figma" in path_text:
            routes.append("niklas design figma export <path>")
        elif "tasks" in path_text:
            routes.extend(["niklas zeus tasks list <path>", "niklas zeus tasks guard <path>"])
        else:
            routes.append("niklas zeus tool doctor <path>")
    elif family == "ER-LINEAR":
        routes.extend(["niklas linear issue lookup <query>", "niklas linear project packet <path>"])
    elif family == "HOLD-MY-LEG":
        routes.extend(["niklas hml video ingest discover <path>", "niklas hml archive inventory <path>"])
    elif family == "UNSORTED-DESKTOP":
        routes.append("niklas archive promote-candidate <path>")
    elif family == "NIKLAS":
        routes.extend(["niklas source register <path>", "niklas context <question> --project Niklas"])

    if "make" in cli_entrypoints:
        routes.append("niklas program make <target> --path <path>")
    if scripts:
        routes.append("niklas program scripts list <path>")
    if any(entry.startswith(("node-bin:", "py-script:")) for entry in cli_entrypoints):
        routes.append("niklas program cli shim <path>")

    return sorted(dict.fromkeys(routes))[:8]


def is_program_like(record: ProgramRecord) -> bool:
    if set(record.markers) & STRONG_MARKERS:
        return True
    return bool(record.cli_entrypoints) or record.status in {"active", "template"} and record.family in {
        "CORNELIUS",
        "NIKLAS",
        "NIKLAS-BUILDER",
        "ZEUS-TOOLS",
        "SKILLS-AND-AGENTS",
    }


def summarize_families(records: list[ProgramRecord]) -> list[ProgramFamily]:
    by_family: dict[str, list[ProgramRecord]] = {}
    for record in records:
        by_family.setdefault(record.family, []).append(record)
    out: list[ProgramFamily] = []
    for name, family_records in sorted(by_family.items(), key=lambda pair: len(pair[1]), reverse=True):
        statuses: dict[str, int] = {}
        languages: set[str] = set()
        for record in family_records:
            statuses[record.status] = statuses.get(record.status, 0) + 1
            languages.update(record.languages)
        top = sorted(family_records, key=lambda item: item.cli_leverage, reverse=True)[:5]
        out.append(
            ProgramFamily(
                name=name,
                count=len(family_records),
                statuses=dict(sorted(statuses.items())),
                languages=sorted(languages),
                top_programs=[
                    {
                        "name": record.name,
                        "path": record.path,
                        "status": record.status,
                        "cli_leverage": record.cli_leverage,
                        "cli_entrypoints": record.cli_entrypoints,
                        "cli_routes": record.cli_routes[:3],
                    }
                    for record in top
                ],
            )
        )
    return out


def render_program_inventory_markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# Niklas Prior Program Inventory",
        "",
        f"Generated: {inventory['generated_at']}",
        f"Method: {inventory['method']}",
        f"Marker files seen: {inventory['marker_files_seen']}",
        f"Programs: {inventory['program_count']}",
        "",
        "## Roots Scanned",
        "",
    ]
    for root in inventory["roots_scanned"]:
        lines.append(f"- `{root}`")
    if inventory["skipped_roots"]:
        lines.extend(["", "## Skipped Roots", ""])
        for root in inventory["skipped_roots"]:
            lines.append(f"- `{root}`")

    lines.extend(["", "## Program Families", ""])
    for family in inventory["families"]:
        lines.extend(
            [
                f"### {family['name']}",
                "",
                f"- Program roots: `{family['count']}`",
                f"- Statuses: {', '.join(f'{key}={value}' for key, value in family['statuses'].items())}",
                f"- Languages: {', '.join(f'`{lang}`' for lang in family['languages'])}",
                "",
                "Top CLI-leverage roots:",
            ]
        )
        for program in family["top_programs"]:
            entrypoints = ", ".join(program["cli_entrypoints"]) or "none detected"
            routes = ", ".join(program["cli_routes"]) or "none suggested"
            lines.append(
                f"- `{program['name']}` ({program['status']}, score {program['cli_leverage']}) "
                f"at `{program['path']}` — {entrypoints}; routes: {routes}"
            )
        lines.append("")

    lines.extend(["## Highest CLI-Leverage Programs", ""])
    for program in inventory["programs"][:40]:
        entrypoints = ", ".join(program["cli_entrypoints"]) or "none detected"
        markers = ", ".join(program["markers"])
        routes = ", ".join(program["cli_routes"]) or "none suggested"
        lines.extend(
            [
                f"### {program['name']}",
                "",
                f"- Family: `{program['family']}`",
                f"- Status: `{program['status']}`",
                f"- CLI leverage: `{program['cli_leverage']}`",
                f"- Path: `{program['path']}`",
                f"- Languages: {', '.join(f'`{lang}`' for lang in program['languages'])}",
                f"- Markers: {markers}",
                f"- Entrypoints: {entrypoints}",
                f"- Scripts: {', '.join(program['scripts'][:12]) or 'none detected'}",
                f"- Potential routes: {routes}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_program_inventory(
    inventory: dict[str, Any],
    output_path: str | Path,
    *,
    markdown: bool = False,
) -> dict[str, str]:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if markdown:
        path.write_text(render_program_inventory_markdown(inventory), encoding="utf-8")
    else:
        path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return {"path": str(path), "format": "markdown" if markdown else "json"}
