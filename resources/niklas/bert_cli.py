#!/usr/bin/env python3
"""Standalone BERT CLI routed through the local Niklas runtime."""
from __future__ import annotations

import argparse
import json
from typing import Any

from .bert_core import (
    NAMING,
    STAGE_ORDER,
    build_accept_payload,
    build_bert_on_payload,
    build_doctor_payload,
    build_first_read_payload,
    build_linear_snapshot,
    build_mcp_payload,
    build_next_payload,
    build_node_create_payload,
    build_node_locate_payload,
    build_node_map_payload,
    build_node_spawn_children_payload,
    build_node_stages_payload,
    build_node_start_payload,
    build_node_template_payload,
    build_project_analyze_payload,
    build_project_create_payload,
    build_project_init_payload,
    build_project_open_payload,
    build_project_template_payload,
    build_readiness_payload,
    build_solve_payload,
    build_stage_draft_payload,
    build_stage_dry_run,
)


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def render_status(payload: dict[str, Any]) -> None:
    print("BERT CLI")
    print(f"mode:    {payload['mode']}")
    print(f"version: {payload['version']}")
    print(f"writes:  {'enabled' if payload['write_enabled'] else 'disabled'}")
    print()
    print("roots:")
    for name, state in payload["roots"].items():
        marker = "ok" if state["exists"] else "missing"
        print(f"  {marker:7} {name:22} {state['path']}")
    print()
    print("linear:")
    print(f"  api: {payload['linear']['linear_api']}")
    local_values = payload["linear"].get("local_config", {}).get("values", {})
    if local_values:
        print(f"  root: {local_values.get('root_initiative', 'unknown')}")
        print(f"  initiative: {local_values.get('initiative', 'unknown')}")
    print()
    print("mcp:")
    mcp = payload["niklas"]["mcp"]
    print(f"  endpoint: {mcp['endpoint']}")
    print(f"  source installed: {mcp['source_installed']}")
    print(f"  daemon reload needed: {mcp['daemon_reload_needed']}")
    print()
    print("warnings:")
    if payload["warnings"]:
        for item in payload["warnings"]:
            print(f"  WARN: {item}")
    else:
        print("  none")
    print()
    print("failures:")
    if payload["failures"]:
        for item in payload["failures"]:
            print(f"  FAIL: {item}")
    else:
        print("  none")
    print()
    print("next:")
    for item in payload["next"]:
        print(f"  - {item}")


def render_which(payload: dict[str, Any]) -> None:
    print("BERT naming map")
    for item in payload["naming"]:
        print()
        print(item["label"])
        print(f"  kind:   {item['kind']}")
        print(f"  status: {item['status']}")
        print(f"  notes:  {item['notes']}")


def render_paths(payload: dict[str, Any]) -> None:
    for name, state in payload["roots"].items():
        print(f"{name}: {state['path']}")


def render_stages(payload: dict[str, Any]) -> None:
    print("BERT stage route")
    for stage in payload["stages"]:
        print(f"{stage['id']:>7}  bert {stage['command']:<15} {stage['name']}")
        print(f"         {stage['purpose']}")


def render_first_read(payload: dict[str, Any]) -> None:
    for row in payload["first_read"]:
        marker = "ok" if row["exists"] else "missing"
        print(f"{marker:7} {row['path']}")


def render_doctor(payload: dict[str, Any]) -> None:
    render_status(payload["status"])
    print()
    print(f"doctor: {payload['readiness']}")


def render_linear(payload: dict[str, Any]) -> None:
    print("BERT Linear snapshot")
    print(f"mode: {payload['mode']}")
    print(f"linear_api: {payload['linear_api']}")
    print(f"local_config: {payload['local_config']['path']}")
    values = payload["local_config"].get("values", {})
    for key in ("root_initiative", "initiative", "runtime_linear_operations_initiative", "default_project"):
        if key in values:
            print(f"{key}: {values[key]}")
    if payload.get("error"):
        print(f"error: {payload['error']}")


def render_mcp(payload: dict[str, Any]) -> None:
    print("BERT MCP snapshot")
    print(f"endpoint: {payload['endpoint']}")
    print(f"server_file: {payload['server_file']}")
    print(f"source_installed: {payload['source_installed']}")
    print(f"daemon_reload_needed: {payload['daemon_reload_needed']}")
    print("tools:")
    for tool in payload["expected_tools"]:
        marker = "ok" if payload["source_tools_present"].get(tool) else "missing"
        print(f"  {marker:7} {tool}")
    print(payload["daemon_reload_reason"])


def render_stage(payload: dict[str, Any]) -> None:
    print(f"bert {payload['stage']['command']}")
    print(f"node: {payload['node']}")
    print(f"mode: {payload['mode']}")
    print(f"writes: {'enabled' if payload['write_enabled'] else 'disabled'}")
    print(payload["stage"]["purpose"])
    print()
    print("expected outputs:")
    for item in payload["expected_outputs"]:
        print(f"  - {item}")
    print()
    print("blocked writes:")
    for item in payload["blocked_writes"]:
        print(f"  - {item['surface']}: {item['operation']} ({item['blocked_by']})")
    print()
    print(payload["next"])


def render_solve(payload: dict[str, Any]) -> None:
    print("BERT solve route")
    print(f"problem: {payload['problem'] or '(none supplied)'}")
    print(f"mode: {payload['mode']}")
    print(f"writes: {'enabled' if payload['write_enabled'] else 'disabled'}")
    print()
    for item in payload["recommended_route"]:
        stage = item["stage"]
        print(f"- bert {stage['command']} <node>: {stage['name']}")
        print(f"  {stage['purpose']}")
    print()
    print(payload["next"])


def render_on(payload: dict[str, Any]) -> None:
    process = payload["bert_process"]
    action = payload["primary_action"]
    linear = payload["linear_status"]
    niklas = payload["niklas_status"]
    material = payload.get("project_material") or {}

    print(payload["headline"])
    print()
    print(f"selected: {payload['selected_folder']}")
    print(f"state:    {process['state']}")
    print(f"position: {process['current_node']} / {process['current_stage']}")
    print()
    print(payload["body"])
    print()
    print(f"next:     {action['label']}")
    if action.get("command"):
        print(f"command:  {action['command']}")
    if action.get("reason"):
        print(f"why:      {action['reason']}")
    print()
    print("status:")
    print(f"  linear: {linear.get('lookup')} anchor={linear.get('anchor')}")
    print(f"  niklas: {niklas.get('correlation')} anchor={niklas.get('anchor')} matches={niklas.get('matches_count')}")

    markers = material.get("markers") or []
    if markers:
        print()
        print("project material:")
        for marker in markers[:5]:
            print(f"  - {marker['kind']}: {marker['path']}")


def render_next(payload: dict[str, Any]) -> None:
    print("bert next")
    print(payload["status_line"])
    if payload.get("before"):
        print(f"first:    {payload['before']}")
    print(f"waiting:  {payload['waiting_on']}")
    print(f"command:  {payload['next_command']}")


def render_draft(payload: dict[str, Any]) -> None:
    print("bert stage draft")
    print(f"node:   {payload['node_path']}")
    if payload.get("stage"):
        print(f"stage:  {payload['stage']['folder']}")
    if payload.get("artifact"):
        artifact = payload["artifact"]
        print(f"file:   {artifact['path']} (V{artifact['version']})")
        flags = []
        if artifact.get("carried_forward"):
            flags.append("carried forward from prior version")
        if artifact.get("seeded"):
            flags.append("includes parent seed")
        if flags:
            print(f"notes:  {'; '.join(flags)}")
    print(f"mode:   {payload['mode']}")
    print(f"writes: {'enabled' if payload['write_enabled'] else 'disabled'}")
    if payload.get("reason"):
        print(f"reason: {payload['reason']}")
    for warning in payload.get("warnings", []):
        print(f"WARN:   {warning}")
    print("next:")
    for item in payload.get("next", []):
        print(f"  - {item}")


def render_accept(payload: dict[str, Any]) -> None:
    print("bert accept")
    print(f"node:     {payload['node_path']}")
    if payload.get("stage"):
        print(f"stage:    {payload['stage'].get('folder')}")
    if payload.get("artifact"):
        print(f"file:     {payload['artifact']['path']} (V{payload['artifact']['version']})")
    print(f"mode:     {payload['mode']}")
    verdict = "ACCEPTED" if payload["accepted"] else (
        "would accept (re-run with --apply)" if payload["would_accept"] else "refused"
    )
    print(f"verdict:  {verdict}")
    if payload.get("reason"):
        print(f"reason:   {payload['reason']}")
    for warning in payload.get("warnings", []):
        print(f"WARN:     {warning}")
    print("next:")
    for item in payload.get("next", []):
        print(f"  - {item}")


def render_scaffold_payload(payload: dict[str, Any]) -> None:
    print(payload["operation"] if "operation" in payload else "bert scaffold template")
    if payload.get("project_name"):
        print(f"project: {payload['project_name']}")
    if payload.get("project_dir"):
        print(f"path: {payload['project_dir']}")
    if payload.get("node_path"):
        print(f"node: {payload['node_path']}")
    print(f"mode: {payload['mode']}")
    print(f"writes: {'enabled' if payload['write_enabled'] else 'disabled'}")
    if payload.get("already_initialized"):
        print("already initialized: yes — resume with `bert on`; adoption never overwrites")
    print()
    print(payload.get("ingest_rule", "0-ingest only exists on L1M1."))
    print()
    if payload.get("hierarchy_contract"):
        contract = payload["hierarchy_contract"]
        print("hierarchy:")
        print(f"  local_tree: {contract['local_tree']}")
        print(f"  source_of_truth: {contract['source_of_truth']}")
        print(f"  map_rule: {contract['map_rule']}")
        print(f"  recursion_rule: {contract['recursion_rule']}")
    if payload.get("folder_gate"):
        gate = payload["folder_gate"]
        print("folder gate:")
        print(f"  status: {gate['status']}")
        print(f"  safe_to_write: {gate['safe_to_write']}")
        print(f"  reason: {gate['reason']}")
    if payload.get("bert_fit_assessment"):
        fit = payload["bert_fit_assessment"]
        print("bert fit:")
        print(f"  status: {fit['status']}")
        print(f"  decision: {fit['decision']}")
        print(f"  reason: {fit['reason']}")
    if payload.get("bert_process"):
        process = payload["bert_process"]
        print("bert process:")
        print(f"  state: {process['state']}")
        print(f"  current_node: {process['current_node']}")
        print(f"  current_stage: {process['current_stage']}")
        print(f"  resume_action: {process['resume_action']}")
        if process.get("next_command"):
            print(f"  next_command: {process['next_command']}")
    if payload.get("inventory"):
        inventory = payload["inventory"]
        print("project analysis:")
        print(f"  likely_project_kind: {inventory['likely_project_kind']}")
        print(f"  files_sampled: {inventory['files_sampled']}")
        print(f"  dirs_sampled: {inventory['dirs_sampled']}")
        print(f"  truncated: {inventory['truncated']}")
        markers = inventory.get("markers") or []
        if markers:
            print("  markers:")
            for marker in markers:
                print(f"    - {marker['kind']}: {marker['path']}")
    if payload.get("linear_mirror"):
        mirror = payload["linear_mirror"]
        print("linear mirror:")
        if mirror.get("default_linear_type"):
            print(f"  default_linear_type: {mirror['default_linear_type']}")
            print(f"  default_linear_role: {mirror['default_linear_role']}")
        if mirror.get("root"):
            print(f"  root: {mirror['root']['node_path']} -> {mirror['root']['default_linear_type']}")
        if mirror.get("current"):
            print(f"  current: {mirror['current']['node_path']} -> {mirror['current']['default_linear_type']}")
        if mirror.get("write_status"):
            print(f"  write_status: {mirror['write_status']}")
    if payload.get("relative_tree"):
        print("tree:")
        for item in payload["relative_tree"]:
            print(f"  {item}")
    elif payload.get("stage_folders"):
        print("stage folders:")
        for item in payload["stage_folders"]:
            print(f"  {item['folder']}: {item['purpose']}")
    if payload.get("position"):
        print("position:")
        position = payload["position"]
        print(f"  local_root_node: {position['local_root_node']}")
        print(f"  current_known_node: {position['current_known_node']}")
        print(f"  linear_tree_walk: {position['linear_tree_walk']}")
        if position.get("niklas_correlation"):
            print(f"  niklas_correlation: {position['niklas_correlation']}")
        if position.get("niklas_anchor"):
            print(f"  niklas_anchor: {position['niklas_anchor']}")
    if payload.get("niklas_lookup"):
        lookup = payload["niklas_lookup"]
        print("niklas lookup:")
        print(f"  db: {lookup['db_path']}")
        print(f"  schema_present: {lookup['schema_present']}")
        print(f"  correlation_status: {lookup['correlation_status']}")
        print(f"  local_anchor: {lookup['local_anchor']}")
        print(f"  matches: {len(lookup.get('matches') or [])}")
        for match in (lookup.get("matches") or [])[:5]:
            print(f"    - {match.get('id')} · {match.get('title')} ({match.get('type')})")
    if payload.get("altitude"):
        altitude = payload["altitude"]
        print("altitude:")
        print(f"  {altitude['altitude']} -> {altitude['linear_target']}")
        print(f"  {altitude['reason']}")
    if payload.get("nodes"):
        print("nodes:")
        for node in payload["nodes"]:
            print(f"  {node['node_path']} ingest={node['has_ingest']}")
    if payload.get("proposed_node"):
        proposed = payload["proposed_node"]
        print("proposed node:")
        print(f"  {proposed['node_path']} -> {proposed['linear_mirror']['default_linear_type']}")
        print(f"  source: {proposed['source']}")
    if payload.get("workflow_steps"):
        print("workflow:")
        for item in payload["workflow_steps"]:
            detail = item.get("node_path") or item.get("path") or ""
            print(f"  {item['step']}: {item['status']} {detail}")
    if payload.get("stages") and isinstance(payload["stages"], list):
        print("stages:")
        for item in payload["stages"]:
            marker = "ok" if item.get("exists") else "missing"
            print(f"  {marker:7} {item['folder']}: {item['purpose']}")
    if payload.get("steps"):
        print("map steps:")
        for item in payload["steps"]:
            print(f"  {item['index']}. {item['title']} -> {item.get('child_node') or 'unmapped'}")
    if payload.get("planned_children"):
        print("planned children:")
        for item in payload["planned_children"]:
            print(f"  step {item['step']}: {item['node_path']} -> {item['linear_mirror']['default_linear_type']}")
    if payload.get("applied"):
        applied = payload["applied"]
        print()
        print("applied:")
        print(f"  created_dirs: {len(applied['created_dirs'])}")
        print(f"  existing_dirs: {len(applied['existing_dirs'])}")
        print(f"  written_files: {len(applied['written_files'])}")
        print(f"  skipped_existing_files: {len(applied['skipped_existing_files'])}")
    if payload.get("external_writes"):
        print()
        print("external writes:")
        for item in payload["external_writes"]:
            print(f"  - {item['surface']}: {item['status']} ({item['reason']})")
    if payload.get("next"):
        print()
        print("next:")
        for item in payload["next"]:
            print(f"  - {item}")


def command_status(args: argparse.Namespace) -> int:
    payload = build_readiness_payload()
    emit_json(payload) if args.json else render_status(payload)
    return 1 if payload["failures"] else 0


def command_on(args: argparse.Namespace) -> int:
    payload = build_bert_on_payload(
        args.project,
        projects_root=args.projects_root,
        task=" ".join(args.task) if args.task else None,
        linear_anchor=args.linear_anchor,
    )
    emit_json(payload) if args.json else render_on(payload)
    return 0


def command_which(args: argparse.Namespace) -> int:
    payload = {"naming": NAMING}
    emit_json(payload) if args.json else render_which(payload)
    return 0


def command_paths(args: argparse.Namespace) -> int:
    payload = build_readiness_payload()
    emit_json(payload["roots"]) if args.json else render_paths(payload)
    return 0


def command_stages(args: argparse.Namespace) -> int:
    payload = {"stages": STAGE_ORDER}
    emit_json(payload) if args.json else render_stages(payload)
    return 0


def command_first_read(args: argparse.Namespace) -> int:
    payload = build_first_read_payload()
    emit_json(payload) if args.json else render_first_read(payload)
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    payload = build_doctor_payload()
    emit_json(payload) if args.json else render_doctor(payload)
    return 1 if payload["failures"] else 0


def command_linear(args: argparse.Namespace) -> int:
    payload = build_linear_snapshot()
    emit_json(payload) if args.json else render_linear(payload)
    return 0


def command_mcp(args: argparse.Namespace) -> int:
    payload = build_mcp_payload()
    emit_json(payload) if args.json else render_mcp(payload)
    return 0


def command_solve(args: argparse.Namespace) -> int:
    payload = build_solve_payload(" ".join(args.problem))
    emit_json(payload) if args.json else render_solve(payload)
    return 0


def command_stage(stage_command: str, args: argparse.Namespace) -> int:
    payload = build_stage_dry_run(
        stage_command,
        args.node,
        parent=args.parent,
        linear_anchor=args.linear_anchor,
    )
    emit_json(payload) if args.json else render_stage(payload)
    return 0


def command_project_template(args: argparse.Namespace) -> int:
    payload = build_project_template_payload(args.name, slug=args.slug)
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_project_create(args: argparse.Namespace) -> int:
    payload = build_project_create_payload(
        args.name,
        slug=args.slug,
        projects_root=args.projects_root,
        linear_anchor=args.linear_anchor,
        niklas_anchor=args.niklas_anchor,
        apply=args.apply,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_project_analyze(args: argparse.Namespace) -> int:
    payload = build_project_analyze_payload(
        args.project,
        projects_root=args.projects_root,
        task=" ".join(args.task) if args.task else None,
        linear_anchor=args.linear_anchor,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_project_init(args: argparse.Namespace) -> int:
    payload = build_project_init_payload(
        args.path,
        name=args.name,
        linear_anchor=args.linear_anchor,
        niklas_anchor=args.niklas_anchor,
        apply=args.apply,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_project_open(args: argparse.Namespace) -> int:
    payload = build_project_open_payload(
        args.project,
        projects_root=args.projects_root,
        task=" ".join(args.task) if args.task else None,
        linear_anchor=args.linear_anchor,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_orient(args: argparse.Namespace) -> int:
    payload = build_project_open_payload(
        args.project,
        projects_root=args.projects_root,
        task=" ".join(args.task) if args.task else None,
        linear_anchor=args.linear_anchor,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_node_template(args: argparse.Namespace) -> int:
    node_path = f"{args.parent}/{args.node}" if args.parent else args.node
    payload = build_node_template_payload(node_path)
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_node_create(args: argparse.Namespace) -> int:
    payload = build_node_create_payload(
        args.node,
        project=args.project,
        parent_path=args.parent,
        projects_root=args.projects_root,
        apply=args.apply,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_node_locate(args: argparse.Namespace) -> int:
    payload = build_node_locate_payload(
        args.project,
        parent_path=args.parent,
        node_id=args.node,
        step=args.step,
        task=" ".join(args.task) if args.task else None,
        projects_root=args.projects_root,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_node_start(args: argparse.Namespace) -> int:
    payload = build_node_start_payload(
        args.project,
        name=args.name,
        parent_path=args.parent,
        node_id=args.node,
        step=args.step,
        task=" ".join(args.task) if args.task else None,
        projects_root=args.projects_root,
        init_project=args.init_project,
        apply=args.apply,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_node_stages(args: argparse.Namespace) -> int:
    payload = build_node_stages_payload(
        args.project,
        node_path=args.node_path,
        projects_root=args.projects_root,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_node_map(args: argparse.Namespace) -> int:
    payload = build_node_map_payload(
        args.project,
        node_path=args.node_path,
        projects_root=args.projects_root,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_node_spawn_children(args: argparse.Namespace) -> int:
    payload = build_node_spawn_children_payload(
        args.project,
        parent_path=args.parent,
        projects_root=args.projects_root,
        apply=args.apply,
    )
    emit_json(payload) if args.json else render_scaffold_payload(payload)
    return 0


def command_next(args: argparse.Namespace) -> int:
    payload = build_next_payload(args.project, projects_root=args.projects_root)
    emit_json(payload) if args.json else render_next(payload)
    return 0


def command_stage_draft(args: argparse.Namespace) -> int:
    payload = build_stage_draft_payload(
        args.project,
        node_path=args.node,
        projects_root=args.projects_root,
        apply=args.apply,
    )
    emit_json(payload) if args.json else render_draft(payload)
    return 0


def command_accept(args: argparse.Namespace) -> int:
    payload = build_accept_payload(
        args.project,
        node_path=args.node,
        stage=args.stage,
        projects_root=args.projects_root,
        apply=args.apply,
    )
    emit_json(payload) if args.json else render_accept(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bert",
        description="Standalone BERT CLI under Niklas for large-problem staged routing.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    next_cmd = sub.add_parser("next", help="The 10-second UX: what is the one next action.")
    next_cmd.add_argument("--project", default=".", help="Project path. Defaults to current directory.")
    next_cmd.add_argument("--projects-root")
    next_cmd.add_argument("--json", action="store_true")
    next_cmd.set_defaults(func=command_next)

    stage_group = sub.add_parser("stage", help="Stage-loop verbs (draft).")
    stage_sub = stage_group.add_subparsers(dest="stage_command", required=True)
    stage_draft = stage_sub.add_parser(
        "draft", help="Scaffold the next MDE draft for the current stage. Never overwrites."
    )
    stage_draft.add_argument("--project", default=".", help="Project path. Defaults to current directory.")
    stage_draft.add_argument("--node", help="Node path (defaults to state.json current_node).")
    stage_draft.add_argument("--projects-root")
    stage_draft.add_argument("--apply", action="store_true", help="Write the draft file and update state.json.")
    stage_draft.add_argument("--json", action="store_true")
    stage_draft.set_defaults(func=command_stage_draft)

    accept = sub.add_parser(
        "accept", help="Acceptance gate: stamp the current stage artifact and advance state."
    )
    accept.add_argument("--project", default=".", help="Project path. Defaults to current directory.")
    accept.add_argument("--node", help="Node path (defaults to state.json current_node).")
    accept.add_argument("--stage", help="Stage folder to accept (must match the derived current stage).")
    accept.add_argument("--projects-root")
    accept.add_argument("--apply", action="store_true", help="Stamp the artifact and advance state.json.")
    accept.add_argument("--json", action="store_true")
    accept.set_defaults(func=command_accept)

    on = sub.add_parser("on", help="Turn BERT on for a selected project folder.")
    on.add_argument("project", nargs="?", default=".", help="Project folder. Defaults to current directory.")
    on.add_argument("--projects-root")
    on.add_argument("--linear-anchor")
    on.add_argument("--task", nargs="*")
    on.add_argument("--json", action="store_true")
    on.set_defaults(func=command_on)

    adopt = sub.add_parser(
        "adopt",
        help="Adopt a project folder: create the hidden .BERT workspace. Plan-only without --apply. Never overwrites files.",
    )
    adopt.add_argument("path", nargs="?", default=".", help="Project folder to adopt. Defaults to current directory.")
    adopt.add_argument("--name")
    adopt.add_argument("--linear-anchor")
    adopt.add_argument("--niklas-anchor")
    adopt.add_argument("--apply", action="store_true", help="Write missing .BERT folders/files. Never overwrites files.")
    adopt.add_argument("--json", action="store_true")
    adopt.set_defaults(func=command_project_init)

    status = sub.add_parser("status", help="Show consolidated BERT/Niklas readiness.")
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

    linear = sub.add_parser("linear", help="Show BERT Linear readiness and local fallback state.")
    linear.add_argument("--json", action="store_true")
    linear.set_defaults(func=command_linear)

    mcp = sub.add_parser("mcp", help="Show BERT MCP source/tool readiness.")
    mcp.add_argument("--json", action="store_true")
    mcp.set_defaults(func=command_mcp)

    solve = sub.add_parser("solve", help="Route a large problem through BERT as a dry-run.")
    solve.add_argument("problem", nargs="*")
    solve.add_argument("--json", action="store_true")
    solve.set_defaults(func=command_solve)

    orient = sub.add_parser("orient", help="Orient the current or supplied project before creating/resuming BERT nodes.")
    orient.add_argument("project", nargs="?", default=".", help="Project path or slug. Defaults to current directory.")
    orient.add_argument("--projects-root")
    orient.add_argument("--linear-anchor")
    orient.add_argument("--task", nargs="*")
    orient.add_argument("--json", action="store_true")
    orient.set_defaults(func=command_orient)

    project = sub.add_parser("project", help="Create or inspect BERT project scaffolds.")
    project_sub = project.add_subparsers(dest="project_command", required=True)

    project_template = project_sub.add_parser("template", help="Show the BERT project folder template.")
    project_template.add_argument("name", nargs="?", default="<project name>")
    project_template.add_argument("--slug")
    project_template.add_argument("--json", action="store_true")
    project_template.set_defaults(func=command_project_template)

    project_create = project_sub.add_parser("create", help="Create or dry-run a BERT project folder.")
    project_create.add_argument("name")
    project_create.add_argument("--slug")
    project_create.add_argument("--projects-root")
    project_create.add_argument("--linear-anchor")
    project_create.add_argument("--niklas-anchor")
    project_create.add_argument("--apply", action="store_true", help="Write missing local folders/files. Never overwrites files.")
    project_create.add_argument("--json", action="store_true")
    project_create.set_defaults(func=command_project_create)

    project_analyze = project_sub.add_parser("analyze", help="Analyze a folder before adopting it as a BERT project.")
    project_analyze.add_argument("project", nargs="?", default=".", help="Project folder to analyze. Defaults to current directory.")
    project_analyze.add_argument("--projects-root")
    project_analyze.add_argument("--linear-anchor")
    project_analyze.add_argument("--task", nargs="*")
    project_analyze.add_argument("--json", action="store_true")
    project_analyze.set_defaults(func=command_project_analyze)

    project_init = project_sub.add_parser("init", help="Create or dry-run a hidden .BERT workspace inside an existing project.")
    project_init.add_argument("path", nargs="?", default=".")
    project_init.add_argument("--name")
    project_init.add_argument("--linear-anchor")
    project_init.add_argument("--niklas-anchor")
    project_init.add_argument("--apply", action="store_true", help="Write missing .BERT folders/files. Never overwrites files.")
    project_init.add_argument("--json", action="store_true")
    project_init.set_defaults(func=command_project_init)

    project_open = project_sub.add_parser("open", help="Read a BERT project packet and orient Linear/Niklas position.")
    project_open.add_argument("project", help="Project slug or project path. If it contains .BERT, that workspace is used.")
    project_open.add_argument("--projects-root")
    project_open.add_argument("--linear-anchor")
    project_open.add_argument("--task", nargs="*")
    project_open.add_argument("--json", action="store_true")
    project_open.set_defaults(func=command_project_open)

    node = sub.add_parser("node", help="Create or inspect nested BERT L/M node scaffolds.")
    node_sub = node.add_subparsers(dest="node_command", required=True)

    node_locate = node_sub.add_parser("locate", help="Locate/propose the next BERT node before writing anything.")
    node_locate.add_argument("--project", default=".", help="Project slug or project path. Defaults to current directory.")
    node_locate.add_argument("--parent", default="L1M1", help="Parent node path, e.g. L1M1 or L1M1/L2M1.")
    node_locate.add_argument("--node", help="Requested child node id, e.g. L2M1.")
    node_locate.add_argument("--step", type=int, help="Parent MAP.md numbered step to turn into a child node.")
    node_locate.add_argument("--task", nargs="*")
    node_locate.add_argument("--projects-root")
    node_locate.add_argument("--json", action="store_true")
    node_locate.set_defaults(func=command_node_locate)

    node_start = node_sub.add_parser("start", help="Guided node startup: orient, optionally init, locate, optionally create, then stage route.")
    node_start.add_argument("--project", default=".", help="Project slug or project path. Defaults to current directory.")
    node_start.add_argument("--name", help="Project name used only if --init-project is supplied.")
    node_start.add_argument("--parent", default="L1M1", help="Parent node path.")
    node_start.add_argument("--node", help="Requested child node id, e.g. L2M1.")
    node_start.add_argument("--step", type=int, help="Parent MAP.md numbered step to turn into a child node.")
    node_start.add_argument("--task", nargs="*")
    node_start.add_argument("--projects-root")
    node_start.add_argument("--init-project", action="store_true", help="Allow start to create a missing .BERT workspace.")
    node_start.add_argument("--apply", action="store_true", help="Write missing local folders/files. Never overwrites files.")
    node_start.add_argument("--json", action="store_true")
    node_start.set_defaults(func=command_node_start)

    node_template = node_sub.add_parser("template", help="Show the folder template for one L/M node.")
    node_template.add_argument("node")
    node_template.add_argument("--parent")
    node_template.add_argument("--json", action="store_true")
    node_template.set_defaults(func=command_node_template)

    node_create = node_sub.add_parser("create", help="Create or dry-run a nested BERT L/M node folder.")
    node_create.add_argument("node")
    node_create.add_argument("--project", required=True, help="Project slug or absolute project path.")
    node_create.add_argument("--parent", help="Parent node path, e.g. L1M1 or L1M1/L2M1. Defaults to L1M1 for L2 nodes.")
    node_create.add_argument("--projects-root")
    node_create.add_argument("--apply", action="store_true", help="Write missing local folders/files. Never overwrites files.")
    node_create.add_argument("--json", action="store_true")
    node_create.set_defaults(func=command_node_create)

    node_stages = node_sub.add_parser("stages", help="Show stage order/status for one BERT node.")
    node_stages.add_argument("node_path", help="Node path, e.g. L1M1 or L1M1/L2M1.")
    node_stages.add_argument("--project", default=".", help="Project slug or project path. Defaults to current directory.")
    node_stages.add_argument("--projects-root")
    node_stages.add_argument("--json", action="store_true")
    node_stages.set_defaults(func=command_node_stages)

    node_map = node_sub.add_parser("map", help="Read a node MAP.md and report child-node candidates.")
    node_map.add_argument("node_path", help="Node path, e.g. L1M1 or L1M1/L2M1.")
    node_map.add_argument("--project", default=".", help="Project slug or project path. Defaults to current directory.")
    node_map.add_argument("--projects-root")
    node_map.add_argument("--json", action="store_true")
    node_map.set_defaults(func=command_node_map)

    node_spawn_children = node_sub.add_parser("spawn-children", help="Create or dry-run child nodes from a parent MAP.md.")
    node_spawn_children.add_argument("--project", default=".", help="Project slug or project path. Defaults to current directory.")
    node_spawn_children.add_argument("--parent", default="L1M1", help="Parent node path whose MAP.md should spawn children.")
    node_spawn_children.add_argument("--projects-root")
    node_spawn_children.add_argument("--apply", action="store_true", help="Write missing local folders/files. Never overwrites files.")
    node_spawn_children.add_argument("--json", action="store_true")
    node_spawn_children.set_defaults(func=command_node_spawn_children)

    for stage in STAGE_ORDER:
        stage_parser = sub.add_parser(stage["command"], help=f"Dry-run {stage['name']}.")
        stage_parser.add_argument("node", nargs="?")
        stage_parser.add_argument("--parent")
        stage_parser.add_argument("--linear-anchor")
        stage_parser.add_argument("--json", action="store_true")
        stage_parser.set_defaults(
            func=lambda args, command=stage["command"]: command_stage(command, args)
        )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
