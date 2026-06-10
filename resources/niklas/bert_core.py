"""Shared read-first BERT runtime payloads for CLI and MCP."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .linear import LinearClient
from .store import NiklasStore


BERT_VERSION = "pilot-cli-mcp-v1"
BERT_STATE_SCHEMA = "bert-state-v2"
BERT_STATE_SCHEMA_V1 = "bert-state-v1"
READ_ONLY_MODE = "read_only_dry_run"
APPLY_BLOCKER = "BERT Runtime Adapter Contract has not accepted write/apply boundaries."


STAGE_ORDER = [
    {
        "id": "0",
        "name": "0_BERT: PROJECT SETUP",
        "command": "setup",
        "purpose": "Place the problem, verify fit, create project parameters, and hand off safely.",
        "expected_outputs": [
            "Linear and local placement snapshot",
            "Project-parameters handoff",
            "Readiness and blocked-write report",
        ],
    },
    {
        "id": "1",
        "name": "1_BERT: GOAL",
        "command": "goal",
        "purpose": "Turn the rough intent into the best possible goal and routed questions.",
        "expected_outputs": [
            "Goal/question dry-run packet",
            "Deferred later-layer decisions",
            "Next Research Scout handoff prompt",
        ],
    },
    {
        "id": "2",
        "name": "2 - BERT Research Scout",
        "command": "research-scout",
        "purpose": "Find the strongest sources, source-makers, constraints, and internal overlap.",
        "expected_outputs": [
            "Source-route dry-run packet",
            "Free/public-first acquisition boundary",
            "Internal overlap search plan",
        ],
    },
    {
        "id": "3",
        "name": "BERT Expert Plans",
        "command": "expert-plans",
        "purpose": "Synthesize expert-informed routes, tradeoffs, assumptions, and next moves.",
        "expected_outputs": [
            "Expert-plan route menu",
            "Recommended route and alternatives",
            "Decision-ready assumptions and risks",
        ],
    },
    {
        "id": "handoff",
        "name": "BERT Handoff",
        "command": "handoff",
        "purpose": "Package the result so another agent or CLI run can resume without chat history.",
        "expected_outputs": [
            "First-read pickup packet",
            "Verification and closeback summary",
            "Blocked writes and next safe action",
        ],
    },
]


NAMING = [
    {
        "label": "BERT",
        "kind": "canonical CLI/product/protocol root",
        "status": "use this for the executable name and product root",
        "notes": "The standalone command is `bert`; Linear root is top-level `BERT`.",
    },
    {
        "label": "BERT GMVP",
        "kind": "current Linear initiative",
        "status": "active current MVP wave",
        "notes": "GMVP means G-Stack-shaped MVP. It was renamed from BERT MVP in Linear.",
    },
    {
        "label": "BERT MVP",
        "kind": "legacy/local/GitHub naming",
        "status": "keep as compatibility path until renamed deliberately",
        "notes": "Local repo and many files still use BERT-MVP / bert-mvp.",
    },
    {
        "label": "BERT GVPMP / GVP",
        "kind": "non-canonical shorthand",
        "status": "do not use in durable docs",
        "notes": "Treat this as spoken confusion around GMVP unless defined separately.",
    },
]


EXPECTED_MCP_TOOLS = [
    "bert_on",
    "bert_status",
    "bert_doctor",
    "bert_first_read",
    "bert_solve",
    "bert_stage",
    "bert_linear_snapshot",
    "bert_project_template",
    "bert_project_analyze",
    "bert_project_create_plan",
    "bert_project_adopt",
    "bert_project_open",
    "bert_node_template",
    "bert_node_create_plan",
    "bert_node_locate",
    "bert_node_start_plan",
    "bert_node_stages",
    "bert_node_map",
    "bert_node_spawn_children_plan",
    "bert_stage_draft",
    "bert_accept",
    "bert_next",
]


ROOT_DEV_STAGES = [
    ("0-ingest", "Ingest", "Project-root intake. Only L1M1 gets this stage."),
    ("1-brainstorm", "Brainstorm", "Generate and structure possible directions."),
    ("2-experts", "Experts", "Name expert perspectives and missing expertise."),
    ("3-research", "Research", "Collect sources, facts, constraints, and uncertainty."),
    ("4-blueprint", "Blueprint", "Turn the route into an executable plan."),
    ("5-summit", "Summit", "Compare perspectives and resolve conflicts."),
    ("6-pressure-test", "PressureTest", "Find risks, weak assumptions, and failure modes."),
    ("7-map", "MAP", "Write the forward-facing highest-level plan and child-node map."),
]


CHILD_DEV_STAGES = [stage for stage in ROOT_DEV_STAGES if stage[0] != "0-ingest"]


HIERARCHY_CONTRACT = {
    "local_root": ".BERT",
    "root_node": "L1M1",
    "local_tree": ".BERT/L1M1/L2M*/L3M*/...",
    "source_of_truth": "local_bert_packet",
    "linear_role": "mirror_and_status_surface",
    "niklas_role": "knowledge_graph_and_context_surface",
    "map_rule": "Every LxMy node ends in MAP.md: the forward-facing highest-level necessary steps for that node's scope.",
    "recursion_rule": "Accepted MAP.md steps become the next level of L/M child nodes.",
    "linear_defaults": {
        "L1M1": "Linear Initiative",
        "child_planning_node": "Linear Sub-initiative",
        "execution_package": "Linear Project",
        "task": "Linear Issue",
    },
}


@dataclass(frozen=True)
class BertEnvironment:
    home: Path
    niklas_root: Path
    runtime_root: Path
    builder_root: Path
    bert_root: Path
    bert_mvp: Path
    skill_pack: Path
    linear_buildout: Path
    legacy_builder_cli: Path
    canonical_command: Path
    niklas_cli: Path
    mcp_server: Path
    db_path: Path

    @classmethod
    def default(cls) -> "BertEnvironment":
        home = Path.home()
        niklas_root = home / "Desktop" / "Niklas"
        runtime_root = niklas_root / "03-Runtime" / "Cornelius"
        builder_root = home / "Desktop" / "PROJECTS" / "NIKLAS-BUILDER"
        bert_root = builder_root / "BERT"
        return cls(
            home=home,
            niklas_root=niklas_root,
            runtime_root=runtime_root,
            builder_root=builder_root,
            bert_root=bert_root,
            bert_mvp=bert_root / "BERT-MVP",
            skill_pack=bert_root / "BERT-SKILL-PACK",
            linear_buildout=bert_root / "BERT-LINEAR-BUILDOUT" / "5-2026_BERT_LINEAR_BUILDOUT",
            legacy_builder_cli=bert_root / "bin" / "niklas-bert",
            canonical_command=niklas_root / "bert",
            niklas_cli=niklas_root / "niklas",
            mcp_server=runtime_root / "resources" / "brain-graph" / "mcp_server.py",
            db_path=runtime_root / "resources" / "niklas" / "data" / "niklas.sqlite",
        )

    @property
    def first_read(self) -> list[Path]:
        return [
            self.bert_root / "README.md",
            self.builder_root / "docs" / "reference" / "BERT_INTEGRATION_MAP.md",
            self.bert_mvp / ".linear-config",
            self.bert_mvp / "BERT" / "LINEAR.md",
            self.bert_mvp / "BERT" / "BERT_PROGRESS.md",
            self.bert_mvp / "BERT" / "handoffs" / "NIKLAS_BUILDER_BERT_CLI_HANDOFF_2026-06-03.md",
            self.bert_mvp / "BERT" / "handoffs" / "CLOUD_CODE_PICKUP_2026-05-28.md",
            self.bert_mvp / "BERT" / "stages" / "01-goal-app" / "1_BERT_GOAL.md",
            self.bert_mvp / "BERT" / "stage-zero" / "project-setup-skill" / "stages" / "01-goal" / "goal_V8.md",
            self.bert_mvp / "BERT" / "stage-zero" / "project-setup-skill" / "stages" / "02-experts" / "experts_V7.md",
            self.bert_mvp / "BERT" / "stage-zero" / "project-setup-skill" / "stages" / "03-expert-plans" / "expert_plans_V1.md",
        ]

    @property
    def projects_root(self) -> Path:
        return self.bert_root / "projects"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def path_state(path: Path) -> dict[str, Any]:
    return {"path": str(path), "exists": path.exists()}


def run_command(args: list[str], cwd: Path) -> dict[str, Any]:
    if not cwd.exists():
        return {"ok": False, "returncode": None, "stdout": "", "stderr": f"missing cwd: {cwd}"}
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def git_branch(path: Path) -> str:
    result = run_command(["git", "status", "--short", "--branch"], path)
    output = result["stdout"] or result["stderr"] or result.get("error") or ""
    return output.splitlines()[0] if output else "not a git repo or no output"


def read_linear_config(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path), "exists": path.exists(), "values": {}}
    if not path.exists():
        return payload
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    payload["values"] = values
    return payload


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "untitled-bert-project"


def parse_lm_node(node_id: str) -> dict[str, int | str]:
    match = re.fullmatch(r"L([1-9][0-9]*)M([1-9][0-9]*)", node_id.strip().upper())
    if not match:
        raise ValueError(f"invalid BERT node id {node_id!r}; expected L<level>M<map>, e.g. L1M1 or L2M3")
    level = int(match.group(1))
    map_number = int(match.group(2))
    return {"id": f"L{level}M{map_number}", "level": level, "map": map_number}


def normalize_node_path(node_path: str) -> list[str]:
    parts = [part.strip().upper() for part in node_path.split("/") if part.strip()]
    if not parts:
        raise ValueError("node path cannot be empty")
    previous_level = 0
    for index, part in enumerate(parts):
        parsed = parse_lm_node(part)
        level = int(parsed["level"])
        if index == 0 and parsed["id"] != "L1M1":
            raise ValueError("BERT node paths must start at L1M1")
        if index > 0 and level != previous_level + 1:
            raise ValueError(f"node path {node_path!r} skips a level at {part}")
        previous_level = level
    return [str(parse_lm_node(part)["id"]) for part in parts]


def node_stages(node_id: str) -> list[tuple[str, str, str]]:
    parsed = parse_lm_node(node_id)
    return ROOT_DEV_STAGES if parsed["id"] == "L1M1" else CHILD_DEV_STAGES


def linear_mirror_for_node(node_path: list[str]) -> dict[str, Any]:
    node_id = node_path[-1]
    parsed = parse_lm_node(node_id)
    is_root = node_id == "L1M1"
    return {
        "node_path": "/".join(node_path),
        "node_id": node_id,
        "default_linear_type": "Initiative" if is_root else "Sub-initiative",
        "default_linear_role": (
            "highest-level project initiative"
            if is_root
            else "child initiative or major plan step under the parent node"
        ),
        "execution_boundary": "Promote a node step to Linear Project only when it becomes a concrete shippable work package.",
        "task_boundary": "Create Linear Issues only for task-level execution inside a Project.",
        "parent_linear_type": None if is_root else "Initiative or Sub-initiative",
        "level": parsed["level"],
        "map": parsed["map"],
    }


def resolve_projects_root(env: BertEnvironment, projects_root: str | Path | None = None) -> Path:
    return Path(projects_root).expanduser() if projects_root else env.projects_root


def resolve_project_dir(
    env: BertEnvironment,
    project: str | None,
    *,
    slug: str | None = None,
    projects_root: str | Path | None = None,
) -> Path:
    if project:
        project_path = Path(project).expanduser()
        if project in {".", ".."} or project.startswith("~") or project_path.is_absolute() or "/" in project or project_path.exists():
            return project_path
    root = resolve_projects_root(env, projects_root)
    return root / (slug or slugify(project or "untitled-bert-project"))


def _workspace_state(
    env: BertEnvironment,
    project: str,
    *,
    projects_root: str | Path | None = None,
) -> dict[str, Any]:
    host_project_dir = resolve_project_dir(env, project, projects_root=projects_root)
    workspace_dir = host_project_dir / ".BERT" if (host_project_dir / ".BERT").exists() else host_project_dir
    return {
        "host_project_dir": host_project_dir,
        "bert_workspace_dir": workspace_dir,
        "hidden_workspace": workspace_dir.name == ".BERT",
        "workspace_exists": workspace_dir.exists(),
        "root_exists": (workspace_dir / "L1M1" / "_node.md").exists(),
        "initialized": workspace_dir.exists() and (workspace_dir / "L1M1" / "_node.md").exists(),
    }


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _scaffold_file(path: Path, content: str) -> dict[str, Any]:
    return {"path": str(path), "content": content}


def _apply_scaffold(dirs: list[Path], files: list[dict[str, Any]]) -> dict[str, Any]:
    result = {
        "created_dirs": [],
        "existing_dirs": [],
        "written_files": [],
        "skipped_existing_files": [],
    }
    for directory in dirs:
        if directory.exists():
            result["existing_dirs"].append(str(directory))
        else:
            directory.mkdir(parents=True, exist_ok=True)
            result["created_dirs"].append(str(directory))
    for item in files:
        path = Path(item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            result["skipped_existing_files"].append(str(path))
            continue
        path.write_text(item["content"], encoding="utf-8")
        result["written_files"].append(str(path))
    return result


def _state_file(
    project_dir: Path,
    *,
    host_dir: Path,
    name: str,
    slug: str,
    linear_anchor: str | None,
    niklas_anchor: str | None,
    generated: str,
) -> dict[str, Any]:
    state = {
        "schema": BERT_STATE_SCHEMA,
        "project_name": name,
        "project_slug": slug,
        "host_project_dir": str(host_dir),
        "bert_workspace_dir": str(project_dir),
        "root_node": "L1M1",
        "current_node": "L1M1",
        "current_stage": "0-ingest",
        "initialized_at": generated,
        "updated_at": generated,
        "linear_anchor": linear_anchor or "pending",
        "niklas_anchor": niklas_anchor or "pending",
        "stages": {"L1M1": {}},
        "write_surfaces": {
            "local_markdown": "apply_gated",
            "linear": "blocked_until_apply_contract",
            "niklas_graph": "blocked_until_write_token",
        },
    }
    return _scaffold_file(project_dir / "state.json", json.dumps(state, indent=2) + "\n")


def _project_files(
    project_dir: Path,
    *,
    host_dir: Path,
    name: str,
    slug: str,
    linear_anchor: str | None,
    niklas_anchor: str | None,
) -> list[dict[str, Any]]:
    generated = utcnow()
    return [
        _state_file(
            project_dir,
            host_dir=host_dir,
            name=name,
            slug=slug,
            linear_anchor=linear_anchor,
            niklas_anchor=niklas_anchor,
            generated=generated,
        ),
        _scaffold_file(
            project_dir / ".linear-config",
            "\n".join(
                [
                    "team: ERI",
                    "team_name: Erichzeus",
                    f"bert_project: {name}",
                    f"bert_project_slug: {slug}",
                    "root_node: L1M1",
                    f"linear_anchor: {linear_anchor or 'pending'}",
                    f"niklas_anchor: {niklas_anchor or 'pending'}",
                    "write_enabled: false",
                    "",
                ]
            ),
        ),
        _scaffold_file(
            project_dir / "PROJECT.md",
            f"""---
kind: bert_project
name: {name}
slug: {slug}
root_node: L1M1
linear_anchor: {linear_anchor or "pending"}
niklas_anchor: {niklas_anchor or "pending"}
generated_at: {generated}
---

# {name}

This is the BERT project packet. `L1M1` is the root map node. Every `LxMy`
node beneath it is a complete BERT project node with its own stage outputs.

## Workflow

`L1M1` runs ingest once, then the BERT thinking pipeline.
Child nodes inherit parent context and start at brainstorm.

Every node ends by writing `MAP.md`. That map is the forward-facing final
artifact for the node: the highest-level necessary steps to accomplish the
node's current goal. Those numbered steps are the candidates for the next
level of child nodes. `L1M1/MAP.md` maps the whole project; `L1M1/L2M1/MAP.md`
maps the first major step; this repeats recursively as `L3M*`, `L4M*`, and so on.

## Local Tree Contract

```text
BERT project folder
└── .BERT/
    └── L1M1/          mirrors the highest-level Linear Initiative
        └── MAP.md     highest-level plan for the whole project
        └── L2M1/      mirrors a child initiative or major plan step
            └── MAP.md
            └── L3M1/  deeper step
```

Local `.BERT` packets own the recursive planning artifacts. Linear mirrors
the hierarchy and status. Niklas provides graph/context lookup.
""",
        ),
        _scaffold_file(
            project_dir / "LINEAR.md",
            f"""# Linear Mirror

- Linear anchor: {linear_anchor or "pending"}
- Root BERT node: `L1M1`
- Default mirror:
  - `L1M1` -> Linear Initiative
  - child planning nodes (`L2M*`, `L3M*`, ...) -> Linear Sub-initiatives
  - concrete shippable work packages -> Linear Projects
  - task-level execution -> Linear Issues
- Rule: Linear mirrors hierarchy, status, and closeback. Local Markdown keeps
  the full recursive stage packet and remains the planning artifact source.
""",
        ),
        _scaffold_file(
            project_dir / "NIKLAS.md",
            f"""# Niklas Linkage

- Niklas project/node anchor: {niklas_anchor or "pending"}
- Root BERT node: `L1M1`
- Rule: Niklas is the durable graph/link layer. This folder is the working
  projection and stage packet.
""",
        ),
        _scaffold_file(
            project_dir / "STATUS.md",
            f"""# Status

- Created: {generated}
- Current node: `L1M1`
- Current stage: `0-ingest`
- Writes to Linear/Niklas graph: blocked until the BERT adapter contract accepts apply semantics.
""",
        ),
        _scaffold_file(
            project_dir / "inbox" / "README.md",
            "# Inbox\n\nDrop unprocessed project inputs here before `L1M1/dev/0-ingest` organizes them.\n",
        ),
    ]


def _node_files(node_dir: Path, node_path: list[str], *, project_name: str | None = None) -> list[dict[str, Any]]:
    node_id = node_path[-1]
    parsed = parse_lm_node(node_id)
    parent = "/".join(node_path[:-1]) or "(root)"
    stages = node_stages(node_id)
    stage_lines = "\n".join(f"- `{folder}` - {purpose}" for folder, _prefix, purpose in stages)
    next_level = int(parsed["level"]) + 1
    next_child_a = f"L{next_level}M1"
    next_child_b = f"L{next_level}M2"
    linear_mirror = linear_mirror_for_node(node_path)
    child_rule = (
        "This is `L1M1`, so it owns `0-ingest` for project-root intake."
        if node_id == "L1M1"
        else "This is a child node, so it inherits parent context and starts at `1-brainstorm`."
    )
    map_scope = (
        "the whole project"
        if node_id == "L1M1"
        else f"the parent step represented by `{'/'.join(node_path)}`"
    )
    map_stub = (
        f"Step 1 can become `{next_child_a}`, Step 2 can become `{next_child_b}`, and so on."
        if node_id == "L1M1"
        else f"Each step can become a child node such as `{next_child_a}` or `{next_child_b}` under this path."
    )
    files = [
        _scaffold_file(
            node_dir / "_node.md",
            f"""---
kind: bert_lm_node
node_path: {'/'.join(node_path)}
node_id: {node_id}
level: {parsed['level']}
map: {parsed['map']}
parent: {parent}
project: {project_name or "pending"}
linear_mirror_type: {linear_mirror['default_linear_type']}
linear_mirror_role: {linear_mirror['default_linear_role']}
---

# {node_id}

{child_rule}

## Linear Mirror

- Default Linear type: {linear_mirror['default_linear_type']}
- Default Linear role: {linear_mirror['default_linear_role']}
- Execution boundary: {linear_mirror['execution_boundary']}
- Task boundary: {linear_mirror['task_boundary']}

## Stage Folders

{stage_lines}

## Recursive MAP Contract

This node is a planning run for {map_scope}. Its final artifact is `MAP.md`.
`MAP.md` must be readable as the forward-facing plan for this scope: the
highest-level necessary steps to accomplish the node goal. Each numbered step
can become a next-level child node (`{next_child_a}`, `{next_child_b}`, etc.)
that runs the same process again for that smaller scope.
""",
        ),
        _scaffold_file(
            node_dir / "MAP.md",
            f"""---
kind: bert_map
node_path: {'/'.join(node_path)}
node_id: {node_id}
status: draft
linear_mirror_type: {linear_mirror['default_linear_type']}
---

# MAP {node_id}

This is the final product of `{node_id}`: a forward-facing plan of the
highest-level necessary steps for this node's scope.

## Node Goal

TBD.

## Highest-Level Necessary Steps

1. TBD
   - Why this is necessary:
   - Done when:
   - Child node: `{next_child_a}`

2. TBD
   - Why this is necessary:
   - Done when:
   - Child node: `{next_child_b}`

## Child Node Decomposition

{map_stub}

## Notes For Next Level

When a step is accepted, create its child node and repeat the same process:
brainstorm, expert perspectives, research, blueprint, summit, pressure-test,
then another forward-facing `MAP.md` for that child scope.
""",
        ),
    ]
    for folder, prefix, purpose in stages:
        files.append(
            _scaffold_file(
                node_dir / "dev" / folder / "README.md",
                f"# {prefix} {node_id}\n\n{purpose}\n\nExpected stage file: `{prefix}_{node_id}_V1.md`.\n",
            )
        )
    return files


def _node_dirs(node_dir: Path, node_id: str) -> list[Path]:
    return [node_dir, node_dir / "dev"] + [node_dir / "dev" / stage[0] for stage in node_stages(node_id)]


def build_node_template_payload(node_path: str = "L1M1") -> dict[str, Any]:
    parts = normalize_node_path(node_path)
    node_id = parts[-1]
    mirror = linear_mirror_for_node(parts)
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "node_path": "/".join(parts),
        "node_id": node_id,
        "is_root": node_id == "L1M1",
        "ingest_rule": "0-ingest only exists on L1M1; child nodes inherit context and start at 1-brainstorm.",
        "hierarchy_contract": HIERARCHY_CONTRACT,
        "linear_mirror": mirror,
        "map_contract": {
            "final_artifact": "MAP.md",
            "purpose": "Forward-facing highest-level necessary steps for this node's current scope.",
            "recursion_rule": f"Numbered MAP steps can become L{int(parse_lm_node(node_id)['level']) + 1}M* child nodes.",
        },
        "stage_folders": [
            {"folder": folder, "file_prefix": prefix, "purpose": purpose}
            for folder, prefix, purpose in node_stages(node_id)
        ],
        "files": ["_node.md", "MAP.md"] + [f"dev/{folder}/README.md" for folder, _prefix, _purpose in node_stages(node_id)],
    }


def build_project_template_payload(name: str = "<project name>", *, slug: str | None = None) -> dict[str, Any]:
    project_slug = slug or slugify(name)
    root_node = build_node_template_payload("L1M1")
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "project_name": name,
        "project_slug": project_slug,
        "root_node": root_node,
        "hierarchy_contract": HIERARCHY_CONTRACT,
        "linear_mirror": {
            "root": linear_mirror_for_node(["L1M1"]),
            "child_default": HIERARCHY_CONTRACT["linear_defaults"]["child_planning_node"],
            "execution_boundary": HIERARCHY_CONTRACT["linear_defaults"]["execution_package"],
            "task_boundary": HIERARCHY_CONTRACT["linear_defaults"]["task"],
        },
        "top_level_files": [".linear-config", "PROJECT.md", "LINEAR.md", "NIKLAS.md", "STATUS.md", "inbox/README.md"],
        "default_projects_root": str(BertEnvironment.default().projects_root),
        "linear_rule": "Project creation will carry Linear anchor fields, but live Linear mutation remains blocked until apply semantics are accepted.",
        "niklas_rule": "Project creation will carry Niklas anchor fields, but graph mutation remains blocked until write-token/apply semantics are accepted.",
    }


PROJECT_ANALYSIS_SKIP_DIRS = {
    ".BERT",
    ".git",
    ".hg",
    ".svn",
    ".cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "DerivedData",
    "dist",
    "node_modules",
    "venv",
}

PROJECT_MARKERS = {
    ".linear-config": "linear_config",
    ".gitignore": "gitignore",
    "AGENTS.md": "agents_instructions",
    "CLAUDE.md": "claude_instructions",
    "README.md": "readme",
    "package.json": "node_package",
    "pnpm-lock.yaml": "pnpm_lock",
    "yarn.lock": "yarn_lock",
    "package-lock.json": "npm_lock",
    "pyproject.toml": "python_project",
    "requirements.txt": "python_requirements",
    "Cargo.toml": "rust_project",
    "go.mod": "go_module",
    "Gemfile": "ruby_project",
    "Podfile": "ios_project",
    "docker-compose.yml": "docker_compose",
    "Dockerfile": "dockerfile",
}


def _safe_resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _project_folder_gate(host_dir: Path, env: BertEnvironment) -> dict[str, Any]:
    resolved = _safe_resolve(host_dir)
    unsafe_paths = {
        _safe_resolve(Path("/")),
        _safe_resolve(env.home),
        _safe_resolve(env.home / "Desktop"),
        _safe_resolve(env.home / "Documents"),
        _safe_resolve(env.home / "Downloads"),
        _safe_resolve(env.home / "Desktop" / "PROJECTS"),
        _safe_resolve(env.builder_root),
        _safe_resolve(env.bert_root),
        _safe_resolve(env.niklas_root),
        _safe_resolve(env.runtime_root),
    }
    if not host_dir.exists():
        return {
            "status": "blocked_missing_folder",
            "path": str(host_dir),
            "safe_to_write": False,
            "reason": "Create or choose a real project folder before BERT can initialize `.BERT`.",
        }
    if not host_dir.is_dir():
        return {
            "status": "blocked_not_directory",
            "path": str(host_dir),
            "safe_to_write": False,
            "reason": "BERT projects must be directories.",
        }
    if resolved in unsafe_paths:
        return {
            "status": "blocked_requires_project_folder",
            "path": str(host_dir),
            "safe_to_write": False,
            "reason": "This is a broad container folder. Pick or create the actual project folder first.",
        }
    return {
        "status": "ok_project_folder",
        "path": str(host_dir),
        "safe_to_write": True,
        "reason": "This looks like a specific project folder BERT can analyze before adoption.",
    }


def _git_state(path: Path) -> dict[str, Any]:
    result = run_command(["git", "status", "--short", "--branch"], path)
    lines = (result.get("stdout") or result.get("stderr") or "").splitlines()
    return {
        "available": result["ok"],
        "branch": lines[0] if lines else "not a git repo or no output",
        "dirty_count": max(0, len(lines) - 1),
        "error": "" if result["ok"] else result.get("stderr", ""),
    }


def _project_inventory(host_dir: Path, *, max_files: int = 500, max_depth: int = 4) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "exists": host_dir.exists(),
        "is_dir": host_dir.is_dir(),
        "sample_limit": max_files,
        "max_depth": max_depth,
        "truncated": False,
        "files_sampled": 0,
        "dirs_sampled": 0,
        "top_level_dirs": [],
        "top_level_files": [],
        "skipped_dirs": [],
        "markers": [],
        "extensions": {},
        "likely_project_kind": "unknown",
    }
    if not host_dir.exists() or not host_dir.is_dir():
        return payload

    extensions: Counter[str] = Counter()
    markers: dict[str, dict[str, str]] = {}
    stack: list[tuple[Path, int]] = [(host_dir, 0)]
    while stack and payload["files_sampled"] < max_files:
        current, depth = stack.pop(0)
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError as exc:
            payload.setdefault("errors", []).append(f"{current}: {exc}")
            continue
        for entry in entries:
            rel = entry.relative_to(host_dir).as_posix()
            if depth == 0:
                if entry.is_dir():
                    payload["top_level_dirs"].append(entry.name)
                elif entry.is_file():
                    payload["top_level_files"].append(entry.name)
            if entry.is_dir():
                if entry.name in PROJECT_ANALYSIS_SKIP_DIRS:
                    payload["skipped_dirs"].append(rel)
                    continue
                if depth < max_depth:
                    payload["dirs_sampled"] += 1
                    stack.append((entry, depth + 1))
                continue
            if not entry.is_file():
                continue
            marker = PROJECT_MARKERS.get(entry.name)
            if marker and marker not in markers:
                markers[marker] = {"kind": marker, "path": rel}
            suffix = entry.suffix.lower() or "[no_ext]"
            extensions[suffix] += 1
            payload["files_sampled"] += 1
            if payload["files_sampled"] >= max_files:
                payload["truncated"] = True
                break

    payload["markers"] = list(markers.values())
    payload["extensions"] = dict(extensions.most_common(20))
    marker_kinds = {item["kind"] for item in payload["markers"]}
    if {"node_package", "pnpm_lock", "yarn_lock", "npm_lock"} & marker_kinds:
        payload["likely_project_kind"] = "node_or_web_app"
    elif {"python_project", "python_requirements"} & marker_kinds:
        payload["likely_project_kind"] = "python_project"
    elif "rust_project" in marker_kinds:
        payload["likely_project_kind"] = "rust_project"
    elif "go_module" in marker_kinds:
        payload["likely_project_kind"] = "go_project"
    elif "readme" in marker_kinds:
        payload["likely_project_kind"] = "documented_project"
    return payload


def _bert_fit_assessment(*, initialized: bool, folder_gate: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    if initialized:
        return {
            "status": "already_bert_project",
            "decision": "open_existing",
            "reason": "This folder already has a `.BERT` workspace.",
        }
    if not folder_gate["safe_to_write"]:
        return {
            "status": "blocked_until_project_folder_selected",
            "decision": "choose_or_create_folder",
            "reason": folder_gate["reason"],
        }
    if inventory["files_sampled"] == 0 and not inventory["top_level_dirs"]:
        return {
            "status": "blank_candidate",
            "decision": "ask_user_before_init",
            "reason": "This is a blank project folder. It can become a BERT project after confirmation.",
        }
    return {
        "status": "candidate_requires_review",
        "decision": "analyze_then_ask_user",
        "reason": "This folder has existing project material. Review markers, Linear, and Niklas correlation before initializing `.BERT`.",
    }


def _parse_status_file(workspace_dir: Path) -> dict[str, Any]:
    status_path = workspace_dir / "STATUS.md"
    payload = {
        "path": str(status_path),
        "exists": status_path.exists(),
        "source": "STATUS.md",
        "current_node": None,
        "current_stage": None,
    }
    if not status_path.exists():
        return payload
    text = status_path.read_text(encoding="utf-8")
    node_match = re.search(r"Current node:\s*`?([^`\n]+)`?", text)
    stage_match = re.search(r"Current stage:\s*`?([^`\n]+)`?", text)
    if node_match:
        payload["current_node"] = node_match.group(1).strip()
    if stage_match:
        payload["current_stage"] = stage_match.group(1).strip()
    return payload


def _read_process_state(workspace_dir: Path) -> dict[str, Any]:
    """Resume position record: prefer machine-canonical state.json, fall back to STATUS.md."""
    state_path = workspace_dir / "state.json"
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            return {
                "path": str(state_path),
                "exists": True,
                "source": "state.json",
                "schema": data.get("schema"),
                "current_node": data.get("current_node"),
                "current_stage": data.get("current_stage"),
                "initialized_at": data.get("initialized_at"),
                "updated_at": data.get("updated_at"),
                "stages": data.get("stages") if isinstance(data.get("stages"), dict) else None,
            }
    return _parse_status_file(workspace_dir)


def _stage_progress_for_node(
    workspace_dir: Path,
    node_path: str,
    *,
    acceptance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Stage rows for one node.

    With v2 acceptance records, completion means *accepted* — a drafted file
    that nobody accepted reports `drafting` and stays the current stage.
    Without records (v1 state or STATUS.md fallback) file existence still
    completes, so legacy workspaces keep resuming exactly as before.
    """
    parts = normalize_node_path(node_path)
    node_id = parts[-1]
    node_dir = workspace_dir.joinpath(*parts)
    progress: list[dict[str, Any]] = []
    for index, (folder, prefix, purpose) in enumerate(node_stages(node_id)):
        stage_dir = node_dir / "dev" / folder
        outputs = sorted(stage_dir.glob(f"{prefix}_{node_id}_V*.md")) if stage_dir.exists() else []
        record = acceptance.get(folder) if acceptance is not None else None
        accepted = bool(record and record.get("status") == "accepted")
        if acceptance is None:
            status = "complete" if outputs else "pending"
        elif accepted:
            status = "complete"
        elif outputs:
            status = "drafting"
        else:
            status = "pending"
        progress.append(
            {
                "index": index,
                "folder": folder,
                "file_prefix": prefix,
                "purpose": purpose,
                "path": str(stage_dir),
                "exists": stage_dir.exists(),
                "expected_glob": str(stage_dir / f"{prefix}_{node_id}_V*.md"),
                "output_files": [str(path) for path in outputs],
                "status": status,
                "accepted": accepted,
                "accepted_at": record.get("accepted_at") if record else None,
            }
        )
    return progress


def _bert_process_position(
    *,
    host_dir: Path,
    workspace_dir: Path,
    initialized: bool,
    nodes: list[dict[str, Any]],
    folder_gate: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    if not initialized:
        if not folder_gate["safe_to_write"]:
            start_reason = "folder_gate_blocked"
        elif inventory["files_sampled"] == 0 and not inventory["top_level_dirs"]:
            start_reason = "blank_folder"
        else:
            start_reason = "existing_material_without_bert"
        return {
            "state": "not_started",
            "initialized": False,
            "host_project_dir": str(host_dir),
            "bert_workspace_dir": str(workspace_dir),
            "start_reason": start_reason,
            "current_node": "L1M1",
            "current_stage": "0-ingest",
            "resume_action": "start_at_beginning",
            "next_command": f"bert adopt {shlex.quote(str(host_dir))} --name {shlex.quote(host_dir.name or 'untitled-bert-project')} --apply",
            "next_after_init": f"bert project open {host_dir}",
            "stage_progress": [],
            "rule": "No `.BERT` workspace exists yet, so BERT starts at the beginning after explicit adoption.",
        }

    status = _read_process_state(workspace_dir)
    node_paths = [node["node_path"] for node in nodes]
    current_node = status.get("current_node") if status.get("current_node") in node_paths else None
    if current_node is None:
        current_node = "L1M1" if "L1M1" in node_paths else (node_paths[0] if node_paths else "missing")
    if current_node == "missing":
        return {
            "state": "initialized_missing_nodes",
            "initialized": True,
            "host_project_dir": str(host_dir),
            "bert_workspace_dir": str(workspace_dir),
            "status_file": status,
            "current_node": "missing",
            "current_stage": "missing",
            "resume_action": "repair_workspace",
            "stage_progress": [],
            "rule": "A `.BERT` folder exists, but no `_node.md` records were found.",
        }

    acceptance = None
    if status.get("schema") == BERT_STATE_SCHEMA and isinstance(status.get("stages"), dict):
        acceptance = status["stages"].get(current_node, {})
    progress = _stage_progress_for_node(workspace_dir, current_node, acceptance=acceptance)
    first_pending = next((stage for stage in progress if stage["status"] != "complete"), None)
    status_stage = status.get("current_stage")
    status_stage_record = next((stage for stage in progress if stage["folder"] == status_stage), None)
    if status_stage_record and status_stage_record["status"] != "complete":
        current_stage = status_stage
    else:
        current_stage = first_pending["folder"] if first_pending else "complete"
    return {
        "state": "in_progress" if first_pending else "node_complete",
        "initialized": True,
        "host_project_dir": str(host_dir),
        "bert_workspace_dir": str(workspace_dir),
        "status_file": status,
        "current_node": current_node,
        "current_stage": current_stage,
        "resume_action": "run_current_stage" if first_pending else "read_map_and_spawn_or_choose_next_node",
        "next_command": f"bert node stages {current_node} --project {host_dir}",
        "stage_progress": progress,
        "rule": "Existing `.BERT` workspaces resume from local status and first incomplete stage output.",
    }


def build_project_analyze_payload(
    project: str,
    *,
    projects_root: str | Path | None = None,
    task: str | None = None,
    linear_anchor: str | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    host_project_dir = resolve_project_dir(env, project, projects_root=projects_root)
    if host_project_dir.name == ".BERT":
        workspace_dir = host_project_dir
        host_dir = host_project_dir.parent
    else:
        host_dir = host_project_dir
        workspace_dir = host_project_dir / ".BERT"
    initialized = workspace_dir.exists()
    local_config = read_linear_config((workspace_dir if initialized else host_dir) / ".linear-config")
    nodes = _discover_lm_nodes(workspace_dir) if initialized else []
    lookup_name = (
        local_config.get("values", {}).get("bert_project")
        or (host_dir.name if host_dir.name else project)
    )
    folder_gate = _project_folder_gate(host_dir, env)
    if folder_gate["safe_to_write"] or initialized:
        inventory = _project_inventory(host_dir)
    else:
        inventory = {
            "exists": host_dir.exists(),
            "is_dir": host_dir.is_dir(),
            "sample_limit": 0,
            "max_depth": 0,
            "truncated": False,
            "files_sampled": 0,
            "dirs_sampled": 0,
            "top_level_dirs": [],
            "top_level_files": [],
            "skipped_dirs": [],
            "markers": [],
            "extensions": {},
            "likely_project_kind": "not_sampled",
            "skipped_reason": folder_gate["reason"],
        }
    if folder_gate["safe_to_write"] or initialized:
        linear_lookup = _linear_anchor_lookup(lookup_name)
    else:
        linear_lookup = {
            "generated_at": utcnow(),
            "mode": READ_ONLY_MODE,
            "query": lookup_name,
            "first_step": "pick or create the actual project folder before Linear lookup",
            "lookup_order": ["initiative", "project"],
            "linear_api": "skipped_folder_gate",
            "matches": {"initiatives": [], "projects": []},
            "next": ["Choose a specific project folder, then rerun BERT analysis."],
        }
    linear_snapshot = build_linear_snapshot(env)
    if folder_gate["safe_to_write"] or initialized:
        niklas_lookup = _niklas_anchor_lookup(
            env=env,
            host_project_dir=host_dir,
            workspace_dir=workspace_dir,
            local_config=local_config,
            lookup_name=lookup_name,
            task=task,
            nodes=nodes,
        )
    else:
        niklas_lookup = {
            "generated_at": utcnow(),
            "mode": READ_ONLY_MODE,
            "write_enabled": False,
            "method": "niklas-local-sqlite-keyword-v1",
            "db_path": str(env.db_path),
            "db_exists": env.db_path.exists(),
            "schema_present": False,
            "query": lookup_name,
            "local_anchor": local_config.get("values", {}).get("niklas_anchor") or "pending",
            "matches": [],
            "correlation_status": "skipped_folder_gate",
            "write_status": "blocked_until_write_token",
            "rule": "Niklas correlation runs after a specific project folder is selected.",
            "next": ["Choose a specific project folder, then rerun BERT analysis."],
        }
    fit = _bert_fit_assessment(initialized=initialized, folder_gate=folder_gate, inventory=inventory)
    if folder_gate["safe_to_write"] or initialized:
        next_steps = [
            "Pick or create the actual project folder first; do not initialize BERT at Desktop/Home/container level.",
            "Review project markers, Linear lookup, and Niklas lookup before adoption.",
            f"If this fits, run `bert adopt {shlex.quote(str(host_dir))} --name {shlex.quote(str(lookup_name))} --apply`.",
            "After initialization, run `bert project open` or `bert node start` to continue the L1M1 workflow.",
        ]
    else:
        next_steps = [
            "Pick or create the actual project folder first.",
            "Do not initialize BERT at Desktop/Home/container level.",
            "After choosing a specific folder, rerun `bert project analyze <folder>`.",
        ]
    bert_process = _bert_process_position(
        host_dir=host_dir,
        workspace_dir=workspace_dir,
        initialized=initialized,
        nodes=nodes,
        folder_gate=folder_gate,
        inventory=inventory,
    )
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "operation": "bert_project_analyze",
        "project": project,
        "host_project_dir": str(host_dir),
        "bert_workspace_dir": str(workspace_dir),
        "initialized": initialized,
        "hidden_workspace": True,
        "task": task,
        "linear_anchor": linear_anchor or local_config.get("values", {}).get("linear_anchor") or "pending",
        "folder_gate": folder_gate,
        "inventory": inventory,
        "git": _git_state(host_dir),
        "local_linear_config": local_config,
        "linear_lookup": linear_lookup,
        "niklas_lookup": niklas_lookup,
        "bert_process": bert_process,
        "bert_fit_assessment": fit,
        "position": {
            "local_root_node": "L1M1" if any(node["node_id"] == "L1M1" for node in nodes) else ("missing" if initialized else "not_initialized"),
            "current_known_node": nodes[-1]["node_path"] if nodes else ("missing" if initialized else "not_initialized"),
            "linear_live": linear_snapshot["linear_api"] == "live",
            "linear_anchor_lookup": linear_lookup["linear_api"],
            "linear_tree_walk": "available" if linear_snapshot["linear_api"] == "live" else linear_snapshot["linear_api"],
            "niklas_correlation": niklas_lookup["correlation_status"],
            "niklas_anchor": niklas_lookup["local_anchor"],
            "hierarchy_source_of_truth": HIERARCHY_CONTRACT["source_of_truth"],
            "linear_rule": "Before creating hierarchy, read UP/ACROSS/DOWN in Linear and confirm altitude.",
            "niklas_rule": "Niklas Project/node link should mirror the selected local L/M node.",
        },
        "next": next_steps,
    }


def _activation_action(source: dict[str, Any]) -> dict[str, Any]:
    process = source.get("bert_process") or {}
    folder_gate = source.get("folder_gate") or {}
    selected = process.get("host_project_dir") or source.get("host_project_dir") or source.get("project") or "."
    selected_arg = shlex.quote(str(selected))
    state = process.get("state")
    stage = process.get("current_stage") or "0-ingest"
    node = process.get("current_node") or "L1M1"
    if folder_gate and not folder_gate.get("safe_to_write", True):
        return {
            "label": "Choose project folder",
            "intent": "select_project_folder",
            "command": "bert on <project-folder>",
            "write_required": False,
            "reason": folder_gate.get("reason"),
        }
    if state == "not_started":
        name = Path(str(selected)).name or "untitled-bert-project"
        return {
            "label": "Start BERT here",
            "intent": "initialize_local_bert_workspace",
            "command": f"bert adopt {selected_arg} --name {shlex.quote(name)} --apply",
            "write_required": True,
            "reason": "Create the local `.BERT` workspace, then begin at L1M1 / 0-ingest.",
        }
    if state == "initialized_missing_nodes":
        return {
            "label": "Inspect BERT workspace",
            "intent": "repair_or_reinitialize_workspace",
            "command": f"bert project open {selected_arg} --json",
            "write_required": False,
            "reason": "A `.BERT` folder exists but no node records were found.",
        }
    if state == "node_complete":
        return {
            "label": "Show process map",
            "intent": "choose_next_node_from_map",
            "command": f"bert node map {shlex.quote(str(node))} --project {selected_arg}",
            "write_required": False,
            "reason": "The current node appears complete; choose or spawn the next node from MAP.md.",
        }
    return {
        "label": f"Continue {stage}",
        "intent": "continue_current_stage",
        "command": f"bert node stages {shlex.quote(str(node))} --project {selected_arg}",
        "write_required": False,
        "reason": "Resume from the current BERT node and first incomplete stage.",
    }


def _activation_copy(source: dict[str, Any]) -> dict[str, str]:
    process = source.get("bert_process") or {}
    folder_gate = source.get("folder_gate") or {}
    inventory = source.get("inventory") or {}
    state = process.get("state")
    if folder_gate and not folder_gate.get("safe_to_write", True):
        return {
            "headline": "BERT needs a project folder.",
            "body": "That is a container, not a project. Choose an existing project folder or create a new one.",
        }
    if state == "not_started":
        if process.get("start_reason") == "blank_folder":
            body = "This folder is empty. BERT can start at the beginning and create the local `.BERT` workspace."
        elif process.get("start_reason") == "existing_material_without_bert":
            body = "This folder already has project material. BERT can adopt it and start from the beginning. Existing files will not be changed."
        else:
            body = "BERT is not initialized here yet. Start at the beginning after adoption."
        return {"headline": "BERT is not started here yet.", "body": body}
    if state == "initialized_missing_nodes":
        return {
            "headline": "BERT needs workspace repair.",
            "body": "A `.BERT` folder exists, but BERT cannot find any node records.",
        }
    if state == "node_complete":
        return {
            "headline": "BERT node is complete.",
            "body": "Use this node's MAP.md to choose or create the next BERT node.",
        }
    marker_count = len(inventory.get("markers") or [])
    marker_note = f" {marker_count} project markers were detected." if marker_count else ""
    return {
        "headline": "BERT is already active here.",
        "body": f"Resume from the current BERT node and stage.{marker_note}",
    }


def _compact_project_material(source: dict[str, Any]) -> dict[str, Any]:
    inventory = source.get("inventory") or {}
    return {
        "likely_project_kind": inventory.get("likely_project_kind"),
        "files_sampled": inventory.get("files_sampled"),
        "dirs_sampled": inventory.get("dirs_sampled"),
        "markers": (inventory.get("markers") or [])[:8],
        "top_level_files": (inventory.get("top_level_files") or [])[:12],
        "top_level_dirs": (inventory.get("top_level_dirs") or [])[:12],
    }


def build_bert_on_payload(
    project: str = ".",
    *,
    projects_root: str | Path | None = None,
    task: str | None = None,
    linear_anchor: str | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    source = build_project_open_payload(
        project,
        projects_root=projects_root,
        task=task,
        linear_anchor=linear_anchor,
        env=env,
    )
    process = source.get("bert_process") or {}
    selected = process.get("host_project_dir") or source.get("host_project_dir") or source.get("project") or project
    copy = _activation_copy(source)
    action = _activation_action(source)
    linear_lookup = source.get("linear_lookup") or {}
    niklas_lookup = source.get("niklas_lookup") or {}
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "operation": "bert_on",
        "project": project,
        "selected_folder": selected,
        "initialized": bool(source.get("initialized")),
        "headline": copy["headline"],
        "body": copy["body"],
        "bert_process": process,
        "primary_action": action,
        "secondary_actions": [
            {"label": "Choose another folder", "intent": "select_project_folder", "command": "bert on <project-folder>"},
            {"label": "Show details", "intent": "inspect_json", "command": f"bert on {shlex.quote(str(selected))} --json"},
        ],
        "linear_status": {
            "lookup": linear_lookup.get("linear_api"),
            "anchor": source.get("linear_anchor") or "pending",
            "matches": linear_lookup.get("matches"),
        },
        "niklas_status": {
            "correlation": niklas_lookup.get("correlation_status"),
            "anchor": niklas_lookup.get("local_anchor") or "pending",
            "matches_count": len(niklas_lookup.get("matches") or []),
        },
        "project_material": _compact_project_material(source),
        "source_operation": source.get("operation"),
        "details": source,
    }


def build_project_create_payload(
    name: str,
    *,
    slug: str | None = None,
    projects_root: str | Path | None = None,
    linear_anchor: str | None = None,
    niklas_anchor: str | None = None,
    apply: bool = False,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    project_slug = slug or slugify(name)
    project_dir = resolve_project_dir(env, name, slug=project_slug, projects_root=projects_root)
    root_node_dir = project_dir / "L1M1"
    dirs = [project_dir, project_dir / "inbox"] + _node_dirs(root_node_dir, "L1M1")
    files = _project_files(
        project_dir,
        host_dir=project_dir,
        name=name,
        slug=project_slug,
        linear_anchor=linear_anchor,
        niklas_anchor=niklas_anchor,
    ) + _node_files(root_node_dir, ["L1M1"], project_name=name)
    applied = _apply_scaffold(dirs, files) if apply else None
    return {
        "generated_at": utcnow(),
        "mode": "local_apply" if apply else READ_ONLY_MODE,
        "write_enabled": apply,
        "operation": "bert_project_create",
        "project_name": name,
        "project_slug": project_slug,
        "project_dir": str(project_dir),
        "root_node": "L1M1",
        "hierarchy_contract": HIERARCHY_CONTRACT,
        "linear_mirror": {
            "root": linear_mirror_for_node(["L1M1"]),
            "write_status": "blocked_until_apply_contract",
        },
        "ingest_rule": "0-ingest is created only for L1M1.",
        "planned_dirs": [str(path) for path in dirs],
        "planned_files": [item["path"] for item in files],
        "relative_tree": [_rel(path, project_dir) for path in dirs] + [_rel(Path(item["path"]), project_dir) for item in files],
        "applied": applied,
        "external_writes": [
            {"surface": "Linear", "status": "blocked", "reason": APPLY_BLOCKER, "anchor": linear_anchor or "pending"},
            {"surface": "Niklas graph", "status": "blocked", "reason": "MCP_WRITE_TOKEN/apply contract not enabled", "anchor": niklas_anchor or "pending"},
        ],
    }


def build_project_init_payload(
    project_path: str | Path,
    *,
    name: str | None = None,
    linear_anchor: str | None = None,
    niklas_anchor: str | None = None,
    apply: bool = False,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    host_dir = Path(project_path).expanduser()
    project_name = name or host_dir.name or "untitled-bert-project"
    project_slug = slugify(project_name)
    workspace_dir = host_dir / ".BERT"
    folder_gate = _project_folder_gate(host_dir, env)
    already_initialized = (workspace_dir / "L1M1" / "_node.md").exists()
    root_node_dir = workspace_dir / "L1M1"
    dirs = [workspace_dir, workspace_dir / "inbox"] + _node_dirs(root_node_dir, "L1M1")
    files = _project_files(
        workspace_dir,
        host_dir=host_dir,
        name=project_name,
        slug=project_slug,
        linear_anchor=linear_anchor,
        niklas_anchor=niklas_anchor,
    ) + _node_files(root_node_dir, ["L1M1"], project_name=project_name)
    if apply and not folder_gate["safe_to_write"]:
        return {
            "generated_at": utcnow(),
            "mode": READ_ONLY_MODE,
            "write_enabled": False,
            "operation": "bert_project_init",
            "project_name": project_name,
            "project_slug": project_slug,
            "host_project_dir": str(host_dir),
            "bert_workspace_dir": str(workspace_dir),
            "root_node": "L1M1",
            "hidden_workspace": True,
            "already_initialized": already_initialized,
            "folder_gate": folder_gate,
            "hierarchy_contract": HIERARCHY_CONTRACT,
            "linear_mirror": {
                "root": linear_mirror_for_node(["L1M1"]),
                "write_status": "blocked_until_apply_contract",
            },
            "ingest_rule": "0-ingest is created only for .BERT/L1M1.",
            "planned_dirs": [str(path) for path in dirs],
            "planned_files": [item["path"] for item in files],
            "relative_tree": [_rel(path, workspace_dir) for path in dirs] + [_rel(Path(item["path"]), workspace_dir) for item in files],
            "applied": None,
            "failures": [folder_gate["reason"]],
            "next": [
                "Pick or create the actual project folder first.",
                "Run `bert project analyze <folder>` before initializing.",
                "Then rerun `bert project init <folder> --apply` only after the folder gate passes.",
            ],
            "external_writes": [
                {"surface": "Linear", "status": "blocked", "reason": APPLY_BLOCKER, "anchor": linear_anchor or "pending"},
                {"surface": "Niklas graph", "status": "blocked", "reason": "MCP_WRITE_TOKEN/apply contract not enabled", "anchor": niklas_anchor or "pending"},
            ],
        }
    applied = _apply_scaffold(dirs, files) if apply else None
    if already_initialized:
        next_steps = [
            "This folder already has an initialized `.BERT` workspace.",
            f"Resume with `bert on {shlex.quote(str(host_dir))}` — adoption never overwrites existing files.",
        ]
    elif apply:
        next_steps = [
            f"BERT workspace created. Run `bert on {shlex.quote(str(host_dir))}` to begin at L1M1 / 0-ingest.",
        ]
    else:
        next_steps = [
            "Dry-run only. Re-run with `--apply` to create the hidden `.BERT` workspace.",
        ]
    return {
        "generated_at": utcnow(),
        "mode": "local_apply" if apply else READ_ONLY_MODE,
        "write_enabled": apply,
        "operation": "bert_project_init",
        "project_name": project_name,
        "project_slug": project_slug,
        "host_project_dir": str(host_dir),
        "bert_workspace_dir": str(workspace_dir),
        "root_node": "L1M1",
        "hidden_workspace": True,
        "already_initialized": already_initialized,
        "next": next_steps,
        "folder_gate": folder_gate,
        "hierarchy_contract": HIERARCHY_CONTRACT,
        "linear_mirror": {
            "root": linear_mirror_for_node(["L1M1"]),
            "write_status": "blocked_until_apply_contract",
        },
        "ingest_rule": "0-ingest is created only for .BERT/L1M1.",
        "planned_dirs": [str(path) for path in dirs],
        "planned_files": [item["path"] for item in files],
        "relative_tree": [_rel(path, workspace_dir) for path in dirs] + [_rel(Path(item["path"]), workspace_dir) for item in files],
        "applied": applied,
        "external_writes": [
            {"surface": "Linear", "status": "blocked", "reason": APPLY_BLOCKER, "anchor": linear_anchor or "pending"},
            {"surface": "Niklas graph", "status": "blocked", "reason": "MCP_WRITE_TOKEN/apply contract not enabled", "anchor": niklas_anchor or "pending"},
        ],
    }


def _read_optional(path: Path, max_chars: int = 4000) -> dict[str, Any]:
    payload = {"path": str(path), "exists": path.exists(), "text": ""}
    if path.exists() and path.is_file():
        payload["text"] = path.read_text(encoding="utf-8")[:max_chars]
    return payload


def _discover_lm_nodes(project_dir: Path) -> list[dict[str, Any]]:
    if not project_dir.exists():
        return []
    nodes: list[dict[str, Any]] = []
    for path in sorted(project_dir.rglob("_node.md")):
        rel_parts = path.parent.relative_to(project_dir).parts
        try:
            node_path = normalize_node_path("/".join(rel_parts))
        except ValueError:
            continue
        node_id = node_path[-1]
        parsed = parse_lm_node(node_id)
        mirror = linear_mirror_for_node(node_path)
        nodes.append(
            {
                "node_path": "/".join(node_path),
                "node_id": node_id,
                "level": parsed["level"],
                "map": parsed["map"],
                "linear_mirror": mirror,
                "path": str(path.parent),
                "has_ingest": (path.parent / "dev" / "0-ingest").exists(),
                "stage_dirs": [
                    stage[0]
                    for stage in node_stages(node_id)
                    if (path.parent / "dev" / stage[0]).exists()
                ],
            }
        )
    return sorted(nodes, key=lambda node: (node["level"], node["map"], node["node_path"]))


def _direct_children(nodes: list[dict[str, Any]], parent_parts: list[str]) -> list[dict[str, Any]]:
    children = []
    for node in nodes:
        parts = normalize_node_path(node["node_path"])
        if parts[:-1] == parent_parts:
            children.append(node)
    return sorted(children, key=lambda node: (node["level"], node["map"], node["node_path"]))


def _read_map_steps(map_path: Path) -> list[dict[str, Any]]:
    if not map_path.exists() or not map_path.is_file():
        return []
    steps: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in map_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(\d+)\.\s+(.+?)\s*$", raw_line)
        if match:
            current = {
                "index": int(match.group(1)),
                "title": match.group(2).strip(),
                "child_node": None,
                "raw": [raw_line],
            }
            steps.append(current)
            continue
        if current is None:
            continue
        current["raw"].append(raw_line)
        child_match = re.search(r"Child node:\s*`?([A-Za-z0-9]+)`?", raw_line)
        if child_match:
            try:
                current["child_node"] = str(parse_lm_node(child_match.group(1))["id"])
            except ValueError:
                current["child_node"] = child_match.group(1).strip()
    return steps


def _propose_child_node(
    parent_parts: list[str],
    *,
    requested_node: str | None = None,
    step: int | None = None,
    existing_children: list[dict[str, Any]] | None = None,
    map_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parent_level = int(parse_lm_node(parent_parts[-1])["level"])
    child_level = parent_level + 1
    source = "next_available_child"
    if requested_node:
        parsed = parse_lm_node(requested_node)
        if int(parsed["level"]) != child_level:
            raise ValueError(f"{parsed['id']} must be a level {child_level} child of {'/'.join(parent_parts)}")
        canonical = str(parsed["id"])
        source = "requested_node"
    elif step is not None:
        matching_step = next((item for item in (map_steps or []) if item["index"] == step), None)
        if matching_step and matching_step.get("child_node"):
            canonical = str(parse_lm_node(str(matching_step["child_node"]))["id"])
            source = "parent_map_step_child_node"
        else:
            canonical = f"L{child_level}M{step}"
            source = "parent_map_step_index"
    else:
        existing_maps = [
            int(parse_lm_node(child["node_id"])["map"])
            for child in (existing_children or [])
        ]
        canonical = f"L{child_level}M{(max(existing_maps) + 1) if existing_maps else 1}"
    parsed = parse_lm_node(canonical)
    return {
        "node_id": str(parsed["id"]),
        "node_path": "/".join(parent_parts + [str(parsed["id"])]),
        "source": source,
        "linear_mirror": linear_mirror_for_node(parent_parts + [str(parsed["id"])]),
    }


def _infer_altitude(task: str | None) -> dict[str, Any]:
    text = (task or "").lower()
    if not text.strip():
        return {
            "altitude": "unknown",
            "linear_target": "needs current task or Linear anchor",
            "reason": "No task text was supplied.",
        }
    initiative_terms = ["whole app", "system", "strategy", "initiative", "top level", "redesign", "architecture"]
    project_terms = ["build", "ship", "feature", "workflow", "project", "capability", "slice"]
    task_terms = ["fix", "bug", "copy", "button", "test", "implement", "change", "update"]
    if any(term in text for term in initiative_terms):
        return {
            "altitude": "initiative",
            "linear_target": "Linear Initiative or Sub-initiative",
            "reason": "Task language points at a broad strategic or product container.",
        }
    if any(term in text for term in project_terms):
        return {
            "altitude": "project",
            "linear_target": "Linear Project under the selected Initiative",
            "reason": "Task language points at a shippable capability or workflow slice.",
        }
    if any(term in text for term in task_terms):
        return {
            "altitude": "task",
            "linear_target": "Linear Issue under the selected Project",
            "reason": "Task language points at concrete implementation work.",
        }
    return {
        "altitude": "needs_review",
        "linear_target": "tree-walk required",
        "reason": "Task language does not clearly select initiative, project, or issue altitude.",
    }


def _linear_anchor_lookup(query: str, *, live: bool = True) -> dict[str, Any]:
    clean_query = query.strip()
    payload: dict[str, Any] = {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "query": clean_query,
        "first_step": "look for an existing Linear Initiative or Project before creating a BERT link",
        "lookup_order": ["initiative", "project"],
        "linear_api": "blocked_missing_token",
        "matches": {"initiatives": [], "projects": []},
        "next": [
            "If an existing initiative fits, link this BERT project to that initiative.",
            "If an existing project fits, link this BERT project to that project and read its parent initiative.",
            "If nothing fits, create the Linear artifact only after the tree-first fit check.",
        ],
    }
    if not clean_query:
        payload["linear_api"] = "blocked_missing_query"
        return payload
    if not live:
        payload["linear_api"] = "skipped"
        return payload
    if not os.environ.get("LINEAR_ACCESS_TOKEN"):
        return payload
    try:
        client = LinearClient()
        data = client.graphql(
            """
            query BertAnchorLookup($query: String!, $first: Int!) {
              initiatives(first: $first, filter: { name: { contains: $query } }) {
                nodes {
                  id
                  name
                  url
                  status
                  parentInitiatives { nodes { id name url } }
                }
              }
              projects(first: $first, filter: { name: { contains: $query } }) {
                nodes {
                  id
                  name
                  url
                  status { name type }
                  initiatives { nodes { id name url } }
                }
              }
            }
            """,
            {"query": clean_query, "first": 10},
        )
        payload["matches"] = {
            "initiatives": data.get("initiatives", {}).get("nodes", []),
            "projects": data.get("projects", {}).get("nodes", []),
        }
        payload["linear_api"] = "live"
    except Exception as exc:  # noqa: BLE001 - project open should return blocked state, not crash.
        payload["linear_api"] = "blocked_error"
        payload["error"] = str(exc)
    return payload


def _trim_niklas_match(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "title": node.get("title"),
        "project": node.get("project"),
        "path": node.get("path"),
        "absolute_path": node.get("absolute_path"),
        "summary": node.get("summary"),
        "tags": node.get("tags") or [],
        "score": node.get("score"),
    }


def _niklas_anchor_lookup(
    *,
    env: BertEnvironment,
    host_project_dir: Path,
    workspace_dir: Path,
    local_config: dict[str, Any],
    lookup_name: str,
    task: str | None,
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    config_values = local_config.get("values", {})
    local_anchor = config_values.get("niklas_anchor") or "pending"
    node_paths = [str(node.get("node_path") or "") for node in nodes if node.get("node_path")]
    query_parts = [
        lookup_name,
        config_values.get("bert_project_slug"),
        str(host_project_dir),
        str(workspace_dir),
        config_values.get("root_node"),
        local_anchor if local_anchor != "pending" else None,
        task,
        " ".join(node_paths[-3:]),
    ]
    query = " ".join(str(part).strip() for part in query_parts if str(part or "").strip())
    payload: dict[str, Any] = {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "method": "niklas-local-sqlite-keyword-v1",
        "db_path": str(env.db_path),
        "db_exists": env.db_path.exists(),
        "schema_present": False,
        "query": query,
        "local_anchor": local_anchor,
        "matches": [],
        "correlation_status": "blocked_db_missing",
        "write_status": "blocked_until_write_token",
        "rule": "Niklas is the project orientation and context graph; BERT must resolve the local project/node against Niklas before durable planning writes.",
        "next": [
            "If a match fits, treat that Niklas node as the context anchor for the BERT project.",
            "If no match fits, create/link a Niklas Project node only after write-token/apply semantics are enabled.",
        ],
    }
    if not env.db_path.exists():
        return payload
    try:
        store = NiklasStore(env.db_path)
        payload["schema_present"] = store.schema_present()
        if not payload["schema_present"]:
            payload["correlation_status"] = "blocked_schema_missing"
            return payload
        matches = [_trim_niklas_match(node) for node in store.search_nodes(query, limit=8)]
        payload["matches"] = matches
        if local_anchor != "pending":
            payload["correlation_status"] = "local_anchor_configured"
        elif matches:
            payload["correlation_status"] = "candidate_matches"
        else:
            payload["correlation_status"] = "no_match"
        return payload
    except Exception as exc:  # noqa: BLE001 - orientation should report, not crash.
        payload["correlation_status"] = "blocked_error"
        payload["error"] = str(exc)
        return payload


def build_project_open_payload(
    project: str,
    *,
    projects_root: str | Path | None = None,
    task: str | None = None,
    linear_anchor: str | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    host_project_dir = resolve_project_dir(env, project, projects_root=projects_root)
    if host_project_dir.name == ".BERT":
        project_dir = host_project_dir
        host_project_dir = host_project_dir.parent
        workspace_dir = project_dir
    elif (host_project_dir / ".BERT").exists():
        project_dir = host_project_dir / ".BERT"
        workspace_dir = project_dir
    else:
        return build_project_analyze_payload(
            project,
            projects_root=projects_root,
            task=task,
            linear_anchor=linear_anchor,
            env=env,
        )
    local_config = read_linear_config(workspace_dir / ".linear-config")
    nodes = _discover_lm_nodes(workspace_dir)
    lookup_name = (
        local_config.get("values", {}).get("bert_project")
        or (host_project_dir.name if host_project_dir.name else project)
    )
    linear_lookup = _linear_anchor_lookup(lookup_name)
    linear_snapshot = build_linear_snapshot(env)
    linear_live = linear_snapshot["linear_api"] == "live"
    niklas_lookup = _niklas_anchor_lookup(
        env=env,
        host_project_dir=host_project_dir,
        workspace_dir=workspace_dir,
        local_config=local_config,
        lookup_name=lookup_name,
        task=task,
        nodes=nodes,
    )
    folder_gate = _project_folder_gate(host_project_dir, env)
    bert_process = _bert_process_position(
        host_dir=host_project_dir,
        workspace_dir=workspace_dir,
        initialized=True,
        nodes=nodes,
        folder_gate=folder_gate,
        inventory={"files_sampled": 0, "top_level_dirs": []},
    )
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "operation": "bert_project_open",
        "project": project,
        "project_dir": str(project_dir),
        "bert_workspace_dir": str(workspace_dir),
        "exists": workspace_dir.exists(),
        "initialized": True,
        "hidden_workspace": workspace_dir.name == ".BERT",
        "task": task,
        "linear_anchor": linear_anchor or local_config.get("values", {}).get("linear_anchor") or "pending",
        "linear_lookup": linear_lookup,
        "niklas_lookup": niklas_lookup,
        "folder_gate": folder_gate,
        "bert_process": bert_process,
        "hierarchy_contract": HIERARCHY_CONTRACT,
        "linear_mirror": {
            "root": linear_mirror_for_node(["L1M1"]),
            "current": linear_mirror_for_node(normalize_node_path(nodes[-1]["node_path"])) if nodes else None,
            "write_status": "blocked_until_apply_contract",
        },
        "altitude": _infer_altitude(task),
        "local_files": {
            "project": _read_optional(workspace_dir / "PROJECT.md"),
            "linear": _read_optional(workspace_dir / "LINEAR.md"),
            "niklas": _read_optional(workspace_dir / "NIKLAS.md"),
            "status": _read_optional(workspace_dir / "STATUS.md"),
        },
        "local_linear_config": local_config,
        "nodes": nodes,
        "position": {
            "local_root_node": "L1M1" if any(node["node_id"] == "L1M1" for node in nodes) else "missing",
            "current_known_node": nodes[-1]["node_path"] if nodes else "missing",
            "linear_live": linear_live,
            "linear_anchor_lookup": linear_lookup["linear_api"],
            "linear_tree_walk": "available" if linear_live else linear_snapshot["linear_api"],
            "niklas_correlation": niklas_lookup["correlation_status"],
            "niklas_anchor": niklas_lookup["local_anchor"],
            "hierarchy_source_of_truth": HIERARCHY_CONTRACT["source_of_truth"],
            "linear_rule": "Before creating hierarchy, read UP/ACROSS/DOWN in Linear and confirm altitude.",
            "niklas_rule": "Niklas Project/node link should mirror the selected local L/M node.",
        },
        "next": [
            "Resolve the Niklas project/node anchor before treating the BERT project as fully oriented.",
            "If altitude is initiative, create or select a Linear Initiative and link it to the local BERT project.",
            "If altitude is project, create or select a Linear Project under the active Initiative.",
            "If altitude is task, create or select a Linear Issue under the active Project.",
            "Do not apply Linear/Niklas writes until tokens and write contracts are configured.",
        ],
    }


def build_node_create_payload(
    node_id: str,
    *,
    project: str,
    parent_path: str | None = None,
    projects_root: str | Path | None = None,
    apply: bool = False,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    parsed = parse_lm_node(node_id)
    canonical_node = str(parsed["id"])
    if canonical_node == "L1M1":
        raise ValueError("use `bert project create` to create L1M1")
    parent_parts = normalize_node_path(parent_path or ("L1M1" if int(parsed["level"]) == 2 else ""))
    parent_level = int(parse_lm_node(parent_parts[-1])["level"])
    if int(parsed["level"]) != parent_level + 1:
        raise ValueError(
            f"{canonical_node} must be created under a level {int(parsed['level']) - 1} parent; got {'/'.join(parent_parts)}"
        )
    host_project_dir = resolve_project_dir(env, project, projects_root=projects_root)
    project_dir = host_project_dir / ".BERT" if (host_project_dir / ".BERT").exists() else host_project_dir
    node_path = parent_parts + [canonical_node]
    node_dir = project_dir.joinpath(*node_path)
    dirs = _node_dirs(node_dir, canonical_node)
    files = _node_files(node_dir, node_path, project_name=project_dir.name)
    if apply and not project_dir.exists():
        raise FileNotFoundError(f"project directory does not exist: {project_dir}; run `bert project create` first")
    applied = _apply_scaffold(dirs, files) if apply else None
    return {
        "generated_at": utcnow(),
        "mode": "local_apply" if apply else READ_ONLY_MODE,
        "write_enabled": apply,
        "operation": "bert_node_create",
        "project": project,
        "project_dir": str(project_dir),
        "host_project_dir": str(host_project_dir),
        "hidden_workspace": project_dir.name == ".BERT",
        "node_id": canonical_node,
        "node_path": "/".join(node_path),
        "parent_path": "/".join(parent_parts),
        "hierarchy_contract": HIERARCHY_CONTRACT,
        "linear_mirror": linear_mirror_for_node(node_path),
        "ingest_rule": "0-ingest is omitted because only L1M1 performs project-root intake.",
        "planned_dirs": [str(path) for path in dirs],
        "planned_files": [item["path"] for item in files],
        "relative_tree": [_rel(path, project_dir) for path in dirs] + [_rel(Path(item["path"]), project_dir) for item in files],
        "applied": applied,
        "external_writes": [
            {"surface": "Linear", "status": "blocked", "reason": APPLY_BLOCKER},
            {"surface": "Niklas graph", "status": "blocked", "reason": "MCP_WRITE_TOKEN/apply contract not enabled"},
        ],
    }


def build_node_locate_payload(
    project: str,
    *,
    parent_path: str = "L1M1",
    node_id: str | None = None,
    step: int | None = None,
    task: str | None = None,
    projects_root: str | Path | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    workspace = _workspace_state(env, project, projects_root=projects_root)
    workspace_dir: Path = workspace["bert_workspace_dir"]
    parent_parts = normalize_node_path(parent_path)
    parent_dir = workspace_dir.joinpath(*parent_parts)
    nodes = _discover_lm_nodes(workspace_dir)
    existing_children = _direct_children(nodes, parent_parts)
    map_path = parent_dir / "MAP.md"
    map_steps = _read_map_steps(map_path)
    proposed = _propose_child_node(
        parent_parts,
        requested_node=node_id,
        step=step,
        existing_children=existing_children,
        map_steps=map_steps,
    )
    matching_step = None
    if step is not None:
        matching_step = next((item for item in map_steps if item["index"] == step), None)
    elif proposed["source"] == "parent_map_step_child_node":
        matching_step = next((item for item in map_steps if item.get("child_node") == proposed["node_id"]), None)
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "operation": "bert_node_locate",
        "project": project,
        "host_project_dir": str(workspace["host_project_dir"]),
        "bert_workspace_dir": str(workspace_dir),
        "initialized": workspace["initialized"],
        "hidden_workspace": workspace["hidden_workspace"],
        "task": task,
        "hierarchy_contract": HIERARCHY_CONTRACT,
        "parent": {
            "node_path": "/".join(parent_parts),
            "node_id": parent_parts[-1],
            "path": str(parent_dir),
            "exists": parent_dir.exists(),
            "map_path": str(map_path),
            "map_exists": map_path.exists(),
            "linear_mirror": linear_mirror_for_node(parent_parts),
        },
        "map_steps": map_steps,
        "existing_children": existing_children,
        "proposed_node": proposed,
        "source_map_step": matching_step,
        "write_plan": {
            "local_apply_command": (
                f"bert node create {proposed['node_id']} --project {project} --parent {'/'.join(parent_parts)} --apply"
            ),
            "linear_write": "blocked_until_apply_contract",
            "niklas_write": "blocked_until_write_token",
        },
        "next": [
            "If the project is not initialized, run `bert project init <project> --apply` first.",
            "If the parent node is missing, create or choose the correct parent before creating this child.",
            "Dry-run `bert node create` before applying local files.",
        ],
    }


def build_node_stages_payload(
    project: str,
    *,
    node_path: str,
    projects_root: str | Path | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    workspace = _workspace_state(env, project, projects_root=projects_root)
    workspace_dir: Path = workspace["bert_workspace_dir"]
    parts = normalize_node_path(node_path)
    node_id = parts[-1]
    node_dir = workspace_dir.joinpath(*parts)
    stages = []
    for index, (folder, prefix, purpose) in enumerate(node_stages(node_id)):
        stage_dir = node_dir / "dev" / folder
        stages.append(
            {
                "index": index,
                "folder": folder,
                "command": folder.split("-", 1)[1] if "-" in folder else folder,
                "file_prefix": prefix,
                "purpose": purpose,
                "path": str(stage_dir),
                "exists": stage_dir.exists(),
                "expected_file": str(stage_dir / f"{prefix}_{node_id}_V1.md"),
            }
        )
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "operation": "bert_node_stages",
        "project": project,
        "bert_workspace_dir": str(workspace_dir),
        "node_path": "/".join(parts),
        "node_id": node_id,
        "node_exists": node_dir.exists(),
        "linear_mirror": linear_mirror_for_node(parts),
        "stages": stages,
        "next": "Run stages in order; only L1M1 includes 0-ingest.",
    }


def build_node_map_payload(
    project: str,
    *,
    node_path: str,
    projects_root: str | Path | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    workspace = _workspace_state(env, project, projects_root=projects_root)
    workspace_dir: Path = workspace["bert_workspace_dir"]
    parts = normalize_node_path(node_path)
    node_dir = workspace_dir.joinpath(*parts)
    map_path = node_dir / "MAP.md"
    steps = _read_map_steps(map_path)
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "operation": "bert_node_map",
        "project": project,
        "bert_workspace_dir": str(workspace_dir),
        "node_path": "/".join(parts),
        "node_id": parts[-1],
        "map_path": str(map_path),
        "map_exists": map_path.exists(),
        "linear_mirror": linear_mirror_for_node(parts),
        "map_contract": {
            "final_artifact": "MAP.md",
            "purpose": HIERARCHY_CONTRACT["map_rule"],
            "recursion_rule": HIERARCHY_CONTRACT["recursion_rule"],
        },
        "steps": steps,
        "child_candidates": [
            {
                "step": item["index"],
                "title": item["title"],
                "node_id": item.get("child_node") or f"L{int(parse_lm_node(parts[-1])['level']) + 1}M{item['index']}",
            }
            for item in steps
        ],
    }


def build_node_spawn_children_payload(
    project: str,
    *,
    parent_path: str,
    projects_root: str | Path | None = None,
    apply: bool = False,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    map_payload = build_node_map_payload(project, node_path=parent_path, projects_root=projects_root, env=env)
    parent_parts = normalize_node_path(parent_path)
    planned_children = []
    applied_children = []
    for candidate in map_payload["child_candidates"]:
        node_id = str(parse_lm_node(candidate["node_id"])["id"])
        plan = build_node_create_payload(
            node_id,
            project=project,
            parent_path="/".join(parent_parts),
            projects_root=projects_root,
            apply=apply,
            env=env,
        )
        planned_children.append(
            {
                "step": candidate["step"],
                "title": candidate["title"],
                "node_id": node_id,
                "node_path": plan["node_path"],
                "linear_mirror": plan["linear_mirror"],
                "planned_dirs": plan["planned_dirs"],
                "planned_files": plan["planned_files"],
            }
        )
        if apply:
            applied_children.append(plan["applied"])
    return {
        "generated_at": utcnow(),
        "mode": "local_apply" if apply else READ_ONLY_MODE,
        "write_enabled": apply,
        "operation": "bert_node_spawn_children",
        "project": project,
        "parent_path": "/".join(parent_parts),
        "map": map_payload,
        "planned_children": planned_children,
        "applied_children": applied_children if apply else None,
        "external_writes": [
            {"surface": "Linear", "status": "blocked", "reason": APPLY_BLOCKER},
            {"surface": "Niklas graph", "status": "blocked", "reason": "MCP_WRITE_TOKEN/apply contract not enabled"},
        ],
    }


def build_node_start_payload(
    project: str,
    *,
    name: str | None = None,
    parent_path: str = "L1M1",
    node_id: str | None = None,
    step: int | None = None,
    task: str | None = None,
    projects_root: str | Path | None = None,
    init_project: bool = False,
    apply: bool = False,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    initial_workspace = _workspace_state(env, project, projects_root=projects_root)
    workflow_steps: list[dict[str, Any]] = [
        {
            "step": "orient",
            "status": "ok" if initial_workspace["workspace_exists"] else "missing_workspace",
            "path": str(initial_workspace["bert_workspace_dir"]),
        }
    ]
    init_payload = None
    if not initial_workspace["initialized"]:
        if init_project:
            init_payload = build_project_init_payload(
                initial_workspace["host_project_dir"],
                name=name,
                apply=apply,
                env=env,
            )
            workflow_steps.append(
                {
                    "step": "initialize_project",
                    "status": "applied" if apply else "planned",
                    "path": init_payload["bert_workspace_dir"],
                }
            )
        else:
            workflow_steps.append(
                {
                    "step": "initialize_project",
                    "status": "blocked_missing_init_project_flag",
                    "path": str(initial_workspace["host_project_dir"] / ".BERT"),
                }
            )
    workspace = _workspace_state(env, project, projects_root=projects_root)
    can_create_node = workspace["initialized"]
    locate = build_node_locate_payload(
        project,
        parent_path=parent_path,
        node_id=node_id,
        step=step,
        task=task,
        projects_root=projects_root,
        env=env,
    )
    create_payload = None
    stages_payload = None
    if can_create_node:
        create_payload = build_node_create_payload(
            locate["proposed_node"]["node_id"],
            project=project,
            parent_path=parent_path,
            projects_root=projects_root,
            apply=apply,
            env=env,
        )
        stages_payload = build_node_stages_payload(
            project,
            node_path=create_payload["node_path"],
            projects_root=projects_root,
            env=env,
        )
        workflow_steps.append(
            {
                "step": "create_node",
                "status": "applied" if apply else "planned",
                "node_path": create_payload["node_path"],
            }
        )
    else:
        workflow_steps.append(
            {
                "step": "create_node",
                "status": "blocked_until_project_initialized",
                "node_path": locate["proposed_node"]["node_path"],
            }
        )
    workflow_steps.append({"step": "run_stages", "status": "planned", "node_path": locate["proposed_node"]["node_path"]})
    workflow_steps.append({"step": "write_map", "status": "planned", "node_path": locate["proposed_node"]["node_path"]})
    return {
        "generated_at": utcnow(),
        "mode": "local_apply" if apply else READ_ONLY_MODE,
        "write_enabled": apply,
        "operation": "bert_node_start",
        "project": project,
        "task": task,
        "hierarchy_contract": HIERARCHY_CONTRACT,
        "workflow_steps": workflow_steps,
        "init_project": init_payload,
        "location": locate,
        "node_create": create_payload,
        "stages": stages_payload,
        "external_writes": [
            {"surface": "Linear", "status": "blocked", "reason": APPLY_BLOCKER},
            {"surface": "Niklas graph", "status": "blocked", "reason": "MCP_WRITE_TOKEN/apply contract not enabled"},
        ],
    }


def build_linear_snapshot(env: BertEnvironment | None = None, *, live: bool = True) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    config = read_linear_config(env.bert_mvp / ".linear-config")
    snapshot: dict[str, Any] = {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "local_config": config,
        "linear_api": "blocked_missing_token",
        "live": None,
    }
    if not live:
        snapshot["linear_api"] = "skipped"
        return snapshot
    if not os.environ.get("LINEAR_ACCESS_TOKEN"):
        return snapshot
    try:
        client = LinearClient()
        project_query = """
        query BertRuntimeAdapterProject($id: String!) {
          project(id: $id) {
            id
            name
            url
            status { name type }
            targetDate
            priority
          }
        }
        """
        initiative_query = """
        query BertInitiative($id: String!) {
          initiative(id: $id) {
            id
            name
            url
            status
            health
          }
        }
        """
        snapshot["live"] = {
            "project": client.graphql(
                project_query,
                {"id": "aafd05ed-75d7-448b-aaa7-1788330afc55"},
            ).get("project"),
            "initiative": client.graphql(
                initiative_query,
                {"id": "443320e5-cb63-4454-8b71-1050d779d2ba"},
            ).get("initiative"),
        }
        snapshot["linear_api"] = "live"
    except Exception as exc:  # noqa: BLE001 - payload should carry blocked state.
        snapshot["linear_api"] = "blocked_error"
        snapshot["error"] = str(exc)
    return snapshot


def build_mcp_payload(env: BertEnvironment | None = None) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    source = env.mcp_server.read_text(encoding="utf-8") if env.mcp_server.exists() else ""
    source_tools = {tool: (f"def {tool}" in source) for tool in EXPECTED_MCP_TOOLS}
    all_present = all(source_tools.values())
    daemon = _mcp_daemon_state(env)
    daemon_reload_needed = _mcp_daemon_reload_needed(env, daemon, all_present)
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "endpoint": os.environ.get("NIKLAS_MCP_RESOURCE_URL", "http://127.0.0.1:8788/mcp"),
        "server_file": str(env.mcp_server),
        "server_file_exists": env.mcp_server.exists(),
        "expected_tools": EXPECTED_MCP_TOOLS,
        "source_tools_present": source_tools,
        "source_installed": all_present,
        "daemon": daemon,
        "daemon_reload_needed": daemon_reload_needed["needed"],
        "daemon_reload_reason": daemon_reload_needed["reason"],
    }


# ---------------------------------------------------------------------------
# Slice 1: stage loop — per-stage MDE forms, draft, accept, next (ERI-2456)
# ---------------------------------------------------------------------------

CITATION_PLACEHOLDER = "- TBD (cite wiki atoms, source packages, or local packet paths)"

CITATION_GATED_STAGES = {"4-blueprint", "7-map"}
ALTITUDE_LINTED_STAGES = {"1-brainstorm", "7-map"}

LOW_ALTITUDE_NOUNS = [
    "postgres", "sqlite", "mysql", "redis", "docker", "kubernetes",
    "react", "next.js", "python", "javascript", "typescript",
    "npm", "pip", "launchctl", "api key", "endpoint",
    ".py", ".ts", ".js", ".sql",
]

STAGE_FORMS: dict[str, dict[str, Any]] = {
    "0-ingest": {
        "headline": "Project-root intake manifest.",
        "body": """## Intake Manifest

What entered this project, from where, and what it claims to be.

| Item | Source | What it claims to be | Keep / Park |
|---|---|---|---|
| TBD | TBD | TBD | TBD |

## Boundaries

- In scope:
- Out of scope (parked, not lost):
""",
        "questions": [
            "What material already exists for this project that BERT should know about?",
            "Is anything here actually a different project that should be split out?",
        ],
    },
    "1-brainstorm": {
        "headline": "Posit the goal — declarative claim, not a question (iron-law-5).",
        "body": """## Goal Posit

State the goal as a 5-10 line declarative claim Erich reacts to. Posit,
don't ask. High level enforced; specificity parked to child nodes.

TBD.

## Question Routing

| Question | Route (`Answer now` / `Research Scout` / `Expert Plans` / `Future item`) |
|---|---|
| TBD | TBD |

## Parked Specificity

- TBD (low-altitude details deliberately pushed down a level)
""",
        "questions": [
            "Does the goal posit match what you actually want at this altitude?",
            "Which routed questions are mis-routed?",
        ],
    },
    "2-experts": {
        "headline": "Sources first: who has already solved this level's steps.",
        "body": """## Source Table

| Source | Source-maker | Value for this node | Access path | Altitude fit |
|---|---|---|---|---|
| TBD | TBD | TBD | TBD | TBD |

## Missing Expertise

- TBD (perspectives this level still lacks)
""",
        "questions": [
            "Which source would you cut, and which is load-bearing?",
            "Is any expert here actually expert at a *different* altitude than this node?",
        ],
    },
    "3-research": {
        "headline": "Ingest manifest: which sources become citable knowledge.",
        "body": """## Ingest Manifest

| Source | Becomes (source package / atoms) | Target wiki path | Status |
|---|---|---|---|
| TBD | TBD | TBD | pending |

## Constraints And Facts Found

- TBD

## Uncertainty Register

- TBD (what we still do not know, and how much it matters)
""",
        "questions": [
            "Is the ingested set sufficient for the blueprint to cite, or are we about to hallucinate?",
        ],
    },
    "4-blueprint": {
        "headline": "EF synthesis — the proven path, fully cited.",
        "body": """## Route

The expert-floor route for this node's scope, synthesized from stage 2-3
sources. Every claim below must trace to a citation.

1. TBD
   - Why this is the proven path:
   - Done when:

## Tradeoffs Considered

- TBD

## Citations

""" + CITATION_PLACEHOLDER + """
""",
        "questions": [
            "Which step would an expert from stage 2 strike out first?",
        ],
    },
    "5-summit": {
        "headline": "10X provocation against the blueprint's constraints.",
        "body": """## What-If Provocations

- What if the core constraint of the blueprint disappeared? TBD
- What if we had to reach the goal in a tenth of the time? TBD

## Axiom Table

| Axiom (what must be true for 10X) | Testable? | Test |
|---|---|---|
| TBD | TBD | TBD |

## MS Track Candidate

- TBD (the moonshot route this node carries alongside the EF route)

## Wild Card (iron-law-11)

- TBD (one deliberately unreasonable idea, kept on the sheet)
""",
        "questions": [
            "Which axiom, if false, kills the moonshot — and is it cheap to test?",
        ],
    },
    "6-pressure-test": {
        "headline": "Premortem, red team, and the monkey.",
        "body": """## Premortem

It is six months later and this node's plan failed. The most likely cause:

TBD.

## Red Team Findings

- TBD

## The Monkey

- Hardest part first: TBD
- Test criterion: TBD
- Kill gate: TBD (the result that means stop, not push harder)
""",
        "questions": [
            "Is the monkey actually the hardest part, or just the scariest?",
        ],
    },
    "7-map": {
        "headline": "Forward-facing MAP: locked goal, dual-track missions, audit column.",
        "body": """## Locked Goal

TBD (re-confirmed against stage 2 experts — the goal freezes here).

## Missions

1. TBD
   - EF (proven path): TBD
   - MS (10X path): TBD
   - Merge strategy: MS works -> new EF; MS fails -> lessons feed EF
   - BUILD / INTEGRATE (from audit): TBD
   - Kill criteria: TBD
   - Done when: TBD
   - Child node: TBD

## Audit Trail

- TBD (what already exists in Niklas/inventory for each mission)

## Citations

""" + CITATION_PLACEHOLDER + """
""",
        "questions": [
            "Can every mission trace to an expert or source from stages 2-4?",
            "Which mission is secretly two missions?",
        ],
    },
}


def _compose_stage_form(
    node_path_str: str,
    node_id: str,
    folder: str,
    prefix: str,
    purpose: str,
    version: int,
    *,
    seed_text: str | None = None,
) -> str:
    form = STAGE_FORMS.get(folder, {"headline": purpose, "body": "TBD.\n", "questions": []})
    questions = "\n".join(
        f"- Q{i + 1}: {question}\n  Answer:\n" for i, question in enumerate(form["questions"])
    ) or "- Q1: What is unresolved at this stage?\n  Answer:\n"
    seed_block = (
        f"\n## Parent Seed (inherited)\n\n{seed_text.strip()}\n" if seed_text else ""
    )
    return f"""---
kind: bert_stage_artifact
node_path: {node_path_str}
node_id: {node_id}
stage: {folder}
version: {version}
status: draft
created: {utcnow()}
---

# {prefix} {node_id} V{version}

{form['headline']}
{seed_block}
{form['body']}
## Questions

{questions}
## Simple Status

- stage: {folder}
- version: V{version}
- state: drafting
- waiting_on: Erich answers, then `bert accept`
"""


def _carry_forward(prior_text: str, new_version: int) -> str:
    text = re.sub(r"(?m)^version: \d+$", f"version: {new_version}", prior_text, count=1)
    text = re.sub(r"(?m)^status: accepted$", "status: draft", text, count=1)
    text = re.sub(r"(?m)^accepted_at: .*\n", "", text, count=1)
    return text


def _latest_stage_version(node_dir: Path, folder: str, prefix: str, node_id: str) -> tuple[int, Path | None]:
    stage_dir = node_dir / "dev" / folder
    if not stage_dir.exists():
        return 0, None
    best, best_path = 0, None
    for path in stage_dir.glob(f"{prefix}_{node_id}_V*.md"):
        match = re.search(r"_V(\d+)\.md$", path.name)
        if match and int(match.group(1)) > best:
            best, best_path = int(match.group(1)), path
    return best, best_path


def _citation_section_ok(text: str) -> bool:
    match = re.search(r"(?ms)^## Citations\s*$(.*?)(?=^## |\Z)", text)
    if not match:
        return False
    bullets = [line.strip() for line in match.group(1).splitlines() if line.strip().startswith("- ")]
    return any("TBD" not in bullet for bullet in bullets)


def _altitude_warnings(text: str, folder: str) -> list[str]:
    lowered = text.lower()
    found = sorted({noun for noun in LOW_ALTITUDE_NOUNS if noun in lowered})
    if not found:
        return []
    return [
        f"altitude lint ({folder}): low-level terms at a planning stage: "
        + ", ".join(found)
        + " — consider raising the altitude or parking them in a child node (warn-only; you are the gate)."
    ]


def _load_state(workspace_dir: Path) -> dict[str, Any] | None:
    state_path = workspace_dir / "state.json"
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _save_state(workspace_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utcnow()
    (workspace_dir / "state.json").write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )


def _loop_context(
    project: str,
    *,
    node_path: str | None = None,
    projects_root: str | Path | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    workspace = _workspace_state(env, project, projects_root=projects_root)
    workspace_dir = workspace["bert_workspace_dir"]
    state = _load_state(workspace_dir)
    node = node_path or (state or {}).get("current_node") or "L1M1"
    parts = normalize_node_path(node)
    node_id = parts[-1]
    node_key = "/".join(parts)
    node_dir = workspace_dir.joinpath(*parts)
    stages_map = (state or {}).get("stages")
    if not isinstance(stages_map, dict):
        stages_map = None
    acceptance = (stages_map or {}).get(node_key, {}) if stages_map is not None else {}
    stage_list = node_stages(node_id)
    current = next(
        (
            stage
            for stage in stage_list
            if (acceptance.get(stage[0]) or {}).get("status") != "accepted"
        ),
        None,
    )
    return {
        "env": env,
        "workspace": workspace,
        "workspace_dir": workspace_dir,
        "host_dir": workspace["host_project_dir"],
        "state": state,
        "node_key": node_key,
        "node_id": node_id,
        "node_dir": node_dir,
        "acceptance": acceptance,
        "stage_list": stage_list,
        "current": current,
    }


def _record_stage_state(
    ctx: dict[str, Any],
    folder: str,
    record: dict[str, Any],
    *,
    current_stage: str,
) -> None:
    state = ctx["state"] or {}
    stages_map = state.get("stages")
    if not isinstance(stages_map, dict):
        stages_map = {}
        state["stages"] = stages_map
        state.setdefault("schema", BERT_STATE_SCHEMA)
        state["schema"] = BERT_STATE_SCHEMA
    node_records = stages_map.setdefault(ctx["node_key"], {})
    node_records[folder] = record
    state["current_node"] = ctx["node_key"]
    state["current_stage"] = current_stage
    _save_state(ctx["workspace_dir"], state)


def build_stage_draft_payload(
    project: str,
    *,
    node_path: str | None = None,
    projects_root: str | Path | None = None,
    apply: bool = False,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    ctx = _loop_context(project, node_path=node_path, projects_root=projects_root, env=env)
    payload: dict[str, Any] = {
        "operation": "bert_stage_draft",
        "mode": "apply_local_markdown" if apply else READ_ONLY_MODE,
        "write_enabled": bool(apply),
        "project_dir": str(ctx["host_dir"]),
        "node_path": ctx["node_key"],
        "warnings": [],
        "next": [],
    }
    if not ctx["workspace"]["initialized"]:
        payload.update(
            {
                "drafted": False,
                "reason": "not_initialized",
                "next": [
                    f"bert adopt {shlex.quote(str(ctx['host_dir']))} --name "
                    f"{shlex.quote(ctx['host_dir'].name or 'untitled-bert-project')} --apply"
                ],
            }
        )
        return payload
    if ctx["current"] is None:
        payload.update(
            {
                "drafted": False,
                "reason": "node_complete",
                "next": [
                    f"bert node spawn-children --project {shlex.quote(str(ctx['host_dir']))} "
                    f"--parent {ctx['node_key']} --apply"
                ],
            }
        )
        return payload

    folder, prefix, purpose = ctx["current"]
    latest_n, latest_path = _latest_stage_version(ctx["node_dir"], folder, prefix, ctx["node_id"])
    version = latest_n + 1
    target = ctx["node_dir"] / "dev" / folder / f"{prefix}_{ctx['node_id']}_V{version}.md"
    seed_path = ctx["node_dir"] / "_seed.md"
    seed_text = (
        seed_path.read_text(encoding="utf-8")
        if folder == "1-brainstorm" and version == 1 and seed_path.exists()
        else None
    )
    if latest_path is not None:
        content = _carry_forward(latest_path.read_text(encoding="utf-8"), version)
        carried_forward = True
    else:
        content = _compose_stage_form(
            ctx["node_key"], ctx["node_id"], folder, prefix, purpose, version, seed_text=seed_text
        )
        carried_forward = False

    payload.update(
        {
            "stage": {"folder": folder, "file_prefix": prefix, "purpose": purpose},
            "artifact": {
                "path": str(target),
                "version": version,
                "carried_forward": carried_forward,
                "seeded": bool(seed_text),
            },
            "planned_files": [str(target)],
            "drafted": False,
        }
    )
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            payload["reason"] = "target_exists"
            payload["next"] = ["bert next"]
            return payload
        target.write_text(content, encoding="utf-8")
        _record_stage_state(
            ctx,
            folder,
            {
                "latest_version": version,
                "status": "drafting",
                "artifact": _rel(target, ctx["workspace_dir"]),
            },
            current_stage=folder,
        )
        payload["drafted"] = True
        payload["next"] = [
            f"Answer the blank `Answer:` lines in {target}",
            f"bert accept --project {shlex.quote(str(ctx['host_dir']))} --apply",
        ]
    else:
        payload["next"] = ["re-run with --apply to write the draft (never overwrites)"]
    return payload


def build_accept_payload(
    project: str,
    *,
    node_path: str | None = None,
    stage: str | None = None,
    projects_root: str | Path | None = None,
    apply: bool = False,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    ctx = _loop_context(project, node_path=node_path, projects_root=projects_root, env=env)
    payload: dict[str, Any] = {
        "operation": "bert_accept",
        "mode": "apply_local_markdown" if apply else READ_ONLY_MODE,
        "write_enabled": bool(apply),
        "project_dir": str(ctx["host_dir"]),
        "node_path": ctx["node_key"],
        "accepted": False,
        "would_accept": False,
        "reason": None,
        "warnings": [],
        "next": [],
    }
    if not ctx["workspace"]["initialized"]:
        payload["reason"] = "not_initialized"
        return payload

    folders = [item[0] for item in ctx["stage_list"]]
    derived = ctx["current"][0] if ctx["current"] is not None else None
    target_folder = stage or derived
    if target_folder is None:
        payload["reason"] = "node_complete"
        payload["next"] = [
            f"bert node spawn-children --project {shlex.quote(str(ctx['host_dir']))} "
            f"--parent {ctx['node_key']} --apply"
        ]
        return payload
    if target_folder not in folders:
        payload["reason"] = "unknown_stage"
        return payload
    record = ctx["acceptance"].get(target_folder) or {}
    if record.get("status") == "accepted":
        payload["reason"] = "already_accepted"
        payload["stage"] = {"folder": target_folder}
        return payload
    if target_folder != derived:
        payload["reason"] = "out_of_sequence"
        payload["stage"] = {"folder": target_folder}
        payload["next"] = [f"accept stages in order — current stage is `{derived}`"]
        return payload

    folder, prefix, purpose = ctx["current"]
    latest_n, latest_path = _latest_stage_version(ctx["node_dir"], folder, prefix, ctx["node_id"])
    if latest_path is None:
        payload["reason"] = "no_draft_to_accept"
        payload["stage"] = {"folder": folder, "file_prefix": prefix, "purpose": purpose}
        payload["next"] = [
            f"bert stage draft --project {shlex.quote(str(ctx['host_dir']))} --apply"
        ]
        return payload

    text = latest_path.read_text(encoding="utf-8")
    payload["stage"] = {"folder": folder, "file_prefix": prefix, "purpose": purpose}
    payload["artifact"] = {"path": str(latest_path), "version": latest_n}
    if folder in ALTITUDE_LINTED_STAGES:
        payload["warnings"].extend(_altitude_warnings(text, folder))
    if folder in CITATION_GATED_STAGES and not _citation_section_ok(text):
        payload["reason"] = "citation_gate_failed"
        payload["next"] = [
            "add at least one resolvable citation (wiki atom, source package, or local "
            "packet path) under `## Citations` — file-path citations are valid in degraded mode"
        ]
        return payload

    payload["would_accept"] = True
    if not apply:
        payload["next"] = ["re-run with --apply to accept and advance"]
        return payload

    accepted_at = utcnow()
    stamped = re.sub(r"(?m)^status: draft$", f"status: accepted\naccepted_at: {accepted_at}", text, count=1)
    if stamped == text and "status: accepted" not in text:
        payload["reason"] = "missing_status_field"
        payload["would_accept"] = False
        return payload
    latest_path.write_text(stamped, encoding="utf-8")

    remaining = [
        item[0]
        for item in ctx["stage_list"]
        if item[0] != folder
        and (ctx["acceptance"].get(item[0]) or {}).get("status") != "accepted"
    ]
    next_stage = remaining[0] if remaining else "complete"
    _record_stage_state(
        ctx,
        folder,
        {
            "latest_version": latest_n,
            "status": "accepted",
            "accepted_at": accepted_at,
            "artifact": _rel(latest_path, ctx["workspace_dir"]),
        },
        current_stage=next_stage,
    )
    payload["accepted"] = True
    payload["accepted_at"] = accepted_at
    if folder == "7-map":
        payload["next"] = [
            f"bert node spawn-children --project {shlex.quote(str(ctx['host_dir']))} "
            f"--parent {ctx['node_key']} --apply"
        ]
    elif next_stage == "complete":
        payload["next"] = ["node complete — read MAP.md and spawn or choose the next node"]
    else:
        payload["next"] = [
            f"bert stage draft --project {shlex.quote(str(ctx['host_dir']))} --apply  # {next_stage}"
        ]
    return payload


def build_next_payload(
    project: str,
    *,
    projects_root: str | Path | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    ctx = _loop_context(project, projects_root=projects_root, env=env)
    payload: dict[str, Any] = {
        "operation": "bert_next",
        "project_dir": str(ctx["host_dir"]),
        "node": ctx["node_key"],
    }
    quoted = shlex.quote(str(ctx["host_dir"]))
    if not ctx["workspace"]["initialized"]:
        payload.update(
            {
                "waiting_on": "adoption",
                "next_command": (
                    f"bert adopt {quoted} --name "
                    f"{shlex.quote(ctx['host_dir'].name or 'untitled-bert-project')} --apply"
                ),
                "status_line": f"{ctx['host_dir']} — no .BERT workspace yet",
            }
        )
        return payload
    if ctx["current"] is None:
        payload.update(
            {
                "stage": {"folder": "complete"},
                "waiting_on": "spawn_or_choose_next_node",
                "next_command": (
                    f"bert node spawn-children --project {quoted} --parent {ctx['node_key']} --apply"
                ),
                "status_line": f"{ctx['node_key']} — all stages accepted",
            }
        )
        return payload

    folder, prefix, purpose = ctx["current"]
    latest_n, latest_path = _latest_stage_version(ctx["node_dir"], folder, prefix, ctx["node_id"])
    payload["stage"] = {"folder": folder, "file_prefix": prefix, "purpose": purpose}
    payload["latest_version"] = latest_n
    if latest_path is None:
        payload.update(
            {
                "waiting_on": "agent_draft",
                "next_command": f"bert stage draft --project {quoted} --apply",
            }
        )
    else:
        payload["artifact"] = str(latest_path)
        text = latest_path.read_text(encoding="utf-8")
        unanswered = len(re.findall(r"(?m)^\s*Answer:\s*$", text))
        if unanswered:
            payload.update(
                {
                    "waiting_on": "erich_answers",
                    "unanswered_questions": unanswered,
                    "next_command": f"bert accept --project {quoted} --apply",
                    "before": f"answer the {unanswered} blank `Answer:` line(s) in {latest_path}",
                }
            )
        else:
            payload.update(
                {
                    "waiting_on": "erich_accept",
                    "next_command": f"bert accept --project {quoted} --apply",
                }
            )
    payload["status_line"] = (
        f"{ctx['node_key']} / {folder} / V{latest_n} — waiting on {payload['waiting_on']}"
    )
    return payload


def _mcp_daemon_state(env: BertEnvironment) -> dict[str, Any]:
    label = f"gui/{os.getuid()}/com.niklas.mcp-daemon"
    source_mtime = _mcp_source_mtime(env)
    state: dict[str, Any] = {
        "label": label,
        "probe": "launchctl",
        "running": False,
        "pid": None,
        "process_started_at": None,
        "server_mtime": (
            datetime.fromtimestamp(env.mcp_server.stat().st_mtime).isoformat()
            if env.mcp_server.exists()
            else None
        ),
        "source_mtime": source_mtime.isoformat() if source_mtime else None,
    }
    launchctl = run_command(["launchctl", "print", label], env.home)
    state["launchctl_ok"] = launchctl["ok"]
    if not launchctl["ok"]:
        state["error"] = launchctl["stderr"] or launchctl["stdout"] or "launchctl probe failed"
        return state
    for raw_line in launchctl["stdout"].splitlines():
        line = raw_line.strip()
        if line.startswith("state =") and "state" not in state:
            state["state"] = line.split("=", 1)[1].strip()
            state["running"] = state["state"] == "running"
        elif line.startswith("pid ="):
            try:
                state["pid"] = int(line.split("=", 1)[1].strip())
            except ValueError:
                state["pid"] = None
        elif line.startswith("runs ="):
            try:
                state["runs"] = int(line.split("=", 1)[1].strip())
            except ValueError:
                state["runs"] = None
    if not state["pid"]:
        return state
    ps = run_command(["ps", "-o", "lstart=", "-p", str(state["pid"])], env.home)
    state["ps_ok"] = ps["ok"]
    if not ps["ok"] or not ps["stdout"]:
        state["ps_error"] = ps["stderr"] or ps["stdout"] or "ps probe failed"
        return state
    started_raw = ps["stdout"].strip()
    state["process_started_raw"] = started_raw
    try:
        state["process_started_at"] = datetime.strptime(
            started_raw,
            "%a %b %d %H:%M:%S %Y",
        ).isoformat()
    except ValueError as exc:
        state["ps_error"] = str(exc)
    return state


def _mcp_daemon_reload_needed(
    env: BertEnvironment,
    daemon: dict[str, Any],
    source_installed: bool,
) -> dict[str, Any]:
    if not source_installed:
        return {
            "needed": False,
            "reason": "BERT MCP tool definitions are not all present in source yet.",
        }
    if not daemon.get("running"):
        return {
            "needed": True,
            "reason": "BERT MCP tools are installed in source, but the Niklas MCP daemon is not running.",
        }
    source_mtime = _mcp_source_mtime(env)
    if not source_mtime:
        return {
            "needed": True,
            "reason": "BERT MCP tools are expected, but the MCP source files are missing.",
        }
    started_at = daemon.get("process_started_at")
    if not started_at:
        return {
            "needed": None,
            "reason": "BERT MCP tools are installed in source, but the live daemon start time could not be verified.",
        }
    process_started = datetime.fromisoformat(started_at)
    if process_started + timedelta(seconds=1) >= source_mtime:
        return {
            "needed": False,
            "reason": "The running Niklas MCP daemon started after the current MCP server source was written.",
        }
    return {
        "needed": True,
        "reason": (
            "BERT MCP tools are installed in source; restart/reload the running Niklas MCP daemon "
            "before clients can discover newly added tools."
        ),
    }


def _mcp_source_mtime(env: BertEnvironment) -> datetime | None:
    files = [env.mcp_server, Path(__file__)]
    mtimes = [path.stat().st_mtime for path in files if path.exists()]
    if not mtimes:
        return None
    return datetime.fromtimestamp(max(mtimes))


def _builder_cli_status(env: BertEnvironment) -> dict[str, Any] | None:
    if not env.legacy_builder_cli.exists():
        return None
    result = run_command([str(env.legacy_builder_cli), "status", "--json"], env.builder_root)
    if not result["ok"] or not result["stdout"]:
        return {"error": result["stderr"] or result["stdout"] or "unknown legacy CLI error"}
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        return {"error": f"legacy CLI emitted invalid JSON: {exc}"}


def _niklas_status(env: BertEnvironment) -> dict[str, Any]:
    try:
        return NiklasStore(env.db_path).status()
    except Exception as exc:  # noqa: BLE001 - status payload should not crash callers.
        return {"error": str(exc), "db_path": str(env.db_path)}


def build_first_read_payload(env: BertEnvironment | None = None) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "first_read": [{"path": str(path), "exists": path.exists()} for path in env.first_read],
    }


def build_readiness_payload(env: BertEnvironment | None = None) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    roots = {
        "canonical_command": path_state(env.canonical_command),
        "niklas_root": path_state(env.niklas_root),
        "runtime_root": path_state(env.runtime_root),
        "niklas_cli": path_state(env.niklas_cli),
        "builder_root": path_state(env.builder_root),
        "bert_root": path_state(env.bert_root),
        "bert_mvp": path_state(env.bert_mvp),
        "skill_pack": path_state(env.skill_pack),
        "linear_buildout": path_state(env.linear_buildout),
        "legacy_builder_cli": path_state(env.legacy_builder_cli),
        "mcp_server": path_state(env.mcp_server),
    }
    git = {
        "niklas_runtime": git_branch(env.runtime_root),
        "builder_root": git_branch(env.builder_root),
        "bert_mvp": git_branch(env.bert_mvp),
        "skill_pack": git_branch(env.skill_pack),
        "linear_buildout": git_branch(env.linear_buildout),
    }
    warnings: list[str] = []
    failures: list[str] = []
    for name, state in roots.items():
        if not state["exists"]:
            failures.append(f"missing root.{name}: {state['path']}")
    if "No commits yet" in git["builder_root"]:
        warnings.append("NIKLAS-BUILDER root git repo has no commits yet; root-level CLI docs are not durable.")
    if "No commits yet" in git["linear_buildout"]:
        warnings.append("BERT-LINEAR-BUILDOUT main repo has no commits yet and remains local/reference material.")
    linear = build_linear_snapshot(env)
    if linear["linear_api"] != "live":
        warnings.append(f"Linear API snapshot is {linear['linear_api']}; using local config fallback.")
    mcp_payload = build_mcp_payload(env)
    if mcp_payload["source_installed"] and mcp_payload["daemon_reload_needed"] is True:
        warnings.append("Niklas MCP daemon needs reload before live clients discover BERT tools.")
    next_actions = [
        "Keep BERT stage execution dry-run until the runtime adapter contract accepts write/apply boundaries.",
        "Use Linear issue ERI-2415 for closeback and evidence from this pilot slice.",
    ]
    if mcp_payload["daemon_reload_needed"] is True:
        next_actions.insert(1, "Reload the Niklas MCP daemon after BERT tool definitions are installed.")
    elif mcp_payload["daemon_reload_needed"] is None:
        next_actions.insert(
            1,
            "Reconnect any stale MCP clients if they do not discover the newly installed bert_* tools.",
        )
    builder_cli = _builder_cli_status(env)
    if isinstance(builder_cli, dict) and builder_cli.get("error"):
        warnings.append(f"legacy builder CLI status unavailable: {builder_cli['error']}")
    return {
        "generated_at": utcnow(),
        "version": BERT_VERSION,
        "mode": READ_ONLY_MODE,
        "name": "BERT",
        "write_enabled": False,
        "apply_blocker": APPLY_BLOCKER,
        "roots": roots,
        "git": git,
        "linear": linear,
        "niklas": {
            "sqlite": _niklas_status(env),
            "mcp": mcp_payload,
        },
        "naming": NAMING,
        "stages": STAGE_ORDER,
        "builder_cli": builder_cli,
        "warnings": warnings,
        "failures": failures,
        "next": next_actions,
    }


def build_doctor_payload(env: BertEnvironment | None = None) -> dict[str, Any]:
    payload = build_readiness_payload(env)
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "readiness": "fail" if payload["failures"] else "ready_with_warnings" if payload["warnings"] else "ready",
        "status": payload,
        "warnings": payload["warnings"],
        "failures": payload["failures"],
    }


def _stage_by_command(command: str) -> dict[str, Any]:
    for stage in STAGE_ORDER:
        if stage["command"] == command or stage["id"] == command:
            return stage
    valid = ", ".join(stage["command"] for stage in STAGE_ORDER)
    raise ValueError(f"unknown BERT stage {command!r}; expected one of: {valid}")


def build_stage_dry_run(
    stage_command: str,
    node: str | None = None,
    *,
    parent: str | None = None,
    linear_anchor: str | None = None,
    env: BertEnvironment | None = None,
) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    stage = _stage_by_command(stage_command)
    node_value = node or "<node>"
    sources = [row["path"] for row in build_first_read_payload(env)["first_read"] if row["exists"]]
    return {
        "generated_at": utcnow(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "stage": stage,
        "node": node_value,
        "parent": parent,
        "linear_anchor": linear_anchor,
        "sources": sources,
        "expected_outputs": stage["expected_outputs"],
        "blocked_writes": [
            {
                "surface": "Linear",
                "operation": "create/update issues, documents, status updates, or hierarchy",
                "blocked_by": APPLY_BLOCKER,
            },
            {
                "surface": "Niklas graph",
                "operation": "ingest paths, write atoms, link assets, or mutate relationships",
                "blocked_by": "MCP_WRITE_TOKEN and BERT write/apply contract are intentionally not used by this pilot slice.",
            },
            {
                "surface": "local BERT Markdown",
                "operation": "create or revise stage packets",
                "blocked_by": "Pilot commands emit dry-run payloads only.",
            },
        ],
        "next": "Review this dry-run payload, then accept the runtime adapter contract before adding --write/--apply.",
    }


def build_solve_payload(problem: str, env: BertEnvironment | None = None) -> dict[str, Any]:
    env = env or BertEnvironment.default()
    return {
        "generated_at": utcnow(),
        "problem": problem.strip(),
        "mode": READ_ONLY_MODE,
        "write_enabled": False,
        "reason": "BERT pilot routes the problem through the staged method without creating files or Linear/Niklas updates.",
        "recommended_route": [
            build_stage_dry_run(stage["command"], "<node>", env=env)
            for stage in STAGE_ORDER
        ],
        "next": "Run `bert setup <node>` after choosing a durable node name and parent surface.",
    }
