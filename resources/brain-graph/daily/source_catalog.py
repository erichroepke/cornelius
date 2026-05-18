"""
Brain Daily Ingest - Source Catalog

Small loader for declaring the source roots that a future `daily.cli discover`
command can inspect. Loading a catalog never walks source trees and never treats
missing mounted drives as fatal. Missing enabled roots are returned with
status="unavailable" so callers can report them and keep going.

Supported formats:
    - JSON via the Python standard library.
    - YAML via PyYAML when available.
    - A minimal YAML fallback for simple catalog files when PyYAML is absent.

Expected shape:

    version: 1
    source_roots:
      - id: zeus_drive
        label: Zeus Drive
        path: "$ZEUS_DRIVE/Zeus"
        enabled: true
        include_extensions:
          - .md
        exclude_names:
          - .git

Required source fields are `id` and `path`. `enabled` defaults to true.
The older `sources` key is still accepted for compatibility.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


class SourceCatalogError(ValueError):
    """Raised when a catalog file is unreadable or structurally invalid."""


@dataclass(frozen=True)
class SourcePolicy:
    """Include/exclude glob policy for paths relative to a source root."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def allows(self, relative_path: str | Path) -> bool:
        """Return true when a relative path passes include/exclude rules."""
        rel = _normalize_relative_path(relative_path)
        included = True
        if self.include:
            included = _matches_any(rel, self.include)
        excluded = _matches_any(rel, self.exclude)
        return included and not excluded

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "include": list(self.include),
            "exclude": list(self.exclude),
        }


@dataclass(frozen=True)
class SourceRoot:
    """One configured source root from the catalog."""

    id: str
    path: Path
    raw_path: str
    enabled: bool = True
    status: str = "available"
    label: str = ""
    policy: SourcePolicy = field(default_factory=SourcePolicy)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        """True when the root is enabled and currently exists."""
        return self.status == "available"

    def allows(self, relative_path: str | Path) -> bool:
        """Delegate to the root policy."""
        return self.policy.allows(relative_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "path": str(self.path),
            "raw_path": self.raw_path,
            "enabled": self.enabled,
            "status": self.status,
            "policy": self.policy.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceCatalog:
    """Loaded source catalog ready for daily discover/indexing consumers."""

    catalog_path: Path
    version: str
    roots: tuple[SourceRoot, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled_roots(self) -> tuple[SourceRoot, ...]:
        return tuple(root for root in self.roots if root.enabled)

    @property
    def available_roots(self) -> tuple[SourceRoot, ...]:
        return tuple(root for root in self.roots if root.status == "available")

    @property
    def unavailable_roots(self) -> tuple[SourceRoot, ...]:
        return tuple(root for root in self.roots if root.status == "unavailable")

    @property
    def disabled_roots(self) -> tuple[SourceRoot, ...]:
        return tuple(root for root in self.roots if root.status == "disabled")

    def get(self, root_id: str) -> Optional[SourceRoot]:
        """Return a root by id, or None if it is not present."""
        for root in self.roots:
            if root.id == root_id:
                return root
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_path": str(self.catalog_path),
            "version": self.version,
            "sources": [root.to_dict() for root in self.roots],
            "metadata": dict(self.metadata),
        }


def load_source_catalog(path: str | Path, *, check_availability: bool = True) -> SourceCatalog:
    """Load, validate, and normalize a JSON/YAML source catalog."""
    catalog_path = Path(path).expanduser()
    data = _load_catalog_data(catalog_path)
    if not isinstance(data, dict):
        raise SourceCatalogError("source catalog must be a mapping/object")

    source_key = "source_roots" if "source_roots" in data else "sources"
    raw_sources = data.get(source_key)
    if not isinstance(raw_sources, list):
        raise SourceCatalogError("source catalog requires a 'source_roots' or 'sources' list")

    roots = tuple(
        _parse_source_root(
            item,
            index=index,
            base_dir=catalog_path.parent,
            check_availability=check_availability,
        )
        for index, item in enumerate(raw_sources)
    )
    metadata = {
        key: value
        for key, value in data.items()
        if key not in {"version", "source_roots", "sources"}
    }

    return SourceCatalog(
        catalog_path=catalog_path,
        version=str(data.get("version", "1")),
        roots=roots,
        metadata=metadata,
    )


def expand_source_path(raw_path: str, *, base_dir: Optional[Path] = None) -> Path:
    """Expand environment variables and `~`; relative paths use base_dir if given."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise SourceCatalogError("source path must be a non-empty string")

    expanded = os.path.expanduser(os.path.expandvars(raw_path.strip()))
    path = Path(expanded)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path


def _parse_source_root(
    item: Any,
    *,
    index: int,
    base_dir: Path,
    check_availability: bool,
) -> SourceRoot:
    if not isinstance(item, dict):
        raise SourceCatalogError(f"sources[{index}] must be a mapping/object")

    root_id = _required_string(item, "id", index)
    raw_path = _required_string(item, "path", index)
    enabled = _parse_enabled(item.get("enabled", True), index)
    path = expand_source_path(raw_path, base_dir=base_dir)
    status = _status_for(path, enabled=enabled, check_availability=check_availability)
    policy = _parse_policy(item, index)

    reserved = {
        "id",
        "label",
        "path",
        "enabled",
        "policy",
        "include",
        "exclude",
        "include_extensions",
        "exclude_names",
    }
    metadata = {key: value for key, value in item.items() if key not in reserved}

    return SourceRoot(
        id=root_id,
        label=str(item.get("label", "")),
        path=path,
        raw_path=raw_path,
        enabled=enabled,
        status=status,
        policy=policy,
        metadata=metadata,
    )


def _required_string(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SourceCatalogError(f"sources[{index}] requires a non-empty '{key}' string")
    return value.strip()


def _parse_enabled(value: Any, index: int) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    raise SourceCatalogError(f"sources[{index}].enabled must be a boolean")


def _status_for(path: Path, *, enabled: bool, check_availability: bool) -> str:
    if not enabled:
        return "disabled"
    if not check_availability:
        return "unchecked"
    try:
        return "available" if path.exists() else "unavailable"
    except OSError:
        return "unavailable"


def _parse_policy(item: dict[str, Any], index: int) -> SourcePolicy:
    policy_data = item.get("policy", {})
    if policy_data is None:
        policy_data = {}
    if not isinstance(policy_data, dict):
        raise SourceCatalogError(f"sources[{index}].policy must be a mapping/object")

    include_raw = policy_data.get("include", item.get("include", ()))
    exclude_raw = policy_data.get("exclude", item.get("exclude", ()))
    include_patterns = list(_normalize_patterns(include_raw, f"sources[{index}].policy.include"))
    exclude_patterns = list(_normalize_patterns(exclude_raw, f"sources[{index}].policy.exclude"))

    include_patterns.extend(
        _patterns_from_extensions(
            item.get("include_extensions", ()),
            f"sources[{index}].include_extensions",
        )
    )
    exclude_patterns.extend(
        _patterns_from_exclude_names(
            item.get("exclude_names", ()),
            f"sources[{index}].exclude_names",
        )
    )

    return SourcePolicy(
        include=tuple(_dedupe_patterns(include_patterns)),
        exclude=tuple(_dedupe_patterns(exclude_patterns)),
    )


def _normalize_patterns(value: Any, field_name: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        patterns: list[str] = []
        for entry in value:
            if not isinstance(entry, str) or not entry.strip():
                raise SourceCatalogError(f"{field_name} entries must be non-empty strings")
            patterns.append(entry.strip())
        return tuple(patterns)
    raise SourceCatalogError(f"{field_name} must be a string or list of strings")


def _patterns_from_extensions(value: Any, field_name: str) -> tuple[str, ...]:
    extensions = _normalize_patterns(value, field_name)
    patterns: list[str] = []
    for extension in extensions:
        normalized = extension.strip()
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        patterns.append(f"**/*{normalized}")
    return tuple(patterns)


def _patterns_from_exclude_names(value: Any, field_name: str) -> tuple[str, ...]:
    names = _normalize_patterns(value, field_name)
    patterns: list[str] = []
    for name in names:
        normalized = name.strip().strip("/")
        if not normalized:
            continue
        patterns.extend(
            (
                normalized,
                f"**/{normalized}",
                f"{normalized}/**",
                f"**/{normalized}/**",
            )
        )
    return tuple(patterns)


def _dedupe_patterns(patterns: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for pattern in patterns:
        if pattern not in seen:
            seen.add(pattern)
            deduped.append(pattern)
    return deduped


def _normalize_relative_path(relative_path: str | Path) -> str:
    return str(relative_path).replace(os.sep, "/").lstrip("/")


def _matches_any(relative_path: str, patterns: tuple[str, ...]) -> bool:
    return any(_matches_glob(relative_path, pattern) for pattern in patterns)


def _matches_glob(relative_path: str, pattern: str) -> bool:
    normalized = pattern.replace(os.sep, "/").lstrip("/")
    if fnmatch.fnmatch(relative_path, normalized):
        return True
    if normalized.startswith("**/"):
        return fnmatch.fnmatch(relative_path, normalized[3:])
    return False


def _load_catalog_data(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceCatalogError(f"could not read source catalog {path}: {exc}") from exc

    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(text, path)
    if suffix in {".yaml", ".yml"}:
        return _load_yaml(text, path)

    try:
        return _load_json(text, path)
    except SourceCatalogError:
        return _load_yaml(text, path)


def _load_json(text: str, path: Path) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceCatalogError(f"invalid JSON in source catalog {path}: {exc}") from exc


def _load_yaml(text: str, path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_minimal_yaml(text, path)

    try:
        return yaml.safe_load(text) or {}
    except Exception as exc:  # PyYAML raises a family of parser/scanner errors.
        raise SourceCatalogError(f"invalid YAML in source catalog {path}: {exc}") from exc


def _parse_minimal_yaml(text: str, path: Path) -> dict[str, Any]:
    """Parse the small YAML subset used by source catalogs when PyYAML is absent."""
    lines = _prepare_yaml_lines(text)
    if not lines:
        return {}
    try:
        parsed, index = _parse_yaml_mapping(lines, 0, lines[0][0])
    except SourceCatalogError:
        raise
    except Exception as exc:
        raise SourceCatalogError(
            f"YAML support requires PyYAML for this catalog shape: {path}"
        ) from exc

    if index != len(lines):
        raise SourceCatalogError(f"could not parse full YAML source catalog {path}")
    return parsed


def _prepare_yaml_lines(text: str) -> list[tuple[int, str]]:
    prepared: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stripped_comment = _strip_yaml_comment(raw.rstrip())
        if not stripped_comment.strip():
            continue
        indent = len(stripped_comment) - len(stripped_comment.lstrip(" "))
        prepared.append((indent, stripped_comment.strip()))
    return prepared


def _strip_yaml_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:idx].rstrip()
    return line


def _parse_yaml_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, current_text = lines[index]
    if current_indent < indent:
        return {}, index
    if current_indent != indent:
        raise SourceCatalogError("inconsistent indentation in YAML source catalog")
    if current_text.startswith("- "):
        return _parse_yaml_list(lines, index, indent)
    return _parse_yaml_mapping(lines, index, indent)


def _parse_yaml_mapping(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        current_indent, text = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SourceCatalogError("unexpected nested mapping in YAML source catalog")
        if text.startswith("- "):
            break
        key, value = _split_yaml_key_value(text)
        index += 1
        if value == "":
            if index < len(lines) and lines[index][0] > current_indent:
                result[key], index = _parse_yaml_block(lines, index, lines[index][0])
            else:
                result[key] = {}
        else:
            result[key] = _parse_yaml_scalar(value)
    return result, index


def _parse_yaml_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        current_indent, text = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent or not text.startswith("- "):
            break

        body = text[2:].strip()
        index += 1
        if not body:
            if index < len(lines) and lines[index][0] > current_indent:
                item, index = _parse_yaml_block(lines, index, lines[index][0])
            else:
                item = None
        elif _looks_like_key_value(body):
            key, value = _split_yaml_key_value(body)
            item = {key: _parse_yaml_scalar(value)} if value != "" else {key: {}}
            if index < len(lines) and lines[index][0] > current_indent:
                continuation, index = _parse_yaml_mapping(lines, index, lines[index][0])
                if not isinstance(continuation, dict):
                    raise SourceCatalogError("YAML list item continuation must be a mapping")
                item.update(continuation)
        else:
            item = _parse_yaml_scalar(body)
        result.append(item)
    return result, index


def _looks_like_key_value(text: str) -> bool:
    return ":" in text and not text.startswith(("'", '"'))


def _split_yaml_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise SourceCatalogError(f"expected key/value entry in YAML source catalog: {text!r}")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise SourceCatalogError("empty key in YAML source catalog")
    return key, value.strip()


def _parse_yaml_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""

    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if lower in {"null", "none", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            inner = value[1:-1].strip()
            return [] if not inner else [_parse_yaml_scalar(part.strip()) for part in inner.split(",")]
        return parsed
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
