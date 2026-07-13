from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from niklas.cli_factory import build_cli_catalog, default_roots, render_markdown_catalog
from niklas.ingest import ingest_path
from niklas.orientation import build_orientation, render_orientation_markdown
from niklas.program_inventory import build_program_inventory, render_program_inventory_markdown
from niklas.retrieval import build_context_pack
from niklas.store import NiklasStore


def test_ingest_markdown_and_asset_then_build_context(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    note = project / "decision.md"
    note.write_text(
        "---\ntitle: Camera Workflow Decision\ntags: [camera, workflow]\n---\n"
        "# Camera Workflow Decision\n\n"
        "Use proxy ingest before color review. Related to [[Color Review Process]].\n",
        encoding="utf-8",
    )
    asset = project / "look.cube"
    asset.write_bytes(b"LUTDATA")

    db_path = tmp_path / "niklas.sqlite"
    result = ingest_path(project, project_scope="HML", recursive=True, db_path=db_path)

    assert result["files_seen"] == 2
    assert result["files_ingested"] == 2

    status = NiklasStore(db_path).status()
    assert status["node_count"] >= 5
    assert status["nodes_by_type"]["Note"] >= 2
    assert status["nodes_by_type"]["Asset"] == 1

    pack = build_context_pack("camera proxy workflow", project_scope="HML", db_path=db_path)
    titles = {node["title"] for node in pack["nodes"]}
    assert "Camera Workflow Decision" in titles
    assert any(rel["type"] == "references" for rel in pack["relationships"])


def test_duplicate_detection_uses_content_hash(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    body = "---\ntitle: Same\n---\n\nSame body.\n"
    (project / "one.md").write_text(body, encoding="utf-8")
    (project / "two.md").write_text(body, encoding="utf-8")

    db_path = tmp_path / "niklas.sqlite"
    ingest_path(project, project_scope="Dupes", recursive=True, db_path=db_path)

    duplicates = NiklasStore(db_path).find_duplicates(project_scope="Dupes")
    assert len(duplicates) == 1
    assert duplicates[0]["kind"] == "exact-content-hash"
    assert duplicates[0]["count"] == 2


def test_source_asset_reuses_node_after_move(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    original = project / "master.md"
    original.write_text(
        "---\ntitle: Original Master File\ntags: [resolver]\n---\n"
        "# Original Master File\n\n"
        "Find the current master file location after a move.\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "niklas.sqlite"

    ingest_path(project, project_scope="Resolver", recursive=True, db_path=db_path)
    store = NiklasStore(db_path)
    first = store.locate_source_asset(str(original))
    assert first is not None
    asset_id = first["asset_id"]
    node_id = first["node_id"]

    moved = project / "renamed-master.md"
    original.rename(moved)
    ingest_path(project, project_scope="Resolver", recursive=True, db_path=db_path)

    located = store.locate_source_asset(asset_id)
    assert located is not None
    assert located["asset_id"] == asset_id
    assert located["node_id"] == node_id
    assert located["current_path"] == str(moved.resolve(strict=False))
    assert any(event["event_type"] == "moved" for event in located["events"])

    node = store.get_node(node_id)
    assert node is not None
    assert node["absolute_path"] == str(moved.resolve(strict=False))
    assert node["metadata"]["source_asset_id"] == asset_id

    pack = build_context_pack("current master file location", project_scope="Resolver", db_path=db_path)
    hit = next(node for node in pack["nodes"] if node["id"] == node_id)
    assert hit["absolute_path"] == str(moved.resolve(strict=False))


def test_source_asset_sync_once_detects_move_without_reingest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    original = project / "master.md"
    original.write_text("# Master\n\nSync should find this after rename.\n", encoding="utf-8")
    db_path = tmp_path / "niklas.sqlite"

    ingest_path(original, project_scope="Resolver", db_path=db_path)
    store = NiklasStore(db_path)
    first = store.locate_source_asset(str(original))
    assert first is not None

    moved = project / "renamed-master.md"
    original.rename(moved)
    sync = store.sync_source_assets_once(scan_depth=1, max_candidates=50)

    assert sync["assets_checked"] == 1
    assert sync["moved"] == 1
    located = store.locate_source_asset(first["asset_id"])
    assert located is not None
    assert located["asset_id"] == first["asset_id"]
    assert located["node_id"] == first["node_id"]
    assert located["current_path"] == str(moved.resolve(strict=False))
    assert any(event["event_type"] == "moved" for event in located["events"])

    node = store.get_node(first["node_id"])
    assert node is not None
    assert node["absolute_path"] == str(moved.resolve(strict=False))


def test_source_asset_copy_candidate_keeps_distinct_asset(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    original = project / "master.md"
    original.write_text("# Master\n\nSame bytes stay in the original.\n", encoding="utf-8")
    copy = project / "master-copy.md"
    db_path = tmp_path / "niklas.sqlite"

    ingest_path(original, project_scope="Resolver", db_path=db_path)
    shutil.copy2(original, copy)
    ingest_path(copy, project_scope="Resolver", db_path=db_path)

    store = NiklasStore(db_path)
    original_asset = store.locate_source_asset(str(original))
    copy_asset = store.locate_source_asset(str(copy))

    assert original_asset is not None
    assert copy_asset is not None
    assert original_asset["asset_id"] != copy_asset["asset_id"]
    assert original_asset["node_id"] != copy_asset["node_id"]
    assert any(event["event_type"] == "copy-candidate" for event in copy_asset["events"])


def test_locate_falls_back_to_strada_alias_when_local_root_missing(tmp_path: Path) -> None:
    local_root = tmp_path / "MASTER 140 TB 1"
    strada_root = tmp_path / "StradaConnect" / "Erich-M4-Max" / "MASTER 140 TB 1"
    relative = Path("2026") / "06-2026 FILMS Jimmy Chin" / "master.md"
    local_file = local_root / relative
    strada_file = strada_root / relative
    local_file.parent.mkdir(parents=True)
    local_file.write_text("# Master\n\nResolve this through Strada.\n", encoding="utf-8")
    db_path = tmp_path / "niklas.sqlite"
    store = NiklasStore(db_path)
    store.register_source_root_alias(
        root_id="master-140-test",
        base_path=str(local_root),
        alias_kind="local",
        priority=10,
    )
    store.register_source_root_alias(
        root_id="master-140-test",
        base_path=str(strada_root),
        alias_kind="strada-connect",
        priority=20,
    )

    ingest_path(local_file, project_scope="Resolver", db_path=db_path)
    first = store.locate_source_asset(str(local_file))
    assert first is not None
    assert first["root_id"] == "master-140-test"
    assert first["relative_path"] == str(relative)

    strada_file.parent.mkdir(parents=True)
    shutil.copy2(local_file, strada_file)
    shutil.rmtree(local_root)

    located = store.locate_source_asset(first["asset_id"])
    assert located is not None
    assert located["resolution_status"] == "strada-available"
    assert located["preferred_uri"] == str(strada_file.resolve(strict=False))
    assert located["local_path"] is None
    assert located["strada_path"] == str(strada_file.resolve(strict=False))
    assert any(step["step"] == "strada-connect-alias" and step["status"] == "available" for step in located["lookup_steps"])


def test_sync_once_updates_asset_to_strada_alias_when_local_root_missing(tmp_path: Path) -> None:
    local_root = tmp_path / "MASTER 140 TB 1"
    strada_root = tmp_path / "StradaConnect" / "Erich-M4-Max" / "MASTER 140 TB 1"
    relative = Path("2026") / "06-2026 FILMS Jimmy Chin" / "master.md"
    local_file = local_root / relative
    strada_file = strada_root / relative
    local_file.parent.mkdir(parents=True)
    local_file.write_text("# Master\n\nSync this through Strada.\n", encoding="utf-8")
    db_path = tmp_path / "niklas.sqlite"
    store = NiklasStore(db_path)
    store.register_source_root_alias(
        root_id="master-140-test",
        base_path=str(local_root),
        alias_kind="local",
        priority=10,
    )
    store.register_source_root_alias(
        root_id="master-140-test",
        base_path=str(strada_root),
        alias_kind="strada-connect",
        priority=20,
    )

    ingest_path(local_file, project_scope="Resolver", db_path=db_path)
    first = store.locate_source_asset(str(local_file))
    assert first is not None
    strada_file.parent.mkdir(parents=True)
    shutil.copy2(local_file, strada_file)
    shutil.rmtree(local_root)

    sync = store.sync_source_assets_once(root_id="master-140-test", scan_depth=1, max_candidates=50)
    assert sync["moved"] == 1
    located = store.locate_source_asset(first["asset_id"])
    assert located is not None
    assert located["current_path"] == str(strada_file.resolve(strict=False))
    assert located["resolution_status"] == "local-available"
    assert any(event["event_type"] == "moved" for event in located["events"])


def test_locate_cli_resolves_source_asset_by_asset_and_node(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "clip-note.md"
    source.write_text("# Clip Note\n\nCLI locate should resolve this file.\n", encoding="utf-8")
    db_path = tmp_path / "niklas.sqlite"
    ingest_path(source, project_scope="Resolver", db_path=db_path)

    store = NiklasStore(db_path)
    located = store.locate_source_asset(str(source))
    assert located is not None
    resources_root = Path(__file__).resolve().parents[2]

    by_asset = subprocess.run(
        [
            sys.executable,
            "-m",
            "niklas.cli",
            "--db",
            str(db_path),
            "locate",
            located["asset_id"],
        ],
        cwd=resources_root,
        check=True,
        capture_output=True,
        text=True,
    )
    by_node = subprocess.run(
        [
            sys.executable,
            "-m",
            "niklas.cli",
            "--db",
            str(db_path),
            "locate",
            located["node_id"],
        ],
        cwd=resources_root,
        check=True,
        capture_output=True,
        text=True,
    )

    asset_payload = json.loads(by_asset.stdout)
    node_payload = json.loads(by_node.stdout)
    assert asset_payload["asset_id"] == located["asset_id"]
    assert node_payload["asset_id"] == located["asset_id"]
    assert asset_payload["current_path"] == str(source.resolve(strict=False))
    assert node_payload["current_path"] == str(source.resolve(strict=False))


def test_sync_cli_once_repairs_moved_asset(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "clip-note.md"
    source.write_text("# Clip Note\n\nCLI sync should repair this file.\n", encoding="utf-8")
    db_path = tmp_path / "niklas.sqlite"
    ingest_path(source, project_scope="Resolver", db_path=db_path)

    store = NiklasStore(db_path)
    located = store.locate_source_asset(str(source))
    assert located is not None
    moved = project / "clip-note-renamed.md"
    source.rename(moved)
    resources_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "niklas.cli",
            "--db",
            str(db_path),
            "sync",
            "once",
            "--scan-depth",
            "1",
            "--max-candidates",
            "50",
        ],
        cwd=resources_root,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["moved"] == 1
    repaired = store.locate_source_asset(located["asset_id"])
    assert repaired is not None
    assert repaired["current_path"] == str(moved.resolve(strict=False))


def test_relation_nodes_support_edge_to_edge_metadata(tmp_path: Path) -> None:
    store = NiklasStore(tmp_path / "relations.sqlite")
    store.initialize()
    store.upsert_node(node_id="note:a", node_type="Note", title="A")
    store.upsert_node(node_id="note:b", node_type="Note", title="B")
    store.upsert_node(node_id="note:c", node_type="Note", title="C")

    first = store.upsert_relation_node(
        source_id="note:a",
        target_id="note:b",
        relation_type="derives-from",
        direction="A->B",
        confidence=0.9,
        rationale="A depends on B.",
        evidence_spans=["A depends on B"],
        review_state="reviewed",
        provenance_run_id="test-run",
        provenance_scope="unit-test",
    )
    second = store.upsert_relation_node(
        source_id="note:b",
        target_id="note:c",
        relation_type="references",
        direction="A->B",
        confidence=0.7,
        rationale="B cites C.",
        evidence_spans=["B cites C"],
        provenance_run_id="test-run",
        provenance_scope="unit-test",
    )
    meta = store.upsert_meta_relation(
        source_relation_id=first["relation_node"]["id"],
        target_relation_id=second["relation_node"]["id"],
        meta_relation_type="supports",
        confidence=0.8,
        rationale="The first claim is reinforced by the second.",
        evidence_spans=["reinforced"],
        provenance_run_id="test-run",
    )

    relation_node = store.get_node(first["relation_node"]["id"])
    assert relation_node is not None
    assert relation_node["type"] == "Relationship"
    assert relation_node["metadata"]["record_kind"] == "node"
    assert relation_node["metadata"]["relation_type"] == "derives-from"
    assert relation_node["metadata"]["confidence"] == 0.9
    assert relation_node["metadata"]["review_state"] == "reviewed"

    relationships = store.get_relationships_for_nodes(
        ["note:a", first["relation_node"]["id"], second["relation_node"]["id"]],
        limit=20,
    )
    rel_types = {rel["type"] for rel in relationships}
    assert "relation-source" in rel_types
    assert "relation-target" in rel_types
    assert "relation-supports" in rel_types
    assert meta["metadata_json"]


def test_relation_cli_creates_metadata_rich_relation(tmp_path: Path) -> None:
    db_path = tmp_path / "relations-cli.sqlite"
    store = NiklasStore(db_path)
    store.initialize()
    store.upsert_node(node_id="note:a", node_type="Note", title="A")
    store.upsert_node(node_id="note:b", node_type="Note", title="B")

    resources_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "niklas.cli",
            "--db",
            str(db_path),
            "relation",
            "create",
            "note:a",
            "note:b",
            "--type",
            "derives-from",
            "--confidence",
            "0.91",
            "--rationale",
            "A depends on B.",
            "--evidence",
            "A depends on B",
            "--run-id",
            "cli-test-run",
            "--scope",
            "cli-test",
        ],
        cwd=resources_root,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    relation_id = payload["relation_node"]["id"]

    show = subprocess.run(
        [
            sys.executable,
            "-m",
            "niklas.cli",
            "--db",
            str(db_path),
            "relation",
            "show",
            relation_id,
        ],
        cwd=resources_root,
        check=True,
        capture_output=True,
        text=True,
    )
    shown = json.loads(show.stdout)

    assert shown["node"]["metadata"]["record_kind"] == "node"
    assert shown["node"]["metadata"]["relation_type"] == "derives-from"
    assert shown["node"]["metadata"]["provenance_run_id"] == "cli-test-run"
    assert {rel["type"] for rel in shown["relationships"]} == {"relation-source", "relation-target"}


def test_cli_store_status_empty_db(tmp_path: Path) -> None:
    status = NiklasStore(tmp_path / "empty.sqlite").status()
    assert status["db_exists"] is False
    assert status["schema_present"] is False
    assert status["node_count"] == 0
    assert status["relationship_count"] == 0


def test_read_paths_do_not_create_missing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.sqlite"
    store = NiklasStore(db_path)

    assert store.get_node("note:missing") is None
    assert store.search_nodes("anything") == []
    assert store.find_duplicates() == []
    assert store.get_relationships_for_nodes(["note:missing"]) == []
    assert not db_path.exists()


def test_orientation_returns_questions_when_session_lacks_landscape(tmp_path: Path) -> None:
    orientation = build_orientation(db_path=tmp_path / "missing.sqlite")

    assert orientation["orientation_version"] == "niklas-orient-v1"
    assert orientation["position"]["state"] == "needs_questions"
    assert orientation["position"]["recommended_next_tool"] == "ask_user"
    question_ids = {question["id"] for question in orientation["questions"]}
    assert {"project", "goal", "task"}.issubset(question_ids)
    assert not (tmp_path / "missing.sqlite").exists()


def test_orientation_positions_session_with_project_and_goal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "mcp.md").write_text(
        "---\ntitle: Niklas MCP Install\n---\n"
        "# Niklas MCP Install\n\n"
        "Codex plugin install and read-only MCP orientation workflow.\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "niklas.sqlite"
    ingest_path(project, project_scope="Niklas", recursive=True, db_path=db_path)

    orientation = build_orientation(
        current_request="Add first-use orientation to the MCP",
        current_goal="Install and verify the Niklas Codex plugin",
        project_hint="Niklas",
        cwd="/Users/erichroepke/Desktop/PROJECTS/NIKLAS-BUILDER",
        db_path=db_path,
    )

    assert orientation["position"]["state"] == "positioned"
    assert orientation["position"]["project_scope"] == "Niklas"
    assert orientation["position"]["recommended_next_tool"] == "niklas_context_pack"
    assert orientation["candidates"]
    markdown = render_orientation_markdown(orientation)
    assert "Niklas Orientation" in markdown
    assert "Niklas MCP Install" in markdown


def test_orientation_cli_outputs_positioning_packet(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "guide.md").write_text(
        "---\ntitle: Orientation Guide\n---\n# Orientation Guide\n\nProject routing questions.\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "niklas.sqlite"
    ingest_path(project, project_scope="Niklas", recursive=True, db_path=db_path)
    resources_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "niklas.cli",
            "--db",
            str(db_path),
            "orient",
            "Need a starting point",
            "--project",
            "Niklas",
            "--goal",
            "Route the session",
        ],
        cwd=resources_root,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["orientation_version"] == "niklas-orient-v1"
    assert payload["position"]["project_scope"] == "Niklas"


def test_cli_maker_discovers_modular_video_archive_candidates(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    root.mkdir()
    (root / "hml-sync.md").write_text(
        "# HML video ingest\n\n"
        "Build a footage archive manifest, register the vault, map proxy clips, "
        "validate Tentacle timecode and lav sync, then create a handoff.\n",
        encoding="utf-8",
    )
    (root / "bert.md").write_text(
        "# BERT staged process\n\n"
        "Run setup, goal, experts, research, blueprint, moonshot, pressure test, and handoff.\n",
        encoding="utf-8",
    )

    catalog = build_cli_catalog([root], max_files=20)
    domains = {candidate["domain"] for candidate in catalog["candidates"]}

    assert "video-ingest" in domains
    assert "archive-inventory" in domains
    assert "audio-sync" in domains
    assert "bert-stage-runner" in domains
    assert any(combo["id"] == "hml-video-ingest-stack" for combo in catalog["combinations"])


def test_cli_maker_markdown_renders_nested_commands(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    root.mkdir()
    (root / "runtime.md").write_text(
        "# Runtime doctor\n\n"
        "Verify MCP status, LaunchAgent plist health, SQLite graph status, and CLI JSON output.\n",
        encoding="utf-8",
    )

    catalog = build_cli_catalog([root], max_files=20)
    markdown = render_markdown_catalog(catalog)

    assert "Niklas CLI Maker Catalog" in markdown
    assert "Runtime Doctor" in markdown
    assert "niklas doctor status" in markdown


def test_cli_maker_default_roots_walk_up_to_niklas_root(tmp_path: Path) -> None:
    niklas_root = tmp_path / "Niklas"
    nested = niklas_root / "03-Runtime" / "Cornelius" / "resources"
    (niklas_root / "01-Brain" / "wiki" / "Projects").mkdir(parents=True)
    (niklas_root / "04-Source-Registry").mkdir()
    nested.mkdir(parents=True)

    roots = default_roots(nested)

    assert niklas_root / "01-Brain/wiki/Projects" in roots
    assert niklas_root / "04-Source-Registry" in roots
    assert all(str(root).startswith(str(niklas_root)) for root in roots)


def test_program_inventory_detects_prior_program_cli_markers(tmp_path: Path) -> None:
    project = tmp_path / "PROJECTS" / "ZEUS-TOOLS" / "figma-cli"
    project.mkdir(parents=True)
    (project / "package.json").write_text(
        '{"name":"figma-cli","bin":{"figma-cli":"./bin/figma.js"},"scripts":{"build":"tsc","test":"vitest"}}',
        encoding="utf-8",
    )
    (project / "README.md").write_text("# Figma CLI\n\nExport design data.\n", encoding="utf-8")

    inventory = build_program_inventory([tmp_path / "PROJECTS"], max_files=20)
    programs = {program["name"]: program for program in inventory["programs"]}

    assert "figma-cli" in programs
    assert programs["figma-cli"]["family"] == "ZEUS-TOOLS"
    assert "node-bin:figma-cli" in programs["figma-cli"]["cli_entrypoints"]
    assert "niklas program cli shim <path>" in programs["figma-cli"]["cli_routes"]


def test_program_inventory_markdown_groups_worktrees(tmp_path: Path) -> None:
    project = tmp_path / "PROJECTS" / "ARC" / "worktrees" / "arc-123-test"
    project.mkdir(parents=True)
    (project / "package.json").write_text('{"name":"arc-test","scripts":{"dev":"next dev"}}', encoding="utf-8")
    (project / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")

    inventory = build_program_inventory([tmp_path / "PROJECTS"], max_files=20)
    markdown = render_program_inventory_markdown(inventory)

    assert "Niklas Prior Program Inventory" in markdown
    assert "ARC" in markdown
    assert "worktree" in markdown
    assert "niklas arc worktree audit <path>" in markdown
