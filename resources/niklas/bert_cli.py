#!/usr/bin/env python3
"""Standalone BERT CLI routed through the local Niklas runtime.

This first slice is intentionally read-only. It consolidates BERT naming,
reports the current local surfaces, and gives a deterministic route for running
the BERT staged method without mutating Linear, GitHub, Niklas, or files.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


HOME = Path.home()
NIKLAS_ROOT = HOME / "Desktop" / "Niklas"
NIKLAS_RUNTIME = NIKLAS_ROOT / "03-Runtime" / "Cornelius"
NIKLAS_CLI = NIKLAS_ROOT / "niklas"
BUILDER_ROOT = HOME / "Desktop" / "PROJECTS" / "NIKLAS-BUILDER"
BERT_ROOT = BUILDER_ROOT / "BERT"
BERT_MVP = BERT_ROOT / "BERT-MVP"
BERT_SKILL_PACK = BERT_ROOT / "BERT-SKILL-PACK"
BERT_LINEAR_BUILDOUT = BERT_ROOT / "BERT-LINEAR-BUILDOUT" / "5-2026_BERT_LINEAR_BUILDOUT"
LEGACY_BUILDER_CLI = BERT_ROOT / "bin" / "niklas-bert"

STAGE_ORDER = [
    {
        "id": "0",
        "name": "0_BERT: PROJECT SETUP",
        "command": "setup",
        "purpose": "Place the problem, verify fit, create project parameters, and hand off safely.",
    },
    {
        "id": "1",
        "name": "1_BERT: GOAL",
        "command": "goal",
        "purpose": "Turn the rough intent into the best possible goal and routed questions.",
    },
    {
        "id": "2",
        "name": "2 - BERT Research Scout",
        "command": "research-scout",
        "purpose": "Find the strongest sources, source-makers, constraints, and internal overlap.",
    },
    {
        "id": "3",
        "name": "BERT Expert Plans",
        "command": "expert-plans",
        "purpose": "Synthesize expert-informed routes, tradeoffs, assumptions, and next moves.",
    },
    {
        "id": "handoff",
        "name": "BERT Handoff",
        "command": "handoff",
        "purpose": "Package the result so another agent or CLI run can resume without chat history.",
    },
]

NAMING = [
    {
        "label": "BERT",
        "kind": "canonical CLI/product/protocol root",
        "status": "use this for the executable name and product root",
        "notes": "The standalone command should be `bert`; Linear root is top-level `BERT`.",
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
        "notes": "Treat this as a spoken confusion around GMVP unless Erich defines it separately.",
    },
]

FIRST_READ = [
    BERT_ROOT / "README.md",
    BUILDER_ROOT / "docs" / "reference" / "BERT_INTEGRATION_MAP.md",
    BERT_MVP / ".linear-config",
    BERT_MVP / "BERT" / "LINEAR.md",
    BERT_MVP / "BERT" / "BERT_PROGRESS.md",
    BERT_MVP / "BERT" / "handoffs" / "NIKLAS_BUILDER_BERT_CLI_HANDOFF_2026-06-03.md",
    BERT_MVP / "BERT" / "handoffs" / "CLOUD_CODE_PICKUP_2026-05-28.md",
    BERT_MVP / "BERT" / "stages" / "01-goal-app" / "1_BERT_GOAL.md",
    BERT_MVP / "BERT" / "stage-zero" / "project-setup-skill" / "stages" / "01-goal" / "goal_V8.md",
    BERT_MVP / "BERT" / "stage-zero" / "project-setup-skill" / "stages" / "02-experts" / "experts_V7.md",
    BERT_MVP / "BERT" / "stage-zero" / "project-setup-skill" / "stages" / "03-expert-plans" / "expert_plans_V1.md",
]


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
    output = result["stdout"] or result["stderr"]
    return output.splitlines()[0] if output else "not a git repo or no output"


def path_state(path: Path) -> dict[str, Any]:
    return {"path": str(path), "exists": path.exists()}


def builder_status() -> dict[str, Any] | None:
    if not LEGACY_BUILDER_CLI.exists():
        return None
    result = run_command([str(LEGACY_BUILDER_CLI), "status", "--json"], BUILDER_ROOT)
    if not result["ok"] or not result["stdout"]:
        return {"error": result["stderr"] or result["stdout"] or "unknown legacy CLI error"}
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        return {"error": f"legacy CLI emitted invalid JSON: {exc}"}


def current_status() -> dict[str, Any]:
    return {
        "name": "BERT",
        "generated_by": "bert-cli-v0",
        "mode": "read_only",
        "readiness": "first_cli_slice",
        "canonical_command": str(NIKLAS_ROOT / "bert"),
        "canonical_root": str(BERT_ROOT),
        "niklas": {
            "root": path_state(NIKLAS_ROOT),
            "runtime": path_state(NIKLAS_RUNTIME),
            "cli": path_state(NIKLAS_CLI),
        },
        "builder": {
            "root": path_state(BUILDER_ROOT),
            "bert_root": path_state(BERT_ROOT),
            "bert_mvp": path_state(BERT_MVP),
            "skill_pack": path_state(BERT_SKILL_PACK),
            "linear_buildout": path_state(BERT_LINEAR_BUILDOUT),
            "legacy_builder_cli": path_state(LEGACY_BUILDER_CLI),
        },
        "git": {
            "niklas_runtime": git_branch(NIKLAS_RUNTIME),
            "builder_root": git_branch(BUILDER_ROOT),
            "bert_mvp": git_branch(BERT_MVP),
            "skill_pack": git_branch(BERT_SKILL_PACK),
            "linear_buildout": git_branch(BERT_LINEAR_BUILDOUT),
        },
        "naming": NAMING,
        "stages": STAGE_ORDER,
        "builder_cli": builder_status(),
        "next": [
            "Keep `bert` as the standalone command under /Users/erichroepke/Desktop/Niklas.",
            "Treat `BERT` as the product/protocol/CLI root.",
            "Treat `BERT GMVP` as the current G-Stack MVP wave and `BERT MVP` as legacy/local repo naming.",
            "Promote read-only routing first; add write/apply behavior only after the runtime adapter contract is accepted.",
        ],
    }


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def render_status(payload: dict[str, Any]) -> None:
    print("BERT CLI")
    print(f"command: {payload['canonical_command']}")
    print(f"mode:    {payload['mode']}")
    print(f"state:   {payload['readiness']}")
    print()
    print("canonical naming:")
    for item in payload["naming"]:
        marker = "use" if item["label"] == "BERT" else "map"
        print(f"  {marker:4} {item['label']}: {item['status']}")
    print()
    print("surfaces:")
    for section in ("niklas", "builder"):
        print(f"  {section}:")
        for name, state in payload[section].items():
            marker = "ok" if state["exists"] else "missing"
            print(f"    {marker:7} {name:18} {state['path']}")
    print()
    print("git:")
    for name, branch in payload["git"].items():
        print(f"  {name}: {branch}")
    print()
    print("next:")
    for item in payload["next"]:
        print(f"  - {item}")


def command_status(args: argparse.Namespace) -> int:
    payload = current_status()
    if args.json:
        emit_json(payload)
    else:
        render_status(payload)
    return 0


def command_which(args: argparse.Namespace) -> int:
    payload = {"naming": NAMING}
    if args.json:
        emit_json(payload)
        return 0
    print("BERT naming map")
    for item in NAMING:
        print()
        print(item["label"])
        print(f"  kind:   {item['kind']}")
        print(f"  status: {item['status']}")
        print(f"  notes:  {item['notes']}")
    return 0


def command_paths(args: argparse.Namespace) -> int:
    payload = current_status()
    paths = {
        "bert_command": payload["canonical_command"],
        "niklas_root": str(NIKLAS_ROOT),
        "niklas_runtime": str(NIKLAS_RUNTIME),
        "builder_root": str(BUILDER_ROOT),
        "bert_root": str(BERT_ROOT),
        "bert_mvp": str(BERT_MVP),
        "bert_skill_pack": str(BERT_SKILL_PACK),
        "bert_linear_buildout": str(BERT_LINEAR_BUILDOUT),
    }
    if args.json:
        emit_json(paths)
    else:
        for name, path in paths.items():
            print(f"{name}: {path}")
    return 0


def command_stages(args: argparse.Namespace) -> int:
    payload = {"stages": STAGE_ORDER}
    if args.json:
        emit_json(payload)
        return 0
    print("BERT stage route")
    for stage in STAGE_ORDER:
        print(f"{stage['id']:>7}  bert {stage['command']:<15} {stage['name']}")
        print(f"         {stage['purpose']}")
    return 0


def command_first_read(args: argparse.Namespace) -> int:
    rows = [{"path": str(path), "exists": path.exists()} for path in FIRST_READ]
    if args.json:
        emit_json({"first_read": rows})
        return 0
    for row in rows:
        marker = "ok" if row["exists"] else "missing"
        print(f"{marker:7} {row['path']}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    payload = current_status()
    failures: list[str] = []
    warnings: list[str] = []

    for section in ("niklas", "builder"):
        for name, state in payload[section].items():
            if not state["exists"]:
                failures.append(f"missing {section}.{name}: {state['path']}")

    if "No commits yet" in payload["git"]["builder_root"]:
        warnings.append("NIKLAS-BUILDER root git repo has no commits yet; root-level CLI docs are not durable.")
    if "No commits yet" in payload["git"]["linear_buildout"]:
        warnings.append("BERT-LINEAR-BUILDOUT main repo has no commits yet and remains local/reference material.")
    builder = payload.get("builder_cli")
    if isinstance(builder, dict) and builder.get("error"):
        warnings.append(f"legacy builder CLI status unavailable: {builder['error']}")

    doctor = {"failures": failures, "warnings": warnings}
    if args.json:
        emit_json({"status": payload, "doctor": doctor})
        return 1 if failures else 0

    render_status(payload)
    print()
    print("doctor:")
    for item in failures:
        print(f"  FAIL: {item}")
    for item in warnings:
        print(f"  WARN: {item}")
    if not failures and not warnings:
        print("  ok")
    return 1 if failures else 0


def command_solve(args: argparse.Namespace) -> int:
    problem = " ".join(args.problem).strip()
    route = {
        "problem": problem,
        "mode": "dry_run",
        "write_enabled": False,
        "reason": "BERT CLI v0 routes the problem through the staged method without creating files or Linear updates.",
        "recommended_route": [
            {
                "stage": stage["name"],
                "command": f"bert {stage['command']} <node>",
                "purpose": stage["purpose"],
            }
            for stage in STAGE_ORDER
        ],
        "next_manual_step": "Run `bert setup <node>` after choosing a durable node name and parent surface.",
    }
    if args.json:
        emit_json(route)
        return 0
    print("BERT solve route")
    print(f"problem: {problem or '(none supplied)'}")
    print("mode: dry-run; no files, Linear records, or graph writes will be created")
    print()
    for step in route["recommended_route"]:
        print(f"- {step['command']}: {step['stage']}")
        print(f"  {step['purpose']}")
    print()
    print(route["next_manual_step"])
    return 0


def placeholder_stage_command(stage_command: str, args: argparse.Namespace) -> int:
    node = args.node or "<node>"
    payload = {
        "command": f"bert {stage_command}",
        "node": node,
        "mode": "dry_run",
        "write_enabled": False,
        "message": "Stage execution is intentionally dry-run only in this first CLI slice.",
        "next": "Accept the runtime adapter contract before enabling --write or Linear/Niklas mutation.",
    }
    if args.json:
        emit_json(payload)
        return 0
    print(f"bert {stage_command}")
    print(f"node: {node}")
    print("mode: dry-run")
    print(payload["message"])
    print(payload["next"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bert",
        description="Standalone BERT CLI under Niklas for large-problem staged routing.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show consolidated BERT/Niklas status.")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    which = sub.add_parser("which", help="Explain BERT, BERT GMVP, BERT MVP, and non-canonical names.")
    which.add_argument("--json", action="store_true")
    which.set_defaults(func=command_which)

    paths = sub.add_parser("paths", help="Print canonical local paths.")
    paths.add_argument("--json", action="store_true")
    paths.set_defaults(func=command_paths)

    stages = sub.add_parser("stages", help="Print the BERT staged route.")
    stages.add_argument("--json", action="store_true")
    stages.set_defaults(func=command_stages)

    first_read = sub.add_parser("first-read", help="Print the current BERT first-read order.")
    first_read.add_argument("--json", action="store_true")
    first_read.set_defaults(func=command_first_read)

    doctor = sub.add_parser("doctor", help="Run local BERT CLI readiness checks.")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=command_doctor)

    solve = sub.add_parser("solve", help="Route a large problem through BERT as a dry-run.")
    solve.add_argument("problem", nargs="*")
    solve.add_argument("--json", action="store_true")
    solve.set_defaults(func=command_solve)

    for stage in STAGE_ORDER:
        stage_parser = sub.add_parser(stage["command"], help=f"Dry-run {stage['name']}.")
        stage_parser.add_argument("node", nargs="?")
        stage_parser.add_argument("--json", action="store_true")
        stage_parser.set_defaults(func=lambda args, command=stage["command"]: placeholder_stage_command(command, args))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
