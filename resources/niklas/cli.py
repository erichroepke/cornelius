#!/usr/bin/env python3
"""Niklas local graph CLI."""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

from .cli_factory import build_cli_catalog, render_markdown_catalog, write_catalog
from .ingest import ingest_path
from .orientation import build_orientation, render_orientation_markdown
from .program_inventory import (
    build_program_inventory,
    render_program_inventory_markdown,
    write_program_inventory,
)
from .retrieval import build_context_pack
from .store import NiklasStore


def parse_metadata_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("--metadata-json must decode to an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(prog="niklas")
    parser.add_argument("--db", help="Path to Niklas SQLite database")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest a file or directory")
    ingest.add_argument("path")
    ingest.add_argument("--project")
    ingest.add_argument("--tag", action="append", default=[])
    ingest.add_argument("--recursive", action="store_true")
    ingest.add_argument("--max-files", type=int)

    context = sub.add_parser("context", help="Build a context pack")
    context.add_argument("question")
    context.add_argument("--project")
    context.add_argument("--limit", type=int, default=8)

    orient = sub.add_parser("orient", help="Orient the current chat/session inside Niklas")
    orient.add_argument("request", nargs="?", help="Current user request or task signal")
    orient.add_argument("--goal", help="Current session goal")
    orient.add_argument("--project", help="Project hint or intended project scope")
    orient.add_argument("--cwd", help="Current working directory to use as a routing signal")
    orient.add_argument("--browser-url", help="Visible browser URL to use as a routing signal")
    orient.add_argument("--chat-summary", help="Short summary of the visible chat so far")
    orient.add_argument("--surface", help="Primary work surface: repo, Linear, browser, notes, CLI, MCP, or chat")
    orient.add_argument("--limit", type=int, default=5)
    orient.add_argument("--format", choices=["json", "markdown"], default="json")

    sub.add_parser("status", help="Show graph status")

    locate = sub.add_parser("locate", help="Resolve a source asset to its current path")
    locate.add_argument("identifier", help="Source asset id, node id, or current path")
    locate.add_argument("--events", type=int, default=10, help="Number of recent path events to return")

    sync = sub.add_parser("sync", help="Verify and repair source asset locations")
    sync_sub = sync.add_subparsers(dest="sync_command", required=True)
    sync_once = sync_sub.add_parser("once", help="Run one source asset sync pass")
    sync_watch = sync_sub.add_parser("watch", help="Continuously sync source asset locations")
    for sync_parser in (sync_once, sync_watch):
        sync_parser.add_argument("--root-id", help="Only sync assets under this source root")
        sync_parser.add_argument("--limit", type=int, help="Maximum number of assets to check")
        sync_parser.add_argument("--scan-depth", type=int, default=1, help="Bounded nearby scan depth for missing paths")
        sync_parser.add_argument(
            "--max-candidates",
            type=int,
            default=500,
            help="Maximum files to inspect per nearby scan",
        )
        sync_parser.add_argument(
            "--record-verified",
            action="store_true",
            help="Append verified events for unchanged available assets",
        )
        sync_parser.add_argument(
            "--verify-existing-hashes",
            action="store_true",
            help="Hash available files too; expensive for large media assets",
        )
    sync_watch.add_argument("--interval", type=float, default=30.0, help="Seconds between sync passes")
    sync_watch.add_argument("--iterations", type=int, help="Stop after this many passes")

    dupes = sub.add_parser("duplicates", help="Find duplicate files")
    dupes.add_argument("--project")
    dupes.add_argument("--limit", type=int, default=50)

    relation = sub.add_parser("relation", help="Create and inspect first-class relation nodes")
    relation_sub = relation.add_subparsers(dest="relation_command", required=True)

    relation_create = relation_sub.add_parser("create", help="Create a metadata-rich relation node")
    relation_create.add_argument("source_id")
    relation_create.add_argument("target_id")
    relation_create.add_argument("--type", dest="relation_type", required=True)
    relation_create.add_argument("--direction", default="A->B")
    relation_create.add_argument("--confidence", type=float, default=0.5)
    relation_create.add_argument("--authority")
    relation_create.add_argument("--original-type")
    relation_create.add_argument("--rationale")
    relation_create.add_argument("--evidence", action="append", default=[])
    relation_create.add_argument("--review-state", default="proposed")
    relation_create.add_argument("--run-id", dest="provenance_run_id")
    relation_create.add_argument("--scope", dest="provenance_scope")
    relation_create.add_argument("--metadata-json")

    relation_meta = relation_sub.add_parser("meta", help="Create a semantic link between two relation nodes")
    relation_meta.add_argument("source_relation_id")
    relation_meta.add_argument("target_relation_id")
    relation_meta.add_argument("--type", dest="meta_relation_type", required=True)
    relation_meta.add_argument("--confidence", type=float, default=0.5)
    relation_meta.add_argument("--rationale")
    relation_meta.add_argument("--evidence", action="append", default=[])
    relation_meta.add_argument("--run-id", dest="provenance_run_id")
    relation_meta.add_argument("--metadata-json")

    relation_show = relation_sub.add_parser("show", help="Show one relation node and its local links")
    relation_show.add_argument("relation_id")
    relation_show.add_argument("--limit", type=int, default=25)

    relation_list = relation_sub.add_parser("list", help="List relation nodes")
    relation_list.add_argument("--type", dest="relation_type")
    relation_list.add_argument("--review-state")
    relation_list.add_argument("--limit", type=int, default=50)

    cli_maker = sub.add_parser("cli-maker", help="Discover modular CLI candidates from Niklas sources")
    cli_maker.add_argument("roots", nargs="*", help="Optional roots to scan. Defaults to core Niklas source roots.")
    cli_maker.add_argument("--include-strada", action="store_true", help="Also scan shallow StradaConnect project roots if mounted.")
    cli_maker.add_argument("--max-files", type=int, default=500)
    cli_maker.add_argument("--max-depth", type=int, default=5)
    cli_maker.add_argument("--format", choices=["json", "markdown"], default="json")
    cli_maker.add_argument("--write", help="Write the catalog to a file as well as printing it.")
    cli_maker.add_argument("--quiet", action="store_true", help="Do not print the catalog when --write is used.")

    programs = sub.add_parser("programs", help="Inventory prior programs and code surfaces")
    programs.add_argument("roots", nargs="*", help="Optional roots to scan. Defaults to current PROJECTS and Niklas roots.")
    programs.add_argument("--include-strada", action="store_true", help="Also scan StradaConnect project roots if mounted.")
    programs.add_argument(
        "--include-master-archives",
        action="store_true",
        help="Also scan bounded Master 140 archive code roots.",
    )
    programs.add_argument("--max-files", type=int, default=1500)
    programs.add_argument("--max-depth", type=int, default=6)
    programs.add_argument("--format", choices=["json", "markdown"], default="json")
    programs.add_argument("--write", help="Write the inventory to a file as well as printing it.")
    programs.add_argument("--quiet", action="store_true", help="Do not print the inventory when --write is used.")

    args = parser.parse_args()

    if args.command == "ingest":
        out = ingest_path(
            args.path,
            project_scope=args.project,
            tags=args.tag,
            recursive=args.recursive,
            db_path=args.db,
            max_files=args.max_files,
        )
    elif args.command == "context":
        out = build_context_pack(
            args.question,
            project_scope=args.project,
            limit=args.limit,
            db_path=args.db,
        )
    elif args.command == "orient":
        out = build_orientation(
            current_request=args.request,
            current_goal=args.goal,
            project_hint=args.project,
            cwd=args.cwd,
            browser_url=args.browser_url,
            chat_summary=args.chat_summary,
            surface=args.surface,
            limit=args.limit,
            db_path=args.db,
        )
    elif args.command == "duplicates":
        out = NiklasStore(args.db).find_duplicates(project_scope=args.project, limit=args.limit)
    elif args.command == "status":
        out = NiklasStore(args.db).status()
    elif args.command == "locate":
        out = NiklasStore(args.db).locate_source_asset(args.identifier, event_limit=args.events)
        if out is None:
            out = {
                "identifier": args.identifier,
                "status": "not-found",
                "current_path": None,
                "events": [],
            }
    elif args.command == "sync":
        store = NiklasStore(args.db)
        if args.sync_command == "once":
            out = store.sync_source_assets_once(
                root_id=args.root_id,
                limit=args.limit,
                scan_depth=args.scan_depth,
                max_candidates=args.max_candidates,
                verify_existing_hashes=args.verify_existing_hashes,
                record_verified=args.record_verified,
            )
        elif args.sync_command == "watch":
            iteration = 0
            try:
                while args.iterations is None or iteration < args.iterations:
                    iteration += 1
                    out = store.sync_source_assets_once(
                        root_id=args.root_id,
                        limit=args.limit,
                        scan_depth=args.scan_depth,
                        max_candidates=args.max_candidates,
                        verify_existing_hashes=args.verify_existing_hashes,
                        record_verified=args.record_verified,
                    )
                    out["iteration"] = iteration
                    print(json.dumps(out), flush=True)
                    if args.iterations is not None and iteration >= args.iterations:
                        return
                    time.sleep(max(args.interval, 1.0))
            except KeyboardInterrupt:
                return
        else:
            raise SystemExit(f"unknown sync command: {args.sync_command}")
    elif args.command == "relation":
        store = NiklasStore(args.db)
        if args.relation_command == "create":
            out = store.upsert_relation_node(
                source_id=args.source_id,
                target_id=args.target_id,
                relation_type=args.relation_type,
                direction=args.direction,
                confidence=args.confidence,
                authority=args.authority,
                original_type=args.original_type,
                rationale=args.rationale,
                evidence_spans=args.evidence,
                review_state=args.review_state,
                provenance_run_id=args.provenance_run_id,
                provenance_scope=args.provenance_scope,
                metadata=parse_metadata_json(args.metadata_json),
            )
        elif args.relation_command == "meta":
            out = store.upsert_meta_relation(
                source_relation_id=args.source_relation_id,
                target_relation_id=args.target_relation_id,
                meta_relation_type=args.meta_relation_type,
                confidence=args.confidence,
                rationale=args.rationale,
                evidence_spans=args.evidence,
                provenance_run_id=args.provenance_run_id,
                metadata=parse_metadata_json(args.metadata_json),
            )
        elif args.relation_command == "show":
            node = store.get_node(args.relation_id)
            out = {
                "node": node,
                "relationships": store.get_relationships_for_nodes([args.relation_id], limit=args.limit),
            }
        elif args.relation_command == "list":
            out = store.list_relation_nodes(
                relation_type=args.relation_type,
                review_state=args.review_state,
                limit=args.limit,
            )
        else:
            raise SystemExit(f"unknown relation command: {args.relation_command}")
    elif args.command == "cli-maker":
        out = build_cli_catalog(
            args.roots or None,
            include_strada=args.include_strada,
            max_files=args.max_files,
            max_depth=args.max_depth,
        )
        if args.write:
            write_catalog(out, args.write, markdown=args.format == "markdown")
        if args.quiet:
            return
    elif args.command == "programs":
        out = build_program_inventory(
            args.roots or None,
            include_strada=args.include_strada,
            include_master_archives=args.include_master_archives,
            max_files=args.max_files,
            max_depth=args.max_depth,
        )
        if args.write:
            write_program_inventory(out, args.write, markdown=args.format == "markdown")
        if args.quiet:
            return
    else:
        raise SystemExit(f"unknown command: {args.command}")

    if args.command == "orient" and args.format == "markdown":
        print(render_orientation_markdown(out), end="")
    elif getattr(args, "format", "json") == "markdown":
        if args.command == "programs":
            print(render_program_inventory_markdown(out))
        else:
            print(render_markdown_catalog(out))
    else:
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
