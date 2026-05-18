"""Focused tests for the daily source catalog loader.

Run with:
    cd ~/Desktop/Cornelius/resources/brain-graph
    python -m pytest daily/test_source_catalog.py -q
"""
from __future__ import annotations

import json
import builtins
from pathlib import Path

import pytest

from daily.source_catalog import SourceCatalogError, load_source_catalog


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_expands_home_and_environment_variables(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    target = home / "Brain" / "wiki"
    target.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CATALOG_CHILD", "wiki")

    catalog_path = _write_json(
        tmp_path / "sources.json",
        {
            "version": 1,
            "sources": [
                {
                    "id": "brain_wiki",
                    "path": "~/Brain/$CATALOG_CHILD",
                }
            ],
        },
    )

    catalog = load_source_catalog(catalog_path)
    root = catalog.get("brain_wiki")
    assert root is not None
    assert root.path == target
    assert root.status == "available"


def test_enabled_disabled_and_unavailable_roots_return_status(tmp_path: Path) -> None:
    available = tmp_path / "available"
    available.mkdir()
    missing_mount = tmp_path / "missing-drive"

    catalog_path = _write_json(
        tmp_path / "sources.json",
        {
            "version": 1,
            "sources": [
                {"id": "available", "path": str(available), "enabled": True},
                {"id": "disabled", "path": str(missing_mount), "enabled": False},
                {"id": "unavailable", "path": str(missing_mount), "enabled": True},
            ],
        },
    )

    catalog = load_source_catalog(catalog_path)
    assert [root.id for root in catalog.enabled_roots] == ["available", "unavailable"]
    assert [root.id for root in catalog.available_roots] == ["available"]
    assert [root.id for root in catalog.disabled_roots] == ["disabled"]
    assert [root.id for root in catalog.unavailable_roots] == ["unavailable"]
    assert catalog.get("unavailable").status == "unavailable"  # type: ignore[union-attr]


def test_missing_catalog_fields_raise_clear_validation_errors(tmp_path: Path) -> None:
    missing_sources = _write_json(tmp_path / "missing-sources.json", {"version": 1})
    with pytest.raises(SourceCatalogError, match="source_roots|sources"):
        load_source_catalog(missing_sources)

    missing_id = _write_json(
        tmp_path / "missing-id.json",
        {"version": 1, "sources": [{"path": str(tmp_path)}]},
    )
    with pytest.raises(SourceCatalogError, match="id"):
        load_source_catalog(missing_id)

    missing_path = _write_json(
        tmp_path / "missing-path.json",
        {"version": 1, "sources": [{"id": "no_path"}]},
    )
    with pytest.raises(SourceCatalogError, match="path"):
        load_source_catalog(missing_path)


def test_include_exclude_policy_parsing_and_matching(tmp_path: Path) -> None:
    root_path = tmp_path / "source"
    root_path.mkdir()
    catalog_path = _write_json(
        tmp_path / "sources.json",
        {
            "version": 1,
            "sources": [
                {
                    "id": "policy_root",
                    "path": str(root_path),
                    "policy": {
                        "include": ["**/*.md", "**/*.txt"],
                        "exclude": ["**/private/**", "**/.git/**"],
                    },
                }
            ],
        },
    )

    catalog = load_source_catalog(catalog_path)
    root = catalog.get("policy_root")
    assert root is not None
    assert root.policy.include == ("**/*.md", "**/*.txt")
    assert root.policy.exclude == ("**/private/**", "**/.git/**")
    assert root.allows("today.md")
    assert root.allows("notes/today.md")
    assert root.allows("notes/today.txt")
    assert not root.allows("private/today.md")
    assert not root.allows("notes/private/today.md")
    assert not root.allows("notes/image.png")


def test_yaml_catalog_shape_loads_without_callers_caring_about_format(tmp_path: Path) -> None:
    root_path = tmp_path / "yaml-source"
    root_path.mkdir()
    catalog_path = tmp_path / "sources.yaml"
    catalog_path.write_text(
        f"""
version: 1
owner: test
sources:
  - id: yaml_root
    label: YAML Root
    path: "{root_path}"
    enabled: true
    policy:
      include:
        - "**/*.md"
      exclude:
        - "**/tmp/**"
""".lstrip(),
        encoding="utf-8",
    )

    catalog = load_source_catalog(catalog_path)
    root = catalog.get("yaml_root")
    assert catalog.metadata["owner"] == "test"
    assert root is not None
    assert root.label == "YAML Root"
    assert root.path == root_path
    assert root.policy.include == ("**/*.md",)
    assert not root.allows("notes/tmp/scratch.md")


def test_source_roots_shape_and_extension_name_policy_loads(tmp_path: Path) -> None:
    root_path = tmp_path / "brain"
    root_path.mkdir()
    catalog_path = tmp_path / "source_catalog.yaml"
    catalog_path.write_text(
        f"""
version: 1
catalog_purpose: source_inventory_intake_policy
source_roots:
  - id: brain_wiki
    path: "{root_path}"
    kind: wiki
    enabled: true
    include_extensions:
      - .md
      - txt
    exclude_names:
      - .git
      - node_modules
    default_policy: index_text_metadata
""".lstrip(),
        encoding="utf-8",
    )

    catalog = load_source_catalog(catalog_path)
    root = catalog.get("brain_wiki")
    assert catalog.metadata["catalog_purpose"] == "source_inventory_intake_policy"
    assert root is not None
    assert root.status == "available"
    assert root.metadata["kind"] == "wiki"
    assert root.metadata["default_policy"] == "index_text_metadata"
    assert root.allows("today.md")
    assert root.allows("notes/today.txt")
    assert not root.allows("notes/image.png")
    assert not root.allows(".git/config")
    assert not root.allows("project/node_modules/package.json")


def test_minimal_yaml_fallback_when_pyyaml_is_not_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_path = tmp_path / "fallback-source"
    root_path.mkdir()
    catalog_path = tmp_path / "sources.yml"
    catalog_path.write_text(
        f"""
version: 1
sources:
  - id: fallback_root
    path: "{root_path}"
    enabled: true
    policy:
      include:
        - "**/*.txt"
      exclude:
        - "**/drafts/**"
""".lstrip(),
        encoding="utf-8",
    )

    real_import = builtins.__import__

    def block_yaml_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "yaml":
            raise ImportError("blocked for fallback test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", block_yaml_import)

    catalog = load_source_catalog(catalog_path)
    root = catalog.get("fallback_root")
    assert root is not None
    assert root.status == "available"
    assert root.allows("notes/today.txt")
    assert not root.allows("notes/drafts/today.txt")
