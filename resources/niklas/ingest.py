"""Local file ingest for Niklas."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .store import NiklasStore, slugify, stable_id, utcnow

logger = logging.getLogger("niklas.ingest")


TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".htm",
    ".xml",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".sh",
    ".sql",
}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv"}
MAX_TEXT_BYTES = 1_000_000
PREVIEW_CHARS = 1200


@dataclass
class IngestedFile:
    node_id: str
    path: str
    type: str
    title: str
    content_hash: str


@dataclass
class IngestResult:
    root_path: str
    project: str | None
    recursive: bool
    files_seen: int = 0
    files_ingested: int = 0
    nodes_written: int = 0
    relationships_written: int = 0
    skipped: list[dict[str, str]] | None = None
    ingest_run_id: str | None = None
    db_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ingest_path(
    path: str | Path,
    *,
    project_scope: str | None = None,
    tags: Iterable[str] | None = None,
    recursive: bool = False,
    db_path: str | Path | None = None,
    max_files: int | None = None,
) -> dict[str, Any]:
    """Ingest a local file or directory into the Niklas graph."""
    target = Path(path).expanduser()
    if not target.exists():
        raise FileNotFoundError(f"ingest path does not exist: {target}")

    logger.info(f"Starting ingest of path: {target} (project: {project_scope}, recursive: {recursive})")

    store = NiklasStore(db_path)
    store.initialize()

    root = target if target.is_dir() else target.parent
    started_at = utcnow()
    result = IngestResult(
        root_path=str(target),
        project=project_scope,
        recursive=recursive,
        skipped=[],
        db_path=str(store.db_path),
    )

    source_id = stable_id("source", str(root.resolve(strict=False)), 20)
    store.upsert_node(
        node_id=source_id,
        node_type="Source",
        title=root.name or str(root),
        path=str(root),
        absolute_path=str(root.resolve(strict=False)),
        project=project_scope,
        metadata={"source_kind": "local-root"},
    )

    link_buffer: list[tuple[str, str, str]] = []
    tag_defaults = list(tags or [])

    for file_path in iter_files(target, recursive=recursive):
        if max_files is not None and result.files_seen >= max_files:
            logger.info(f"Ingest hit max_files limit of {max_files}")
            break
        result.files_seen += 1
        try:
            ingested, links = ingest_file(
                file_path,
                root=root,
                store=store,
                project_scope=project_scope,
                tags=tag_defaults,
                source_id=source_id,
            )
            logger.debug(f"Ingested file: {file_path}")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            logger.warning(f"Failed to ingest file {file_path}: {exc}")
            assert result.skipped is not None
            result.skipped.append({"path": str(file_path), "reason": str(exc)})
            continue
        result.files_ingested += 1
        result.nodes_written += 1
        result.relationships_written += 1
        link_buffer.extend((ingested.node_id, link, "references") for link in links)

    for source_node_id, link_title, rel_type in link_buffer:
        ref_id = f"ref:{slugify(link_title)}"
        store.upsert_node(
            node_id=ref_id,
            node_type="Note",
            title=link_title,
            project=project_scope,
            metadata={"reference_only": True},
        )
        store.upsert_relationship(
            source_id=source_node_id,
            target_id=ref_id,
            relationship_type=rel_type,
            confidence=0.6,
            metadata={"source": "markdown-link"},
        )
        result.relationships_written += 1

    result.ingest_run_id = store.record_ingest_run(
        root_path=str(target),
        project=project_scope,
        file_count=result.files_seen,
        node_count=result.nodes_written,
        started_at=started_at,
        metadata={"recursive": recursive},
    )

    logger.info(
        f"Finished ingest. Run ID: {result.ingest_run_id}. "
        f"Seen: {result.files_seen}, Ingested: {result.files_ingested}, "
        f"Skipped: {len(result.skipped or [])}"
    )
    return result.to_dict()


def iter_files(path: Path, *, recursive: bool) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    iterator = path.rglob("*") if recursive else path.iterdir()
    for item in iterator:
        if not item.is_file():
            continue
        if any(part in SKIP_DIRS for part in item.parts):
            continue
        if item.name == ".DS_Store":
            continue
        yield item


def ingest_file(
    file_path: Path,
    *,
    root: Path,
    store: NiklasStore,
    project_scope: str | None,
    tags: Iterable[str],
    source_id: str,
) -> tuple[IngestedFile, list[str]]:
    stat = file_path.stat()
    content_hash = hash_file(file_path)
    ext = file_path.suffix.lower()
    mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    relative_path = safe_relative(file_path, root)
    metadata: dict[str, Any] = {
        "ingested_at": utcnow(),
        "source": "niklas-ingest-v1",
    }
    frontmatter: dict[str, Any] = {}
    extracted_tags = set(tags)
    links: list[str] = []
    content_preview = ""
    summary = ""
    title = file_path.stem

    if is_textual(file_path):
        text = read_text_preview(file_path)
        content_preview = text[:PREVIEW_CHARS]
        if ext in MARKDOWN_EXTENSIONS:
            frontmatter, body = split_frontmatter(text)
            title = str(frontmatter.get("title") or first_markdown_heading(body) or file_path.stem)
            extracted_tags.update(extract_frontmatter_tags(frontmatter))
            extracted_tags.update(extract_hash_tags(body))
            links = extract_wikilinks(body)
            summary = summarize_text(body)
            metadata["frontmatter"] = frontmatter
        else:
            title = file_path.stem
            summary = summarize_text(text) or f"{ext or 'text'} file"
            extracted_tags.update(extract_hash_tags(text))
    else:
        summary = f"{mime_type} asset, {stat.st_size} bytes"

    node_type = infer_node_type(file_path, frontmatter)
    node_id = stable_id("file", str(file_path.resolve(strict=False)), 24)
    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()

    store.upsert_node(
        node_id=node_id,
        node_type=node_type,
        title=title,
        path=relative_path,
        absolute_path=str(file_path.resolve(strict=False)),
        project=project_scope,
        mime_type=mime_type,
        extension=ext,
        content_hash=content_hash,
        size_bytes=stat.st_size,
        modified_at=modified_at,
        summary=summary,
        content_preview=content_preview,
        metadata=metadata,
    )
    store.set_tags(node_id, extracted_tags)
    store.upsert_relationship(
        source_id=node_id,
        target_id=source_id,
        relationship_type="ingested-from-source",
        confidence=1.0,
        metadata={"root": str(root)},
    )
    return IngestedFile(node_id, relative_path, node_type, title, content_hash), links


def is_textual(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    mime_type = mimetypes.guess_type(str(path))[0] or ""
    return mime_type.startswith("text/")


def read_text_preview(path: Path) -> str:
    data = path.read_bytes()[:MAX_TEXT_BYTES]
    return data.decode("utf-8", errors="replace")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end].strip()
    body = text[end + 4 :].lstrip("\n")
    return parse_simple_frontmatter(raw), body


def parse_simple_frontmatter(raw: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            data[key] = items
        else:
            data[key] = value.strip("'\"")
    return data


def extract_frontmatter_tags(frontmatter: dict[str, Any]) -> set[str]:
    raw = frontmatter.get("tags") or frontmatter.get("tag") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in re.split(r"[, ]+", raw) if part.strip()]
    if not isinstance(raw, list):
        return set()
    return {str(tag).strip().lstrip("#") for tag in raw if str(tag).strip()}


def extract_hash_tags(text: str) -> set[str]:
    return set(re.findall(r"(?<!\w)#([A-Za-z0-9][A-Za-z0-9_/-]*)", text))


def extract_wikilinks(text: str) -> list[str]:
    links = []
    for match in re.findall(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", text):
        cleaned = match.strip()
        if cleaned:
            links.append(cleaned)
    return links


def first_markdown_heading(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def summarize_text(text: str) -> str:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line in {"---"}:
            continue
        lines.append(line)
        if len(" ".join(lines)) >= 350:
            break
    return " ".join(lines)[:500]


def infer_node_type(file_path: Path, frontmatter: dict[str, Any]) -> str:
    explicit = str(
        frontmatter.get("niklas_type")
        or frontmatter.get("entity_type")
        or frontmatter.get("type")
        or ""
    ).strip()
    normalized = explicit[:1].upper() + explicit[1:] if explicit else ""
    if normalized in {"Project", "Asset", "Note", "Task", "Skill", "Process", "Source"}:
        return normalized

    parts = {part.lower() for part in file_path.parts}
    if any(part in parts for part in {"tasks", "task", "todos"}):
        return "Task"
    if any(part in parts for part in {"skills", "skill"}):
        return "Skill"
    if any(part in parts for part in {"process", "processes", "runbooks", "runbook"}):
        return "Process"
    if any(part in parts for part in {"sources", "source-registry", "source"}):
        return "Source"
    if file_path.suffix.lower() in MARKDOWN_EXTENSIONS:
        return "Note"
    return "Asset"


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return os.path.basename(path)
