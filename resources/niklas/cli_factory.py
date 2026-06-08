"""Discover modular CLI opportunities from Niklas source material."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .store import slugify, utcnow


TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".py",
    ".sh",
}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
}
MAX_FILE_BYTES = 350_000


DEFAULT_RELATIVE_ROOTS = [
    "01-Brain/wiki/Projects",
    "01-Brain/wiki/Permanent",
    "01-Brain/wiki/Sources",
    "04-Source-Registry",
    "06-Operations",
    "07-Archive/startup-pack",
]

STRADA_ROOTS = [
    "/Volumes/StradaConnect/Erich’s Mac Studio/Desktop/PROJECTS",
    "/Volumes/StradaConnect/Erich’s Mac Studio/Documents/Wideframe",
    "/Volumes/StradaConnect/Erich’s Mac Studio/Library/LaunchAgents",
]


@dataclass(frozen=True)
class SignalRule:
    signal: str
    domain: str
    weight: int
    keywords: tuple[str, ...]


@dataclass
class SourceHit:
    path: str
    title: str
    signals: list[str]
    matched_terms: list[str]


@dataclass
class CliCandidate:
    id: str
    domain: str
    title: str
    level: str
    confidence: float
    summary: str
    suggested_commands: list[str]
    components: list[str]
    bert_style_steps: list[str]
    evidence: list[SourceHit] = field(default_factory=list)
    score: int = 0


SIGNAL_RULES = [
    SignalRule(
        "footage-media",
        "video-ingest",
        5,
        ("video", "footage", "camera", "clip", "proxy", "transcode", "premiere", "wfseq"),
    ),
    SignalRule(
        "audio-sync",
        "audio-sync",
        6,
        ("sync", "lav", "timecode", "tentacle", "pluraleyes", "audio", "aaf"),
    ),
    SignalRule(
        "archive-structure",
        "archive-inventory",
        5,
        ("archive", "vault", "manifest", "inventory", "storage", "tier", "folder-only"),
    ),
    SignalRule(
        "source-registry",
        "source-register",
        4,
        ("source-registry", "source root", "registry", "moc", "project records", "niklas-native"),
    ),
    SignalRule(
        "bert-process",
        "bert-stage-runner",
        5,
        ("bert", "stage", "goal", "experts", "research", "blueprint", "moonshot", "pressure"),
    ),
    SignalRule(
        "zeus-process",
        "zeus-process-runner",
        4,
        ("zeus", "sidecar", "command-center", "active note", "actions for codex", "launchagent"),
    ),
    SignalRule(
        "local-ingest",
        "niklas-ingest",
        4,
        ("ingest", "raw", "inbox", "context pack", "duplicates", "sqlite", "graph"),
    ),
    SignalRule(
        "linear-execution",
        "linear-handoff",
        4,
        ("linear", "issue", "fit-check", "gitbranchname", "project = github pr", "closeout"),
    ),
    SignalRule(
        "runtime-health",
        "runtime-doctor",
        4,
        ("health", "status", "mcp", "plist", "launchagent", "daemon", "verify"),
    ),
    SignalRule(
        "cli-design",
        "cli-playbook",
        3,
        ("cli", "command", "subcommand", "tool-calling", "json output", "workflow"),
    ),
]


CANDIDATE_LIBRARY: dict[str, dict[str, Any]] = {
    "video-ingest": {
        "title": "Video Ingest",
        "level": "compound",
        "summary": "Turn shoot folders, proxies, Wideframe sequences, and editorial docs into a repeatable ingest surface.",
        "commands": [
            "niklas video ingest discover <root>",
            "niklas video ingest manifest <root>",
            "niklas video ingest register <manifest>",
            "niklas video ingest handoff <project>",
        ],
        "components": ["discover", "manifest", "register", "handoff"],
        "steps": ["setup", "inventory", "classify", "validate", "handoff"],
    },
    "audio-sync": {
        "title": "Audio Sync",
        "level": "feature",
        "summary": "Extract lav/timecode/sync-map work into a focused command module that can sit inside video ingest or run alone.",
        "commands": [
            "niklas video audio map <root>",
            "niklas video audio validate <sync-map>",
            "niklas video audio report <project>",
        ],
        "components": ["map", "validate", "report"],
        "steps": ["setup", "source-map", "match", "verify", "handoff"],
    },
    "archive-inventory": {
        "title": "Archive Inventory",
        "level": "compound",
        "summary": "Inventory archive roots without moving files, preserving folder-only rules and media provenance.",
        "commands": [
            "niklas archive inventory <root>",
            "niklas archive summarize <manifest>",
            "niklas archive tier-candidates <manifest>",
            "niklas archive register <project>",
        ],
        "components": ["inventory", "summarize", "tier-candidates", "register"],
        "steps": ["setup", "scan", "classify", "risk-check", "handoff"],
    },
    "source-register": {
        "title": "Source Register",
        "level": "task",
        "summary": "Create canonical source-root pointers and project records from existing registries and MOCs.",
        "commands": [
            "niklas source register <path>",
            "niklas source roots <project>",
            "niklas source gaps <project>",
        ],
        "components": ["register", "roots", "gaps"],
        "steps": ["setup", "read", "fit", "register", "handoff"],
    },
    "bert-stage-runner": {
        "title": "BERT Stage Runner",
        "level": "compound",
        "summary": "Expose the BERT staged method as composable setup/goal/research/expert-plan commands.",
        "commands": [
            "niklas bert setup <node>",
            "niklas bert goal <node>",
            "niklas bert research-scout <node>",
            "niklas bert expert-plans <node>",
            "niklas bert handoff <node>",
        ],
        "components": ["setup", "goal", "research-scout", "expert-plans", "handoff"],
        "steps": ["context", "placement", "neighborhood", "packet", "readiness", "goal", "handoff"],
    },
    "zeus-process-runner": {
        "title": "Zeus Process Runner",
        "level": "compound",
        "summary": "Convert sidecar, command-center, and LaunchAgent checks into a predictable operational command surface.",
        "commands": [
            "niklas zeus sidecar status",
            "niklas zeus action-list",
            "niklas zeus launchagents doctor",
            "niklas zeus handoff",
        ],
        "components": ["sidecar-status", "action-list", "launchagents-doctor", "handoff"],
        "steps": ["read-current", "verify-active", "list-actions", "doctor", "handoff"],
    },
    "niklas-ingest": {
        "title": "Niklas Ingest",
        "level": "feature",
        "summary": "Wrap local ingest/context/duplicates into repeatable source-pack routines.",
        "commands": [
            "niklas ingest <path> --project <name>",
            "niklas context <question> --project <name>",
            "niklas duplicates --project <name>",
            "niklas ingest-pack <root>",
        ],
        "components": ["ingest", "context", "duplicates", "ingest-pack"],
        "steps": ["source", "ingest", "retrieve", "dedupe", "handoff"],
    },
    "linear-handoff": {
        "title": "Linear Handoff",
        "level": "task",
        "summary": "Turn local process findings into Linear-safe issue/project handoff packets when Linear is available.",
        "commands": [
            "niklas linear lookup <query>",
            "niklas linear packet <source>",
            "niklas linear closeout <issue>",
        ],
        "components": ["lookup", "packet", "closeout"],
        "steps": ["triage", "lookup", "fit-check", "packet", "sync"],
    },
    "runtime-doctor": {
        "title": "Runtime Doctor",
        "level": "feature",
        "summary": "Check Niklas/Zeus runtime routes, MCP transport, LaunchAgents, and local database state.",
        "commands": [
            "niklas doctor status",
            "niklas doctor mcp",
            "niklas doctor launchagents",
            "niklas doctor db",
        ],
        "components": ["status", "mcp", "launchagents", "db"],
        "steps": ["probe", "classify", "explain", "repair-plan", "handoff"],
    },
    "cli-playbook": {
        "title": "CLI Playbook",
        "level": "task",
        "summary": "Use the accepted CLI research node to generate command naming, UX, JSON-output, and automation rules.",
        "commands": [
            "niklas cli-maker scan",
            "niklas cli-maker show <candidate>",
            "niklas cli-maker scaffold <candidate>",
        ],
        "components": ["scan", "show", "scaffold"],
        "steps": ["canon", "pattern", "frontier", "checklist", "handoff"],
    },
}


def default_roots(base_path: str | Path | None = None) -> list[Path]:
    base = find_niklas_root(base_path)
    return [base / rel for rel in DEFAULT_RELATIVE_ROOTS if (base / rel).exists()]


def find_niklas_root(base_path: str | Path | None = None) -> Path:
    starts = [Path(base_path).expanduser()] if base_path else [Path.cwd(), Path(__file__).resolve()]
    for start in starts:
        current = start.resolve(strict=False)
        if current.is_file():
            current = current.parent
        for candidate in [current, *current.parents]:
            if (candidate / "01-Brain").exists() and (candidate / "04-Source-Registry").exists():
                return candidate
    return Path(base_path).resolve() if base_path else Path.cwd().resolve()


def strada_roots() -> list[Path]:
    return [Path(raw) for raw in STRADA_ROOTS if Path(raw).exists()]


def build_cli_catalog(
    roots: Iterable[str | Path] | None = None,
    *,
    include_strada: bool = False,
    max_files: int = 500,
    max_depth: int = 5,
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Scan source roots and return modular CLI candidates with evidence."""
    selected_roots = [Path(root).expanduser() for root in roots or default_roots(base_path)]
    if include_strada:
        selected_roots.extend(strada_roots())
    selected_roots = list(dict.fromkeys(selected_roots))

    candidates = _empty_candidates()
    files_scanned = 0
    roots_seen: list[str] = []
    skipped_roots: list[str] = []

    for root in selected_roots:
        if not root.exists():
            skipped_roots.append(str(root))
            continue
        roots_seen.append(str(root))
        for file_path in iter_source_files(root, max_depth=max_depth):
            if files_scanned >= max_files:
                break
            files_scanned += 1
            hit_scores = score_source(file_path)
            if not hit_scores:
                continue
            for domain, payload in hit_scores.items():
                candidate = candidates[domain]
                candidate.score += int(payload["score"])
                if len(candidate.evidence) < 8:
                    candidate.evidence.append(
                        SourceHit(
                            path=str(file_path),
                            title=payload["title"],
                            signals=payload["signals"],
                            matched_terms=payload["terms"],
                        )
                    )
            if files_scanned >= max_files:
                break

    populated = [candidate for candidate in candidates.values() if candidate.score > 0]
    populated.sort(key=lambda item: (item.score, len(item.evidence)), reverse=True)
    for candidate in populated:
        candidate.confidence = min(0.95, round(0.35 + candidate.score / 80, 2))

    combinations = suggest_combinations(populated)
    return {
        "generated_at": utcnow(),
        "method": "niklas-cli-maker-v1",
        "roots_scanned": roots_seen,
        "skipped_roots": skipped_roots,
        "files_scanned": files_scanned,
        "candidate_count": len(populated),
        "candidates": [candidate_to_dict(candidate) for candidate in populated],
        "combinations": combinations,
    }


def iter_source_files(root: Path, *, max_depth: int) -> Iterable[Path]:
    if root.is_file():
        if is_text_file(root):
            yield root
        return
    root = root.resolve(strict=False)
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        if any(part in SKIP_DIRS for part in item.parts):
            continue
        try:
            depth = len(item.relative_to(root).parts)
        except ValueError:
            depth = len(item.parts)
        if depth > max_depth:
            continue
        if is_text_file(item):
            yield item


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return False
    try:
        return path.stat().st_size <= MAX_FILE_BYTES
    except OSError:
        return False


def score_source(path: Path) -> dict[str, dict[str, Any]]:
    text = read_source_text(path)
    if not text:
        return {}
    haystack = f"{path.name}\n{text}".lower()
    title = extract_title(path, text)
    by_domain: dict[str, dict[str, Any]] = {}
    for rule in SIGNAL_RULES:
        terms = [term for term in rule.keywords if term.lower() in haystack]
        if not terms:
            continue
        if rule.domain == "audio-sync" and not (
            {"lav", "timecode", "tentacle", "pluraleyes", "audio", "aaf"} & set(terms)
        ):
            continue
        payload = by_domain.setdefault(
            rule.domain,
            {"score": 0, "signals": set(), "terms": set(), "title": title},
        )
        payload["score"] += rule.weight * len(terms)
        payload["signals"].add(rule.signal)
        payload["terms"].update(terms)
    for payload in by_domain.values():
        payload["signals"] = sorted(payload["signals"])
        payload["terms"] = sorted(payload["terms"])
    return by_domain


def read_source_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_BYTES]
    except OSError:
        return ""


def extract_title(path: Path, text: str) -> str:
    for line in text.splitlines()[:30]:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.lstrip("#").strip()
        if stripped.lower().startswith("title:"):
            return stripped.split(":", 1)[1].strip().strip('"')
    return path.stem.replace("-", " ").replace("_", " ").strip() or path.name


def _empty_candidates() -> dict[str, CliCandidate]:
    candidates: dict[str, CliCandidate] = {}
    for domain, data in CANDIDATE_LIBRARY.items():
        candidates[domain] = CliCandidate(
            id=slugify(domain),
            domain=domain,
            title=str(data["title"]),
            level=str(data["level"]),
            confidence=0.0,
            summary=str(data["summary"]),
            suggested_commands=list(data["commands"]),
            components=list(data["components"]),
            bert_style_steps=list(data["steps"]),
        )
    return candidates


def candidate_to_dict(candidate: CliCandidate) -> dict[str, Any]:
    out = asdict(candidate)
    out["evidence"] = [asdict(hit) for hit in candidate.evidence]
    return out


def suggest_combinations(candidates: list[CliCandidate]) -> list[dict[str, Any]]:
    domains = {candidate.domain for candidate in candidates}
    recipes = [
        (
            "hml-video-ingest-stack",
            ["archive-inventory", "video-ingest", "audio-sync", "source-register"],
            "HML / documentary ingest stack: inventory the archive, map media, validate lav sync, then register durable source roots.",
        ),
        (
            "niklas-builder-stack",
            ["niklas-ingest", "cli-playbook", "bert-stage-runner", "runtime-doctor"],
            "Niklas Builder stack: ingest strategy docs, turn them into CLI candidates, stage via BERT, and verify runtime health.",
        ),
        (
            "strada-ops-stack",
            ["zeus-process-runner", "runtime-doctor", "archive-inventory", "source-register"],
            "Strada/Mac Studio operations stack: inspect mounted project roots, LaunchAgents, archived manifests, and source pointers.",
        ),
        (
            "linearized-cli-workflow",
            ["cli-playbook", "bert-stage-runner", "linear-handoff"],
            "Planning-to-execution stack: use CLI research, run BERT-style setup, then produce Linear-safe handoffs.",
        ),
    ]
    out: list[dict[str, Any]] = []
    for recipe_id, required, summary in recipes:
        present = [domain for domain in required if domain in domains]
        if len(present) < 2:
            continue
        out.append(
            {
                "id": recipe_id,
                "summary": summary,
                "present_modules": present,
                "missing_modules": [domain for domain in required if domain not in domains],
                "suggested_entrypoint": f"niklas compose {recipe_id}",
            }
        )
    return out


def render_markdown_catalog(catalog: dict[str, Any]) -> str:
    lines = [
        "# Niklas CLI Maker Catalog",
        "",
        f"Generated: {catalog['generated_at']}",
        f"Method: {catalog['method']}",
        f"Files scanned: {catalog['files_scanned']}",
        f"Candidates: {catalog['candidate_count']}",
        "",
        "## Roots Scanned",
        "",
    ]
    for root in catalog["roots_scanned"]:
        lines.append(f"- `{root}`")
    if catalog["skipped_roots"]:
        lines.extend(["", "## Skipped Roots", ""])
        for root in catalog["skipped_roots"]:
            lines.append(f"- `{root}`")

    lines.extend(["", "## Candidate Modules", ""])
    for candidate in catalog["candidates"]:
        lines.extend(
            [
                f"### {candidate['title']}",
                "",
                f"- Domain: `{candidate['domain']}`",
                f"- Level: `{candidate['level']}`",
                f"- Confidence: `{candidate['confidence']}`",
                f"- Score: `{candidate['score']}`",
                f"- Summary: {candidate['summary']}",
                f"- Components: {', '.join(f'`{part}`' for part in candidate['components'])}",
                f"- BERT-style steps: {', '.join(f'`{step}`' for step in candidate['bert_style_steps'])}",
                "",
                "Suggested commands:",
                "",
            ]
        )
        for command in candidate["suggested_commands"]:
            lines.append(f"- `{command}`")
        lines.extend(["", "Evidence:"])
        for hit in candidate["evidence"][:5]:
            terms = ", ".join(hit["matched_terms"][:8])
            lines.append(f"- `{hit['path']}` — {hit['title']} ({terms})")
        lines.append("")

    lines.extend(["## Combinations", ""])
    for combo in catalog["combinations"]:
        lines.extend(
            [
                f"### {combo['id']}",
                "",
                combo["summary"],
                "",
                f"- Present: {', '.join(f'`{item}`' for item in combo['present_modules'])}",
                f"- Missing: {', '.join(f'`{item}`' for item in combo['missing_modules']) or '`none`'}",
                f"- Entrypoint: `{combo['suggested_entrypoint']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_catalog(catalog: dict[str, Any], output_path: str | Path, *, markdown: bool = False) -> dict[str, str]:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if markdown:
        path.write_text(render_markdown_catalog(catalog), encoding="utf-8")
    else:
        path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return {"path": str(path), "format": "markdown" if markdown else "json"}
