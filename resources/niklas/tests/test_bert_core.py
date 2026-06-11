from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from niklas.bert_cli import main as bert_cli_main
from niklas.bert_core import (
    EXPECTED_MCP_TOOLS,
    BertEnvironment,
    build_bert_on_payload,
    build_node_create_payload,
    build_node_locate_payload,
    build_node_map_payload,
    build_node_spawn_children_payload,
    build_node_stages_payload,
    build_node_start_payload,
    build_node_template_payload,
    build_linear_snapshot,
    build_mcp_payload,
    build_project_analyze_payload,
    build_project_create_payload,
    build_project_init_payload,
    build_project_open_payload,
    build_readiness_payload,
    build_stage_dry_run,
)
from niklas.store import NiklasStore


def make_env(tmp_path: Path) -> BertEnvironment:
    niklas_root = tmp_path / "Niklas"
    runtime_root = niklas_root / "03-Runtime" / "Cornelius"
    builder_root = tmp_path / "PROJECTS" / "NIKLAS-BUILDER"
    bert_root = builder_root / "BERT"
    env = BertEnvironment(
        home=tmp_path,
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

    for directory in [
        env.niklas_root,
        env.runtime_root,
        env.builder_root,
        env.bert_root,
        env.bert_mvp,
        env.skill_pack,
        env.linear_buildout,
        env.legacy_builder_cli.parent,
        env.mcp_server.parent,
        env.db_path.parent,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    env.canonical_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    env.niklas_cli.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    env.legacy_builder_cli.write_text(
        "#!/usr/bin/env bash\nprintf '{\"readiness\":\"test\"}'\n",
        encoding="utf-8",
    )
    env.legacy_builder_cli.chmod(0o755)
    env.mcp_server.write_text(
        "\n".join(f"async def {tool}(): pass" for tool in EXPECTED_MCP_TOOLS),
        encoding="utf-8",
    )

    for path in env.first_read:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.name == ".linear-config":
            path.write_text(
                "team: ERI\n"
                "root_initiative: BERT\n"
                "initiative: BERT GMVP\n"
                "runtime_linear_operations_initiative: BERT Runtime / Linear Operations\n",
                encoding="utf-8",
            )
        else:
            path.write_text("# Test\n", encoding="utf-8")
    return env


def test_readiness_payload_uses_temp_roots_and_dry_run_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LINEAR_ACCESS_TOKEN", raising=False)
    env = make_env(tmp_path)

    payload = build_readiness_payload(env)

    assert payload["mode"] == "read_only_dry_run"
    assert payload["write_enabled"] is False
    assert payload["linear"]["linear_api"] == "session_managed"
    assert payload["niklas"]["mcp"]["source_installed"] is True
    assert payload["failures"] == []
    assert any(stage["command"] == "setup" for stage in payload["stages"])


def test_stage_dry_run_never_enables_writes(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    payload = build_stage_dry_run(
        "setup",
        "pilot-ready BERT CLI/MCP",
        parent="BERT Runtime Adapter Contract",
        linear_anchor="ERI-2415",
        env=env,
    )

    assert payload["stage"]["name"] == "0_BERT: PROJECT SETUP"
    assert payload["node"] == "pilot-ready BERT CLI/MCP"
    assert payload["parent"] == "BERT Runtime Adapter Contract"
    assert payload["linear_anchor"] == "ERI-2415"
    assert payload["write_enabled"] is False
    assert {item["surface"] for item in payload["blocked_writes"]} == {
        "Linear",
        "Niklas graph",
        "local BERT Markdown",
    }


def test_linear_snapshot_is_session_managed_even_with_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 2026-06-11: the engine never calls the Linear API — even when a
    LINEAR_ACCESS_TOKEN is present in the environment."""
    monkeypatch.setenv("LINEAR_ACCESS_TOKEN", "should-never-be-used")
    env = make_env(tmp_path)

    payload = build_linear_snapshot(env)

    assert payload["linear_api"] == "session_managed"
    assert payload["local_config"]["values"]["root_initiative"] == "BERT"
    assert payload["session_snapshot"] is None


def test_linear_snapshot_reads_session_written_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The session queries Linear via its own MCP and persists a local snapshot
    file; build_linear_snapshot surfaces it without touching the API."""
    monkeypatch.delenv("LINEAR_ACCESS_TOKEN", raising=False)
    env = make_env(tmp_path)
    (env.bert_mvp / ".linear-snapshot.json").write_text(
        '{"initiative": {"id": "abc", "name": "BERT GMVP"}}', encoding="utf-8"
    )

    payload = build_linear_snapshot(env)

    assert payload["linear_api"] == "session_managed"
    assert payload["session_snapshot"]["initiative"]["name"] == "BERT GMVP"


def test_mcp_payload_reports_expected_bert_tools(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    payload = build_mcp_payload(env)

    assert payload["source_installed"] is True
    assert payload["daemon_reload_needed"] in (True, False, None)
    assert "daemon_reload_reason" in payload
    assert set(payload["expected_tools"]) == set(EXPECTED_MCP_TOOLS)


def test_project_create_apply_builds_l1m1_with_ingest(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    payload = build_project_create_payload("My BERT Project", apply=True, env=env)
    project_dir = Path(payload["project_dir"])

    assert payload["write_enabled"] is True
    assert payload["hierarchy_contract"]["local_tree"] == ".BERT/L1M1/L2M*/L3M*/..."
    assert payload["linear_mirror"]["root"]["default_linear_type"] == "Initiative"
    assert (project_dir / "PROJECT.md").exists()
    assert (project_dir / "LINEAR.md").exists()
    assert (project_dir / "NIKLAS.md").exists()
    assert (project_dir / "inbox" / "README.md").exists()
    assert (project_dir / "L1M1" / "_node.md").exists()
    assert (project_dir / "L1M1" / "MAP.md").exists()
    assert (project_dir / "L1M1" / "dev" / "0-ingest").is_dir()
    assert (project_dir / "L1M1" / "dev" / "1-brainstorm").is_dir()
    assert "forward-facing final\nartifact" in (project_dir / "PROJECT.md").read_text(encoding="utf-8")
    assert "`L1M1` -> Linear Initiative" in (project_dir / "LINEAR.md").read_text(encoding="utf-8")
    root_map = (project_dir / "L1M1" / "MAP.md").read_text(encoding="utf-8")
    assert "Highest-Level Necessary Steps" in root_map
    assert "Child node: `L2M1`" in root_map


def test_node_create_apply_omits_ingest_for_child_nodes(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    build_project_create_payload("My BERT Project", apply=True, env=env)

    payload = build_node_create_payload(
        "L2M1",
        project="my-bert-project",
        apply=True,
        env=env,
    )
    node_dir = Path(payload["project_dir"]) / "L1M1" / "L2M1"

    assert payload["node_path"] == "L1M1/L2M1"
    assert payload["linear_mirror"]["default_linear_type"] == "Sub-initiative"
    assert (node_dir / "_node.md").exists()
    assert not (node_dir / "dev" / "0-ingest").exists()
    assert (node_dir / "dev" / "1-brainstorm").is_dir()
    assert (node_dir / "dev" / "7-map").is_dir()
    node_doc = (node_dir / "_node.md").read_text(encoding="utf-8")
    node_map = (node_dir / "MAP.md").read_text(encoding="utf-8")
    assert "Recursive MAP Contract" in node_doc
    assert "Default Linear type: Sub-initiative" in node_doc
    assert "Child node: `L3M1`" in node_map


def test_node_template_exposes_recursive_map_contract(tmp_path: Path) -> None:
    make_env(tmp_path)

    payload = build_node_template_payload("L1M1/L2M1")

    assert payload["map_contract"]["final_artifact"] == "MAP.md"
    assert payload["hierarchy_contract"]["source_of_truth"] == "local_bert_packet"
    assert payload["linear_mirror"]["default_linear_type"] == "Sub-initiative"
    assert "highest-level necessary steps" in payload["map_contract"]["purpose"]
    assert payload["map_contract"]["recursion_rule"] == "Numbered MAP steps can become L3M* child nodes."


def test_project_init_creates_hidden_bert_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_env(tmp_path)
    monkeypatch.delenv("LINEAR_ACCESS_TOKEN", raising=False)
    host = tmp_path / "Some Linear Project"
    host.mkdir()

    payload = build_project_init_payload(host, name="Some Linear Project", apply=True, env=env)
    workspace = host / ".BERT"

    assert payload["hidden_workspace"] is True
    assert Path(payload["bert_workspace_dir"]) == workspace
    assert (workspace / "PROJECT.md").exists()
    assert (workspace / "L1M1" / "dev" / "0-ingest").is_dir()

    opened = build_project_open_payload(str(host), env=env)
    assert opened["hidden_workspace"] is True
    assert opened["position"]["local_root_node"] == "L1M1"
    assert opened["hierarchy_contract"]["linear_role"] == "mirror_and_status_surface"
    assert opened["linear_mirror"]["root"]["default_linear_type"] == "Initiative"
    assert opened["position"]["hierarchy_source_of_truth"] == "local_bert_packet"
    assert opened["linear_lookup"]["query"] == "Some Linear Project"
    assert opened["linear_lookup"]["lookup_order"] == ["initiative", "project"]
    assert opened["linear_lookup"]["linear_api"] == "session_managed"
    assert opened["position"]["linear_anchor_lookup"] == "session_managed"
    assert opened["niklas_lookup"]["correlation_status"] == "blocked_db_missing"
    assert opened["position"]["niklas_correlation"] == "blocked_db_missing"
    assert opened["bert_process"]["state"] == "in_progress"
    assert opened["bert_process"]["current_node"] == "L1M1"
    assert opened["bert_process"]["current_stage"] == "0-ingest"


def test_project_init_writes_state_json(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "State Demo"
    host.mkdir()

    payload = build_project_init_payload(host, name="State Demo", apply=True, env=env)
    state_path = host / ".BERT" / "state.json"

    assert payload["already_initialized"] is False
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["schema"] == "bert-state-v2"
    assert state["stages"] == {"L1M1": {}}
    assert state["project_name"] == "State Demo"
    assert state["project_slug"] == "state-demo"
    assert state["host_project_dir"] == str(host)
    assert state["bert_workspace_dir"] == str(host / ".BERT")
    assert state["root_node"] == "L1M1"
    assert state["current_node"] == "L1M1"
    assert state["current_stage"] == "0-ingest"
    assert state["linear_anchor"] == "pending"
    assert state["niklas_anchor"] == "pending"
    assert state["initialized_at"]
    assert state["write_surfaces"]["linear"] == "blocked_until_apply_contract"


def test_resume_prefers_state_json(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "State Resume"
    host.mkdir()
    build_project_init_payload(host, name="State Resume", apply=True, env=env)
    state_path = host / ".BERT" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_stage"] = "1-brainstorm"
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    opened = build_project_open_payload(str(host), env=env)

    assert opened["bert_process"]["status_file"]["source"] == "state.json"
    assert opened["bert_process"]["current_node"] == "L1M1"
    assert opened["bert_process"]["current_stage"] == "1-brainstorm"


def test_resume_falls_back_to_status_md(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "Status Fallback"
    host.mkdir()
    build_project_init_payload(host, name="Status Fallback", apply=True, env=env)
    (host / ".BERT" / "state.json").unlink()

    opened = build_project_open_payload(str(host), env=env)

    assert opened["bert_process"]["status_file"]["source"] == "STATUS.md"
    assert opened["bert_process"]["current_node"] == "L1M1"
    assert opened["bert_process"]["current_stage"] == "0-ingest"


def test_project_init_reports_already_initialized(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "Twice Adopted"
    host.mkdir()
    first = build_project_init_payload(host, name="Twice Adopted", apply=True, env=env)
    map_path = host / ".BERT" / "L1M1" / "MAP.md"
    original_map = map_path.read_text(encoding="utf-8")

    second = build_project_init_payload(host, name="Twice Adopted", apply=True, env=env)

    assert first["already_initialized"] is False
    assert second["already_initialized"] is True
    assert second["applied"]["written_files"] == []
    assert len(second["applied"]["skipped_existing_files"]) == len(second["planned_files"])
    assert map_path.read_text(encoding="utf-8") == original_map
    assert any("Resume with" in step for step in second["next"])


def test_cli_adopt_routes_to_project_init(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    host = tmp_path / "CLI Adopt"
    host.mkdir()

    exit_code = bert_cli_main(["adopt", str(host), "--name", "CLI Adopt", "--apply", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["operation"] == "bert_project_init"
    assert payload["write_enabled"] is True
    assert payload["already_initialized"] is False
    assert (host / ".BERT" / "L1M1" / "MAP.md").exists()
    assert (host / ".BERT" / "state.json").exists()


def test_project_open_reports_niklas_candidate_anchor(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    store = NiklasStore(env.db_path)
    store.initialize()
    store.ensure_project("Some Linear Project")
    host = tmp_path / "Some Linear Project"
    host.mkdir()
    build_project_init_payload(str(host), name="Some Linear Project", apply=True, env=env)

    opened = build_project_open_payload(str(host), env=env)

    assert opened["niklas_lookup"]["schema_present"] is True
    assert opened["niklas_lookup"]["correlation_status"] == "candidate_matches"
    assert opened["niklas_lookup"]["matches"][0]["id"] == "project:some-linear-project"
    assert opened["position"]["niklas_correlation"] == "candidate_matches"


def test_project_open_resumes_first_unaccepted_stage(tmp_path: Path) -> None:
    """A drafted-but-unaccepted file no longer fakes progress (acceptance = completion)."""
    env = make_env(tmp_path)
    host = tmp_path / "Resume Project"
    host.mkdir()
    build_project_init_payload(str(host), name="Resume Project", apply=True, env=env)
    ingest_output = host / ".BERT" / "L1M1" / "dev" / "0-ingest" / "Ingest_L1M1_V1.md"
    ingest_output.write_text("---\nstatus: draft\n---\n# Ingest claims to be complete\n", encoding="utf-8")

    opened = build_project_open_payload(str(host), env=env)
    assert opened["bert_process"]["state"] == "in_progress"
    assert opened["bert_process"]["current_node"] == "L1M1"
    assert opened["bert_process"]["current_stage"] == "0-ingest"
    assert opened["bert_process"]["stage_progress"][0]["status"] == "drafting"
    assert opened["bert_process"]["stage_progress"][1]["status"] == "pending"

    from niklas.bert_core import build_accept_payload as _accept

    assert _accept(str(host), apply=True, env=env)["accepted"] is True
    reopened = build_project_open_payload(str(host), env=env)
    assert reopened["bert_process"]["current_stage"] == "1-brainstorm"
    assert reopened["bert_process"]["stage_progress"][0]["status"] == "complete"


def test_bert_on_blocks_container_folder(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    desktop = env.home / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)

    payload = build_bert_on_payload(str(desktop), env=env)

    assert payload["operation"] == "bert_on"
    assert payload["headline"] == "BERT needs a project folder."
    assert payload["bert_process"]["state"] == "not_started"
    assert payload["primary_action"]["label"] == "Choose project folder"
    assert payload["linear_status"]["lookup"] == "skipped_folder_gate"
    assert payload["niklas_status"]["correlation"] == "skipped_folder_gate"


def test_bert_on_blank_folder_starts_at_beginning(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "Blank UX"
    host.mkdir()

    payload = build_bert_on_payload(str(host), env=env)

    assert payload["headline"] == "BERT is not started here yet."
    assert payload["bert_process"]["state"] == "not_started"
    assert payload["bert_process"]["current_node"] == "L1M1"
    assert payload["bert_process"]["current_stage"] == "0-ingest"
    assert payload["primary_action"]["label"] == "Start BERT here"
    assert payload["primary_action"]["write_required"] is True


def test_bert_on_existing_non_bert_folder_starts_at_beginning(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "Existing UX"
    host.mkdir()
    (host / "README.md").write_text("# Existing UX\n", encoding="utf-8")

    payload = build_bert_on_payload(str(host), env=env)

    assert payload["bert_process"]["state"] == "not_started"
    assert payload["bert_process"]["start_reason"] == "existing_material_without_bert"
    assert payload["bert_process"]["current_stage"] == "0-ingest"
    assert payload["primary_action"]["label"] == "Start BERT here"
    assert payload["project_material"]["markers"][0]["kind"] == "readme"


def test_bert_on_initialized_folder_resumes(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "Initialized UX"
    host.mkdir()
    build_project_init_payload(str(host), name="Initialized UX", apply=True, env=env)

    payload = build_bert_on_payload(str(host), env=env)

    assert payload["headline"] == "BERT is already active here."
    assert payload["initialized"] is True
    assert payload["bert_process"]["state"] == "in_progress"
    assert payload["bert_process"]["current_node"] == "L1M1"
    assert payload["bert_process"]["current_stage"] == "0-ingest"
    assert payload["primary_action"]["label"] == "Continue 0-ingest"


def test_project_analyze_blocks_desktop_container(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    desktop = env.home / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)

    payload = build_project_analyze_payload(str(desktop), env=env)
    init_payload = build_project_init_payload(str(desktop), apply=True, env=env)

    assert payload["operation"] == "bert_project_analyze"
    assert payload["initialized"] is False
    assert payload["folder_gate"]["status"] == "blocked_requires_project_folder"
    assert payload["bert_fit_assessment"]["decision"] == "choose_or_create_folder"
    assert payload["bert_process"]["state"] == "not_started"
    assert payload["bert_process"]["current_node"] == "L1M1"
    assert payload["bert_process"]["current_stage"] == "0-ingest"
    assert init_payload["write_enabled"] is False
    assert init_payload["folder_gate"]["status"] == "blocked_requires_project_folder"
    assert not (desktop / ".BERT").exists()


def test_project_open_analyzes_blank_folder_before_adoption(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "Blank Candidate"
    host.mkdir()

    payload = build_project_open_payload(str(host), env=env)

    assert payload["operation"] == "bert_project_analyze"
    assert payload["initialized"] is False
    assert payload["folder_gate"]["status"] == "ok_project_folder"
    assert payload["bert_fit_assessment"]["status"] == "blank_candidate"
    assert payload["bert_process"]["state"] == "not_started"
    assert payload["bert_process"]["start_reason"] == "blank_folder"
    assert payload["bert_process"]["current_stage"] == "0-ingest"
    assert payload["write_enabled"] is False
    assert not (host / ".BERT").exists()


def test_project_analyze_reports_existing_markers_without_writes(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "Existing App"
    host.mkdir()
    (host / "README.md").write_text("# Existing App\n", encoding="utf-8")
    (host / "package.json").write_text("{\"name\":\"existing-app\"}\n", encoding="utf-8")

    payload = build_project_analyze_payload(str(host), task="build MVP", env=env)

    assert payload["operation"] == "bert_project_analyze"
    assert payload["initialized"] is False
    assert payload["inventory"]["likely_project_kind"] == "node_or_web_app"
    assert {marker["kind"] for marker in payload["inventory"]["markers"]} >= {"readme", "node_package"}
    assert payload["bert_fit_assessment"]["status"] == "candidate_requires_review"
    assert payload["bert_process"]["state"] == "not_started"
    assert payload["bert_process"]["start_reason"] == "existing_material_without_bert"
    assert not (host / ".BERT").exists()


def test_node_locate_proposes_next_child_from_parent(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    build_project_create_payload("My BERT Project", apply=True, env=env)

    payload = build_node_locate_payload("my-bert-project", env=env)

    assert payload["operation"] == "bert_node_locate"
    assert payload["initialized"] is True
    assert payload["parent"]["node_path"] == "L1M1"
    assert payload["proposed_node"]["node_path"] == "L1M1/L2M1"
    assert payload["proposed_node"]["linear_mirror"]["default_linear_type"] == "Sub-initiative"


def test_node_start_can_init_project_and_create_first_child(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = tmp_path / "Host Project"
    host.mkdir()

    payload = build_node_start_payload(
        str(host),
        name="Host Project",
        init_project=True,
        apply=True,
        env=env,
    )

    assert payload["operation"] == "bert_node_start"
    assert (host / ".BERT" / "L1M1" / "_node.md").exists()
    assert (host / ".BERT" / "L1M1" / "L2M1" / "_node.md").exists()
    assert payload["node_create"]["node_path"] == "L1M1/L2M1"
    assert any(step["step"] == "create_node" and step["status"] == "applied" for step in payload["workflow_steps"])


def test_node_map_and_spawn_children_from_root_map(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    build_project_create_payload("My BERT Project", apply=True, env=env)

    map_payload = build_node_map_payload("my-bert-project", node_path="L1M1", env=env)
    assert map_payload["map_exists"] is True
    assert [candidate["node_id"] for candidate in map_payload["child_candidates"]] == ["L2M1", "L2M2"]

    spawn = build_node_spawn_children_payload(
        "my-bert-project",
        parent_path="L1M1",
        apply=True,
        env=env,
    )
    project_dir = Path(spawn["map"]["bert_workspace_dir"])

    assert spawn["write_enabled"] is True
    assert [child["node_path"] for child in spawn["planned_children"]] == ["L1M1/L2M1", "L1M1/L2M2"]
    assert (project_dir / "L1M1" / "L2M1" / "_node.md").exists()
    assert (project_dir / "L1M1" / "L2M2" / "_node.md").exists()


def test_node_stages_reports_child_without_ingest(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    build_project_create_payload("My BERT Project", apply=True, env=env)
    build_node_create_payload("L2M1", project="my-bert-project", apply=True, env=env)

    payload = build_node_stages_payload("my-bert-project", node_path="L1M1/L2M1", env=env)

    assert payload["node_exists"] is True
    assert payload["linear_mirror"]["default_linear_type"] == "Sub-initiative"
    assert [stage["folder"] for stage in payload["stages"]][0] == "1-brainstorm"
    assert "0-ingest" not in [stage["folder"] for stage in payload["stages"]]


# ---------------------------------------------------------------------------
# Slice 1: stage loop — forms, draft, accept, state v2, next (ERI-2456)
# ---------------------------------------------------------------------------

from niklas.bert_core import (  # noqa: E402
    build_accept_payload,
    build_next_payload,
    build_stage_draft_payload,
)


def _adopted_host(tmp_path: Path, env: BertEnvironment, name: str = "Loop Demo") -> Path:
    host = tmp_path / name
    host.mkdir()
    build_project_init_payload(host, name=name, apply=True, env=env)
    return host


def _accept_through(host: Path, env: BertEnvironment, stages: list[str]) -> None:
    """Draft + answer-free accept each stage in order (citation stages get a citation)."""
    for folder in stages:
        draft = build_stage_draft_payload(str(host), apply=True, env=env)
        artifact = Path(draft["artifact"]["path"])
        if folder in {"4-blueprint", "7-map"}:
            text = artifact.read_text(encoding="utf-8")
            text = text.replace(
                "- TBD (cite wiki atoms, source packages, or local packet paths)",
                "- dev/2-experts/Experts_L1M1_V1.md — expert table backing this route",
            )
            artifact.write_text(text, encoding="utf-8")
        accepted = build_accept_payload(str(host), apply=True, env=env)
        assert accepted["accepted"] is True, f"{folder}: {accepted.get('reason')}"
        assert accepted["stage"]["folder"] == folder


def test_state_v2_written_on_adopt(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)
    state = json.loads((host / ".BERT" / "state.json").read_text(encoding="utf-8"))

    assert state["schema"] == "bert-state-v2"
    assert state["current_node"] == "L1M1"
    assert state["current_stage"] == "0-ingest"
    assert state["stages"] == {"L1M1": {}}


def test_stage_draft_plan_then_apply_scaffolds_form(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)

    plan = build_stage_draft_payload(str(host), env=env)
    assert plan["mode"] == "read_only_dry_run"
    assert plan["stage"]["folder"] == "0-ingest"
    assert plan["artifact"]["path"].endswith("dev/0-ingest/Ingest_L1M1_V1.md")
    assert not Path(plan["artifact"]["path"]).exists()

    applied = build_stage_draft_payload(str(host), apply=True, env=env)
    artifact = Path(applied["artifact"]["path"])
    assert artifact.exists()
    text = artifact.read_text(encoding="utf-8")
    assert "kind: bert_stage_artifact" in text
    assert "status: draft" in text
    assert "## Questions" in text
    assert "Answer:" in text
    assert "## Simple Status" in text


def test_stage_draft_version_bumps_and_carries_forward(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)
    first = build_stage_draft_payload(str(host), apply=True, env=env)
    v1 = Path(first["artifact"]["path"])
    v1.write_text(
        v1.read_text(encoding="utf-8") + "\nUNIQUE-CARRY-MARKER\n", encoding="utf-8"
    )

    second = build_stage_draft_payload(str(host), apply=True, env=env)
    v2 = Path(second["artifact"]["path"])

    assert v2.name == "Ingest_L1M1_V2.md"
    assert v1.exists() and v2.exists()
    text = v2.read_text(encoding="utf-8")
    assert "UNIQUE-CARRY-MARKER" in text
    assert "version: 2" in text
    assert "status: draft" in text


def test_accept_advances_state_and_stamps_artifact(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)
    draft = build_stage_draft_payload(str(host), apply=True, env=env)

    plan = build_accept_payload(str(host), env=env)
    assert plan["mode"] == "read_only_dry_run"
    assert plan["accepted"] is False
    assert plan["would_accept"] is True

    accepted = build_accept_payload(str(host), apply=True, env=env)
    assert accepted["accepted"] is True
    assert accepted["stage"]["folder"] == "0-ingest"

    state = json.loads((host / ".BERT" / "state.json").read_text(encoding="utf-8"))
    record = state["stages"]["L1M1"]["0-ingest"]
    assert record["status"] == "accepted"
    assert record["latest_version"] == 1
    assert record["accepted_at"]
    assert state["current_stage"] == "1-brainstorm"

    text = Path(draft["artifact"]["path"]).read_text(encoding="utf-8")
    assert "status: accepted" in text
    assert "status: draft" not in text


def test_accept_refuses_missing_artifact_and_out_of_sequence(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)

    missing = build_accept_payload(str(host), apply=True, env=env)
    assert missing["accepted"] is False
    assert missing["reason"] == "no_draft_to_accept"

    skip = build_accept_payload(str(host), stage="4-blueprint", apply=True, env=env)
    assert skip["accepted"] is False
    assert skip["reason"] == "out_of_sequence"


def test_accept_same_version_twice_refused(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)
    build_stage_draft_payload(str(host), apply=True, env=env)
    first = build_accept_payload(str(host), apply=True, env=env)
    second = build_accept_payload(str(host), stage="0-ingest", apply=True, env=env)

    assert first["accepted"] is True
    assert second["accepted"] is False
    assert second["reason"] in {"out_of_sequence", "already_accepted"}


def test_accept_citation_gate_on_blueprint(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)
    _accept_through(host, env, ["0-ingest", "1-brainstorm", "2-experts", "3-research"])

    build_stage_draft_payload(str(host), apply=True, env=env)  # 4-blueprint V1
    refused = build_accept_payload(str(host), apply=True, env=env)
    assert refused["accepted"] is False
    assert refused["reason"] == "citation_gate_failed"

    blueprint = (
        host / ".BERT" / "L1M1" / "dev" / "4-blueprint" / "Blueprint_L1M1_V1.md"
    )
    text = blueprint.read_text(encoding="utf-8").replace(
        "- TBD (cite wiki atoms, source packages, or local packet paths)",
        "- dev/2-experts/Experts_L1M1_V1.md — expert table backing this route",
    )
    blueprint.write_text(text, encoding="utf-8")

    accepted = build_accept_payload(str(host), apply=True, env=env)
    assert accepted["accepted"] is True
    assert accepted["stage"]["folder"] == "4-blueprint"


def test_altitude_lint_warns_but_never_blocks(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)
    _accept_through(host, env, ["0-ingest"])

    draft = build_stage_draft_payload(str(host), apply=True, env=env)  # 1-brainstorm
    artifact = Path(draft["artifact"]["path"])
    artifact.write_text(
        artifact.read_text(encoding="utf-8")
        + "\nWe will use postgres and a docker container in api_server.py.\n",
        encoding="utf-8",
    )

    accepted = build_accept_payload(str(host), apply=True, env=env)
    assert accepted["accepted"] is True
    assert any("altitude" in warning.lower() for warning in accepted["warnings"])


def test_next_payload_walks_the_loop(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)

    fresh = build_next_payload(str(host), env=env)
    assert fresh["node"] == "L1M1"
    assert fresh["stage"]["folder"] == "0-ingest"
    assert fresh["waiting_on"] == "agent_draft"
    assert "bert stage draft" in fresh["next_command"]

    build_stage_draft_payload(str(host), apply=True, env=env)
    drafted = build_next_payload(str(host), env=env)
    assert drafted["waiting_on"] == "erich_answers"
    assert drafted["latest_version"] == 1

    build_accept_payload(str(host), apply=True, env=env)
    advanced = build_next_payload(str(host), env=env)
    assert advanced["stage"]["folder"] == "1-brainstorm"
    assert advanced["waiting_on"] == "agent_draft"


def test_stage_progress_prefers_acceptance_over_file_existence(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    host = _adopted_host(tmp_path, env)
    build_stage_draft_payload(str(host), apply=True, env=env)  # 0-ingest drafted, NOT accepted

    opened = build_project_open_payload(str(host), env=env)
    process = opened["bert_process"]
    assert process["current_stage"] == "0-ingest"
    ingest_row = next(
        row for row in process["stage_progress"] if row["folder"] == "0-ingest"
    )
    assert ingest_row["status"] == "drafting"

    # Legacy v1 state: file existence still completes (read-compat fallback).
    state_path = host / ".BERT" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["schema"] = "bert-state-v1"
    state.pop("stages", None)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    legacy = build_project_open_payload(str(host), env=env)
    legacy_row = next(
        row
        for row in legacy["bert_process"]["stage_progress"]
        if row["folder"] == "0-ingest"
    )
    assert legacy_row["status"] == "complete"


def test_cli_next_draft_accept_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    host = tmp_path / "CLI Loop"
    host.mkdir()
    assert bert_cli_main(["adopt", str(host), "--name", "CLI Loop", "--apply", "--json"]) == 0
    capsys.readouterr()

    assert bert_cli_main(["stage", "draft", "--project", str(host), "--apply", "--json"]) == 0
    draft = json.loads(capsys.readouterr().out)
    assert draft["operation"] == "bert_stage_draft"
    assert Path(draft["artifact"]["path"]).exists()

    assert bert_cli_main(["accept", "--project", str(host), "--apply", "--json"]) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["operation"] == "bert_accept"
    assert accepted["accepted"] is True

    assert bert_cli_main(["next", "--project", str(host), "--json"]) == 0
    nxt = json.loads(capsys.readouterr().out)
    assert nxt["operation"] == "bert_next"
    assert nxt["stage"]["folder"] == "1-brainstorm"
