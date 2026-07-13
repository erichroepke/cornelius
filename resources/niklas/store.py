"""SQLite persistence for the Niklas local graph."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


ENTITY_TYPES = {
    "Project",
    "Asset",
    "Note",
    "Task",
    "Skill",
    "Process",
    "Source",
    "Tag",
    "Confidence",
    "Relationship",
    "LinearIssue",
}

RELATION_LINK_SOURCE = "relation-source"
RELATION_LINK_TARGET = "relation-target"
META_RELATION_TYPES = {
    "supports",
    "contradicts",
    "refines",
    "depends-on",
    "generalizes",
    "supersedes",
}

SOURCE_SYNC_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".lrdata",
    ".photoslibrary",
}

DEFAULT_SOURCE_ROOT_ALIASES = {
    "master-140-tb-1": [
        {
            "alias_kind": "local",
            "base_path": "/Volumes/MASTER 140 TB 1",
            "priority": 10,
            "metadata": {"label": "MASTER 140 TB 1 direct mount"},
        },
        {
            "alias_kind": "strada-connect",
            "base_path": "/Volumes/StradaConnect/Erich-M4-Max/MASTER 140 TB 1",
            "priority": 20,
            "metadata": {"label": "MASTER 140 TB 1 through StradaConnect"},
        },
        {
            "alias_kind": "strada",
            "base_path": "strada://Erich-M4-Max/MASTER 140 TB 1",
            "priority": 30,
            "metadata": {"label": "MASTER 140 TB 1 Strada remote locator"},
        },
    ],
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    raw = os.environ.get("NIKLAS_DB_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent / "data" / "niklas.sqlite"


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    return slug.strip("-") or "untitled"


def stable_id(prefix: str, value: str, length: int = 20) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"


def default_metadata(record_kind: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload.setdefault("record_kind", record_kind)
    payload.setdefault("schema", "niklas-sqlite-v1")
    payload.setdefault("write_source", "niklas-store")
    return payload


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    metadata = out.get("metadata_json")
    if isinstance(metadata, str):
        try:
            out["metadata"] = json.loads(metadata) if metadata else {}
        except json.JSONDecodeError:
            out["metadata"] = {}
    out.pop("metadata_json", None)
    tags = out.get("tags")
    if isinstance(tags, str):
        out["tags"] = [t for t in tags.split(",") if t]
    elif tags is None:
        out["tags"] = []
    return out


class NiklasStore:
    """Small SQLite graph store for local Niklas ingest and retrieval."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def connect_readonly(self) -> Iterator[sqlite3.Connection]:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Niklas database does not exist: {self.db_path}")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row["name"] == column for row in rows)

    @classmethod
    def _ensure_column(
        cls,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        column_type: str,
    ) -> None:
        if not cls._column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _register_default_source_root_aliases(self, conn: sqlite3.Connection) -> None:
        for root_id, aliases in DEFAULT_SOURCE_ROOT_ALIASES.items():
            for alias in aliases:
                alias_id = stable_id(
                    "root-alias",
                    f"{root_id}|{alias['base_path']}",
                    24,
                )
                conn.execute(
                    """
                    INSERT INTO source_root_aliases (
                        id, root_id, alias_kind, base_path, priority, computer_name,
                        status, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'known', ?)
                    ON CONFLICT(root_id, base_path) DO UPDATE SET
                        alias_kind = excluded.alias_kind,
                        priority = excluded.priority,
                        computer_name = excluded.computer_name,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        alias_id,
                        root_id,
                        alias["alias_kind"],
                        alias["base_path"],
                        int(alias["priority"]),
                        os.uname().nodename,
                        json.dumps(
                            default_metadata(
                                "source-root-alias",
                                alias.get("metadata") or {},
                            ),
                            sort_keys=True,
                        ),
                    ),
                )

    def schema_present(self) -> bool:
        if not self.db_path.exists():
            return False
        try:
            with self.connect_readonly() as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                ).fetchall()
        except (OSError, sqlite3.Error):
            return False
        names = {row["name"] for row in rows}
        return {"nodes", "relationships", "tags", "ingest_runs"}.issubset(names)

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    path TEXT,
                    absolute_path TEXT,
                    project TEXT,
                    mime_type TEXT,
                    extension TEXT,
                    content_hash TEXT,
                    size_bytes INTEGER,
                    modified_at TEXT,
                    summary TEXT,
                    content_preview TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS relationships (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tags (
                    node_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    PRIMARY KEY (node_id, tag)
                );

                CREATE TABLE IF NOT EXISTS ingest_runs (
                    id TEXT PRIMARY KEY,
                    root_path TEXT NOT NULL,
                    project TEXT,
                    file_count INTEGER NOT NULL,
                    node_count INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS source_assets (
                    asset_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    current_path TEXT NOT NULL,
                    root_id TEXT,
                    relative_path TEXT,
                    project TEXT,
                    node_type TEXT,
                    mime_type TEXT,
                    extension TEXT,
                    content_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS source_path_events (
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    previous_path TEXT,
                    node_id TEXT,
                    content_hash TEXT,
                    size_bytes INTEGER,
                    observed_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS source_root_aliases (
                    id TEXT PRIMARY KEY,
                    root_id TEXT NOT NULL,
                    alias_kind TEXT NOT NULL,
                    base_path TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 100,
                    computer_name TEXT,
                    status TEXT NOT NULL DEFAULT 'known',
                    last_checked_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
                CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project);
                CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
                CREATE INDEX IF NOT EXISTS idx_nodes_hash ON nodes(content_hash);
                CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_id);
                CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_id);
                CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(type);
                CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
                CREATE INDEX IF NOT EXISTS idx_source_assets_node ON source_assets(node_id);
                CREATE INDEX IF NOT EXISTS idx_source_assets_path ON source_assets(current_path);
                CREATE INDEX IF NOT EXISTS idx_source_assets_root_relative ON source_assets(root_id, relative_path);
                CREATE INDEX IF NOT EXISTS idx_source_assets_hash_size ON source_assets(content_hash, size_bytes);
                CREATE INDEX IF NOT EXISTS idx_source_path_events_asset ON source_path_events(asset_id);
                CREATE INDEX IF NOT EXISTS idx_source_path_events_type ON source_path_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_source_root_aliases_root ON source_root_aliases(root_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_source_root_aliases_unique ON source_root_aliases(root_id, base_path);

                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    id,
                    title,
                    summary,
                    content_preview,
                    tags,
                    project
                );
                """
            )
            self._ensure_column(conn, "source_assets", "root_id", "TEXT")
            self._ensure_column(conn, "source_assets", "relative_path", "TEXT")
            self._register_default_source_root_aliases(conn)
            fts_count = conn.execute("SELECT count(*) FROM nodes_fts").fetchone()[0]
            if fts_count == 0:
                conn.execute(
                    """
                    INSERT INTO nodes_fts (id, title, summary, content_preview, tags, project)
                    SELECT n.id, n.title, n.summary, n.content_preview, COALESCE(group_concat(t.tag, ' '), ''), COALESCE(n.project, '')
                    FROM nodes n
                    LEFT JOIN tags t ON t.node_id = n.id
                    GROUP BY n.id
                    """
                )

    def upsert_node(
        self,
        *,
        node_id: str,
        node_type: str,
        title: str,
        path: str | None = None,
        absolute_path: str | None = None,
        project: str | None = None,
        mime_type: str | None = None,
        extension: str | None = None,
        content_hash: str | None = None,
        size_bytes: int | None = None,
        modified_at: str | None = None,
        summary: str | None = None,
        content_preview: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if node_type not in ENTITY_TYPES:
            raise ValueError(f"unsupported Niklas node type: {node_type}")
        now = utcnow()
        payload = {
            "id": node_id,
            "type": node_type,
            "title": title or "Untitled",
            "path": path,
            "absolute_path": absolute_path,
            "project": project,
            "mime_type": mime_type,
            "extension": extension,
            "content_hash": content_hash,
            "size_bytes": size_bytes,
            "modified_at": modified_at,
            "summary": summary,
            "content_preview": content_preview,
            "metadata_json": json.dumps(default_metadata("node", metadata), sort_keys=True),
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO nodes (
                    id, type, title, path, absolute_path, project, mime_type,
                    extension, content_hash, size_bytes, modified_at, summary,
                    content_preview, metadata_json, created_at, updated_at
                )
                VALUES (
                    :id, :type, :title, :path, :absolute_path, :project, :mime_type,
                    :extension, :content_hash, :size_bytes, :modified_at, :summary,
                    :content_preview, :metadata_json, :created_at, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    title = excluded.title,
                    path = excluded.path,
                    absolute_path = excluded.absolute_path,
                    project = excluded.project,
                    mime_type = excluded.mime_type,
                    extension = excluded.extension,
                    content_hash = excluded.content_hash,
                    size_bytes = excluded.size_bytes,
                    modified_at = excluded.modified_at,
                    summary = excluded.summary,
                    content_preview = excluded.content_preview,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            self._update_fts(conn, node_id)
        if project and node_type != "Project":
            project_id = self.ensure_project(project)
            self.upsert_relationship(
                source_id=node_id,
                target_id=project_id,
                relationship_type="belongs-to-project",
                confidence=1.0,
            )
        return self.get_node(node_id) or payload

    def ensure_project(self, project: str) -> str:
        project_id = f"project:{slugify(project)}"
        self.upsert_node(
            node_id=project_id,
            node_type="Project",
            title=project,
            project=project,
            metadata={"source": "niklas-core"},
        )
        return project_id

    def ensure_tag(self, tag: str) -> str:
        clean = tag.strip().lstrip("#")
        tag_id = f"tag:{slugify(clean)}"
        self.upsert_node(
            node_id=tag_id,
            node_type="Tag",
            title=f"#{clean}",
            metadata={"source": "niklas-core"},
        )
        return tag_id

    def set_tags(self, node_id: str, tags: Iterable[str]) -> None:
        clean_tags = sorted({t.strip().lstrip("#") for t in tags if t and t.strip().lstrip("#")})
        with self.connect() as conn:
            conn.execute("DELETE FROM tags WHERE node_id = ?", (node_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO tags(node_id, tag) VALUES (?, ?)",
                [(node_id, tag) for tag in clean_tags],
            )
            self._update_fts(conn, node_id)
        for tag in clean_tags:
            tag_id = self.ensure_tag(tag)
            self.upsert_relationship(
                source_id=node_id,
                target_id=tag_id,
                relationship_type="tagged-with",
                confidence=1.0,
            )

    def _update_fts(self, conn: sqlite3.Connection, node_id: str) -> None:
        row = conn.execute(
            """
            SELECT n.id, n.title, n.summary, n.content_preview, n.project,
                   COALESCE(group_concat(t.tag, ' '), '') AS tags_str
            FROM nodes n
            LEFT JOIN tags t ON t.node_id = n.id
            WHERE n.id = ?
            GROUP BY n.id
            """,
            (node_id,),
        ).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))
        conn.execute(
            """
            INSERT INTO nodes_fts (id, title, summary, content_preview, tags, project)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["title"],
                row["summary"],
                row["content_preview"],
                row["tags_str"],
                row["project"] or "",
            ),
        )

    def upsert_relationship(
        self,
        *,
        source_id: str,
        target_id: str,
        relationship_type: str,
        confidence: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        rel_id = stable_id("rel", f"{source_id}|{relationship_type}|{target_id}", 32)
        payload = {
            "id": rel_id,
            "source_id": source_id,
            "target_id": target_id,
            "type": relationship_type,
            "confidence": float(confidence),
            "metadata_json": json.dumps(default_metadata("relationship", metadata), sort_keys=True),
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO relationships (
                    id, source_id, target_id, type, confidence,
                    metadata_json, created_at, updated_at
                )
                VALUES (
                    :id, :source_id, :target_id, :type, :confidence,
                    :metadata_json, :created_at, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    confidence = excluded.confidence,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
        return payload

    def relation_node_id(
        self,
        *,
        source_id: str,
        target_id: str,
        relation_type: str,
        direction: str = "A->B",
        provenance_scope: str | None = None,
    ) -> str:
        scope = provenance_scope or "default"
        return stable_id(
            "relation",
            f"{source_id}|{relation_type}|{target_id}|{direction}|{scope}",
            32,
        )

    def upsert_relation_node(
        self,
        *,
        source_id: str,
        target_id: str,
        relation_type: str,
        direction: str = "A->B",
        confidence: float = 0.5,
        authority: str | None = None,
        original_type: str | None = None,
        rationale: str | None = None,
        evidence_spans: list[str] | None = None,
        review_state: str = "proposed",
        provenance_run_id: str | None = None,
        provenance_scope: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a first-class relation node between two graph nodes."""
        relation_id = self.relation_node_id(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            direction=direction,
            provenance_scope=provenance_scope,
        )
        relation_metadata = {
            "relation_type": relation_type,
            "direction": direction,
            "confidence": float(confidence),
            "authority": authority,
            "original_type": original_type,
            "evidence_spans": evidence_spans or [],
            "review_state": review_state,
            "provenance_run_id": provenance_run_id,
            "provenance_scope": provenance_scope,
            **(metadata or {}),
        }
        relation_node = self.upsert_node(
            node_id=relation_id,
            node_type="Relationship",
            title=f"{source_id} {relation_type} {target_id}",
            summary=rationale,
            metadata=relation_metadata,
        )
        source_link = self.upsert_relationship(
            source_id=source_id,
            target_id=relation_id,
            relationship_type=RELATION_LINK_SOURCE,
            confidence=1.0,
            metadata={"relation_id": relation_id, "relation_role": "source"},
        )
        target_link = self.upsert_relationship(
            source_id=relation_id,
            target_id=target_id,
            relationship_type=RELATION_LINK_TARGET,
            confidence=1.0,
            metadata={"relation_id": relation_id, "relation_role": "target"},
        )
        return {
            "relation_node": relation_node,
            "source_link": source_link,
            "target_link": target_link,
        }

    def upsert_meta_relation(
        self,
        *,
        source_relation_id: str,
        target_relation_id: str,
        meta_relation_type: str,
        confidence: float = 0.5,
        rationale: str | None = None,
        evidence_spans: list[str] | None = None,
        provenance_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_type = meta_relation_type.strip().lower().replace("_", "-")
        if clean_type not in META_RELATION_TYPES:
            raise ValueError(f"unsupported Niklas meta-relation type: {meta_relation_type}")
        return self.upsert_relationship(
            source_id=source_relation_id,
            target_id=target_relation_id,
            relationship_type=f"relation-{clean_type}",
            confidence=confidence,
            metadata={
                "rationale": rationale,
                "evidence_spans": evidence_spans or [],
                "provenance_run_id": provenance_run_id,
                **(metadata or {}),
            },
        )

    def list_relation_nodes(
        self,
        *,
        relation_type: str | None = None,
        review_state: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self.schema_present():
            return []
        scan_limit = max(int(limit) * 10, int(limit), 100)
        with self.connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT n.*, group_concat(t.tag, ',') AS tags
                FROM nodes n
                LEFT JOIN tags t ON t.node_id = n.id
                WHERE n.type = 'Relationship'
                GROUP BY n.id
                ORDER BY n.updated_at DESC
                LIMIT ?
                """,
                (scan_limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = row_to_dict(row)
            if item is None:
                continue
            metadata = item.get("metadata") or {}
            if relation_type and metadata.get("relation_type") != relation_type:
                continue
            if review_state and metadata.get("review_state") != review_state:
                continue
            out.append(item)
            if len(out) >= int(limit):
                break
        return out

    def record_ingest_run(
        self,
        *,
        root_path: str,
        project: str | None,
        file_count: int,
        node_count: int,
        started_at: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        finished_at = utcnow()
        run_id = stable_id("ingest", f"{root_path}|{started_at}|{finished_at}", 24)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_runs (
                    id, root_path, project, file_count, node_count,
                    started_at, finished_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    root_path,
                    project,
                    file_count,
                    node_count,
                    started_at,
                    finished_at,
                    json.dumps(default_metadata("ingest-run", metadata), sort_keys=True),
                ),
            )
        return run_id

    @staticmethod
    def file_node_id_for_asset(asset_id: str) -> str:
        return stable_id("file", asset_id, 24)

    @staticmethod
    def _source_asset_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        metadata = item.get("metadata_json")
        if isinstance(metadata, str):
            try:
                item["metadata"] = json.loads(metadata) if metadata else {}
            except json.JSONDecodeError:
                item["metadata"] = {}
        item.pop("metadata_json", None)
        return item

    @staticmethod
    def _source_root_alias_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        metadata = item.get("metadata_json")
        if isinstance(metadata, str):
            try:
                item["metadata"] = json.loads(metadata) if metadata else {}
            except json.JSONDecodeError:
                item["metadata"] = {}
        item.pop("metadata_json", None)
        return item

    @staticmethod
    def _source_path_exists(path: str | Path) -> bool:
        candidate = Path(path).expanduser()
        if not candidate.exists():
            return False
        parts = candidate.resolve(strict=False).parts
        if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
            volume_root = Path("/", "Volumes", parts[2])
            if volume_root.exists() and not os.path.ismount(volume_root):
                return False
        return True

    @staticmethod
    def _hash_file(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _last_source_path_event_type(self, conn: sqlite3.Connection, asset_id: str) -> str | None:
        row = conn.execute(
            """
            SELECT event_type
            FROM source_path_events
            WHERE asset_id = ?
            ORDER BY observed_at DESC
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        return row["event_type"] if row is not None else None

    def register_source_root_alias(
        self,
        *,
        root_id: str,
        base_path: str,
        alias_kind: str = "local",
        priority: int = 100,
        computer_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        alias_id = stable_id("root-alias", f"{root_id}|{base_path}", 24)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_root_aliases (
                    id, root_id, alias_kind, base_path, priority, computer_name,
                    status, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, 'known', ?)
                ON CONFLICT(root_id, base_path) DO UPDATE SET
                    alias_kind = excluded.alias_kind,
                    priority = excluded.priority,
                    computer_name = excluded.computer_name,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json
                """,
                (
                    alias_id,
                    root_id,
                    alias_kind,
                    base_path,
                    int(priority),
                    computer_name or os.uname().nodename,
                    json.dumps(
                        default_metadata("source-root-alias", metadata),
                        sort_keys=True,
                    ),
                ),
            )
            row = conn.execute(
                "SELECT * FROM source_root_aliases WHERE id = ?",
                (alias_id,),
            ).fetchone()
        return self._source_root_alias_to_dict(row) or {}

    def list_source_root_aliases(self, root_id: str | None = None) -> list[dict[str, Any]]:
        if not self.schema_present():
            return []
        with self.connect_readonly() as conn:
            if not self._table_exists(conn, "source_root_aliases"):
                return []
            if root_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM source_root_aliases
                    WHERE root_id = ?
                    ORDER BY priority, alias_kind, base_path
                    """,
                    (root_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM source_root_aliases
                    ORDER BY root_id, priority, alias_kind, base_path
                    """
                ).fetchall()
        return [item for row in rows if (item := self._source_root_alias_to_dict(row)) is not None]

    @staticmethod
    def _is_uri(value: str) -> bool:
        return "://" in value

    @staticmethod
    def _uri_join(base_uri: str, relative_path: str) -> str:
        return f"{base_uri.rstrip('/')}/{relative_path.lstrip('/')}"

    def _refresh_source_root_aliases(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        if not self._table_exists(conn, "source_root_aliases"):
            return []
        now = utcnow()
        rows = conn.execute(
            """
            SELECT *
            FROM source_root_aliases
            ORDER BY root_id, priority, alias_kind, base_path
            """
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            alias = self._source_root_alias_to_dict(row) or {}
            base_path = str(alias.get("base_path") or "")
            if self._is_uri(base_path):
                status = "remote-reference"
            else:
                status = "available" if self._source_path_exists(base_path) else "missing"
            conn.execute(
                """
                UPDATE source_root_aliases
                SET status = ?, last_checked_at = ?
                WHERE id = ?
                """,
                (status, now, alias["id"]),
            )
            alias["status"] = status
            alias["last_checked_at"] = now
            out.append(alias)
        return out

    def _infer_source_root(
        self,
        conn: sqlite3.Connection,
        absolute_path: str,
    ) -> tuple[str | None, str | None]:
        current = Path(absolute_path).expanduser().resolve(strict=False)
        if not self._table_exists(conn, "source_root_aliases"):
            return None, None
        rows = conn.execute(
            """
            SELECT *
            FROM source_root_aliases
            ORDER BY length(base_path) DESC, priority
            """
        ).fetchall()
        for row in rows:
            base_raw = row["base_path"]
            if self._is_uri(base_raw):
                continue
            base = Path(base_raw).expanduser().resolve(strict=False)
            try:
                relative = current.relative_to(base)
            except ValueError:
                continue
            return row["root_id"], str(relative)
        return None, None

    def _resolve_asset_locations(
        self,
        conn: sqlite3.Connection,
        asset: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None, str]:
        locations: list[dict[str, Any]] = []
        lookup_steps: list[dict[str, Any]] = []
        preferred_uri: str | None = None
        resolution_status = "missing"

        recorded_path = str(asset.get("current_path") or "")
        if recorded_path:
            exists = self._source_path_exists(recorded_path)
            locations.append(
                {
                    "kind": "recorded",
                    "uri": recorded_path,
                    "exists": exists,
                    "priority": 0,
                }
            )
            lookup_steps.append(
                {
                    "step": "recorded-path",
                    "uri": recorded_path,
                    "status": "available" if exists else "missing",
                }
            )
            if exists:
                preferred_uri = recorded_path
                resolution_status = "local-available"

        root_id = asset.get("root_id")
        relative_path = asset.get("relative_path")
        if root_id and relative_path and self._table_exists(conn, "source_root_aliases"):
            rows = conn.execute(
                """
                SELECT *
                FROM source_root_aliases
                WHERE root_id = ?
                ORDER BY priority, alias_kind, base_path
                """,
                (root_id,),
            ).fetchall()
            for row in rows:
                alias = self._source_root_alias_to_dict(row) or {}
                base_path = str(alias.get("base_path") or "")
                alias_kind = str(alias.get("alias_kind") or "alias")
                if self._is_uri(base_path):
                    uri = self._uri_join(base_path, relative_path)
                    exists = None
                    status = "remote-reference"
                    if preferred_uri is None:
                        preferred_uri = uri
                        resolution_status = (
                            "strada-remote-reference"
                            if alias_kind.startswith("strada")
                            else "remote-reference"
                        )
                else:
                    uri = str(Path(base_path).expanduser().resolve(strict=False) / relative_path)
                    exists = self._source_path_exists(uri)
                    status = "available" if exists else "missing"
                    if exists and preferred_uri is None:
                        preferred_uri = uri
                        resolution_status = (
                            "strada-available"
                            if alias_kind.startswith("strada")
                            else "local-available"
                        )
                locations.append(
                    {
                        "kind": alias_kind,
                        "root_id": root_id,
                        "relative_path": relative_path,
                        "uri": uri,
                        "exists": exists,
                        "priority": alias.get("priority"),
                        "computer_name": alias.get("computer_name"),
                    }
                )
                lookup_steps.append(
                    {
                        "step": f"{alias_kind}-alias",
                        "uri": uri,
                        "status": status,
                    }
                )

        if preferred_uri is None and not lookup_steps:
            resolution_status = "unresolved-no-location"
        return locations, lookup_steps, preferred_uri, resolution_status

    def _iter_bounded_source_files(
        self,
        root: Path,
        *,
        max_depth: int,
        max_files: int,
    ) -> tuple[list[Path], bool]:
        if not self._source_path_exists(root) or not root.is_dir():
            return [], False
        files: list[Path] = []
        truncated = False
        stack: list[tuple[Path, int]] = [(root, 0)]
        inspected = 0
        seen_dirs: set[str] = set()
        while stack and inspected < max_files:
            directory, depth = stack.pop(0)
            directory_key = str(directory.resolve(strict=False))
            if directory_key in seen_dirs:
                continue
            seen_dirs.add(directory_key)
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name)
            except OSError:
                continue
            for item in entries:
                if item.name in SOURCE_SYNC_SKIP_DIRS:
                    continue
                try:
                    if item.is_file():
                        inspected += 1
                        files.append(item)
                        if inspected >= max_files:
                            truncated = True
                            break
                    elif item.is_dir() and depth < max_depth:
                        stack.append((item, depth + 1))
                except OSError:
                    continue
            if truncated:
                break
        return files, truncated

    def _candidate_paths_for_missing_asset(
        self,
        conn: sqlite3.Connection,
        asset: dict[str, Any],
        *,
        scan_depth: int,
        max_candidates: int,
    ) -> tuple[list[Path], bool]:
        candidates: list[Path] = []
        seen: set[str] = set()
        truncated = False

        def add_candidate(path: Path) -> None:
            key = str(path.expanduser().resolve(strict=False))
            if key not in seen:
                seen.add(key)
                candidates.append(Path(key))

        root_id = asset.get("root_id")
        relative_path = asset.get("relative_path")
        if root_id and relative_path and self._table_exists(conn, "source_root_aliases"):
            rows = conn.execute(
                """
                SELECT *
                FROM source_root_aliases
                WHERE root_id = ?
                ORDER BY priority, alias_kind, base_path
                """,
                (root_id,),
            ).fetchall()
            relative = Path(str(relative_path))
            relative_parent = relative.parent if str(relative.parent) != "." else Path()
            for row in rows:
                base_path = row["base_path"]
                if self._is_uri(base_path):
                    continue
                direct = Path(base_path).expanduser().resolve(strict=False) / relative
                if self._source_path_exists(direct):
                    add_candidate(direct)
                nearby_root = Path(base_path).expanduser().resolve(strict=False) / relative_parent
                files, was_truncated = self._iter_bounded_source_files(
                    nearby_root,
                    max_depth=scan_depth,
                    max_files=max_candidates,
                )
                truncated = truncated or was_truncated
                for file_path in files:
                    add_candidate(file_path)

        current_path = asset.get("current_path")
        if current_path:
            parent = Path(str(current_path)).expanduser().resolve(strict=False).parent
            files, was_truncated = self._iter_bounded_source_files(
                parent,
                max_depth=scan_depth,
                max_files=max_candidates,
            )
            truncated = truncated or was_truncated
            for file_path in files:
                add_candidate(file_path)

        return candidates, truncated

    def _matching_source_candidate(
        self,
        conn: sqlite3.Connection,
        asset: dict[str, Any],
        *,
        scan_depth: int,
        max_candidates: int,
    ) -> tuple[str | None, bool, int]:
        expected_size = int(asset["size_bytes"])
        expected_hash = str(asset["content_hash"])
        candidates, truncated = self._candidate_paths_for_missing_asset(
            conn,
            asset,
            scan_depth=scan_depth,
            max_candidates=max_candidates,
        )
        checked = 0
        for candidate in candidates:
            try:
                if not candidate.is_file():
                    continue
                stat = candidate.stat()
            except OSError:
                continue
            checked += 1
            if stat.st_size != expected_size:
                continue
            try:
                if self._hash_file(candidate) == expected_hash:
                    return str(candidate.resolve(strict=False)), truncated, checked
            except OSError:
                continue
        return None, truncated, checked

    def _update_asset_node_path(
        self,
        conn: sqlite3.Connection,
        *,
        asset: dict[str, Any],
        new_path: str,
        root_id: str | None,
        relative_path: str | None,
        now: str,
    ) -> None:
        conn.execute(
            """
            UPDATE source_assets
            SET current_path = ?, root_id = ?, relative_path = ?,
                status = 'active', last_seen_at = ?, metadata_json = ?
            WHERE asset_id = ?
            """,
            (
                new_path,
                root_id,
                relative_path,
                now,
                json.dumps(
                    default_metadata(
                        "source-asset",
                        {"resolution": "moved", "updated_by": "niklas-sync"},
                    ),
                    sort_keys=True,
                ),
                asset["asset_id"],
            ),
        )
        node = conn.execute(
            "SELECT path FROM nodes WHERE id = ?",
            (asset["node_id"],),
        ).fetchone()
        node_path = relative_path or (node["path"] if node is not None else None)
        conn.execute(
            """
            UPDATE nodes
            SET absolute_path = ?, path = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_path, node_path, now, asset["node_id"]),
        )

    def sync_source_assets_once(
        self,
        *,
        root_id: str | None = None,
        limit: int | None = None,
        scan_depth: int = 1,
        max_candidates: int = 500,
        verify_existing_hashes: bool = False,
        record_verified: bool = False,
        event_limit: int = 50,
    ) -> dict[str, Any]:
        """Verify indexed source assets and repair moved paths without broad archive crawling."""
        self.initialize()
        now = utcnow()
        summary: dict[str, Any] = {
            "db_path": str(self.db_path),
            "started_at": now,
            "finished_at": None,
            "root_id": root_id,
            "assets_checked": 0,
            "aliases_checked": 0,
            "available": 0,
            "verified": 0,
            "moved": 0,
            "missing": 0,
            "changed": 0,
            "events_recorded": 0,
            "candidate_files_checked": 0,
            "truncated_scans": 0,
            "events": [],
        }

        def remember_event(event: dict[str, Any]) -> None:
            summary["events_recorded"] += 1
            if len(summary["events"]) < event_limit:
                summary["events"].append(event)

        with self.connect() as conn:
            aliases = self._refresh_source_root_aliases(conn)
            summary["aliases_checked"] = len(aliases)
            if root_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM source_assets
                    WHERE root_id = ?
                    ORDER BY last_seen_at DESC
                    LIMIT COALESCE(?, -1)
                    """,
                    (root_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM source_assets
                    ORDER BY last_seen_at DESC
                    LIMIT COALESCE(?, -1)
                    """,
                    (limit,),
                ).fetchall()

            for row in rows:
                asset = self._source_asset_to_dict(row) or {}
                if not asset:
                    continue
                summary["assets_checked"] += 1
                asset_id = asset["asset_id"]
                current_path = str(asset.get("current_path") or "")
                current_exists = bool(current_path) and self._source_path_exists(current_path)
                if current_exists:
                    if not verify_existing_hashes and not record_verified:
                        summary["available"] += 1
                        conn.execute(
                            """
                            UPDATE source_assets
                            SET status = 'active', last_seen_at = ?
                            WHERE asset_id = ?
                            """,
                            (now, asset_id),
                        )
                        continue
                    try:
                        stat = Path(current_path).stat()
                        content_hash = self._hash_file(current_path)
                    except OSError:
                        current_exists = False
                    else:
                        if stat.st_size == asset["size_bytes"] and content_hash == asset["content_hash"]:
                            summary["verified"] += 1
                            conn.execute(
                                """
                                UPDATE source_assets
                                SET status = 'active', last_seen_at = ?
                                WHERE asset_id = ?
                                """,
                                (now, asset_id),
                            )
                            if record_verified and self._last_source_path_event_type(conn, asset_id) != "verified":
                                event = self._insert_source_path_event(
                                    conn,
                                    asset_id=asset_id,
                                    event_type="verified",
                                    path=current_path,
                                    node_id=asset.get("node_id"),
                                    content_hash=asset.get("content_hash"),
                                    size_bytes=asset.get("size_bytes"),
                                    observed_at=now,
                                    metadata={"source": "niklas-sync"},
                                )
                                remember_event(event)
                            continue
                        summary["changed"] += 1
                        conn.execute(
                            """
                            UPDATE source_assets
                            SET content_hash = ?, size_bytes = ?, status = 'active',
                                last_seen_at = ?, metadata_json = ?
                            WHERE asset_id = ?
                            """,
                            (
                                content_hash,
                                stat.st_size,
                                now,
                                json.dumps(
                                    default_metadata(
                                        "source-asset",
                                        {
                                            "resolution": "observed-content-change",
                                            "updated_by": "niklas-sync",
                                        },
                                    ),
                                    sort_keys=True,
                                ),
                                asset_id,
                            ),
                        )
                        event = self._insert_source_path_event(
                            conn,
                            asset_id=asset_id,
                            event_type="observed",
                            path=current_path,
                            node_id=asset.get("node_id"),
                            content_hash=content_hash,
                            size_bytes=stat.st_size,
                            observed_at=now,
                            metadata={"resolution": "observed-content-change"},
                        )
                        remember_event(event)
                        continue

                new_path, truncated, checked = self._matching_source_candidate(
                    conn,
                    asset,
                    scan_depth=scan_depth,
                    max_candidates=max_candidates,
                )
                summary["candidate_files_checked"] += checked
                if truncated:
                    summary["truncated_scans"] += 1
                if new_path:
                    new_root_id, new_relative_path = self._infer_source_root(conn, new_path)
                    if new_root_id is None:
                        new_root_id = asset.get("root_id")
                    if new_relative_path is None:
                        new_relative_path = asset.get("relative_path")
                    self._update_asset_node_path(
                        conn,
                        asset=asset,
                        new_path=new_path,
                        root_id=new_root_id,
                        relative_path=new_relative_path,
                        now=now,
                    )
                    event = self._insert_source_path_event(
                        conn,
                        asset_id=asset_id,
                        event_type="moved",
                        path=new_path,
                        previous_path=current_path or None,
                        node_id=asset.get("node_id"),
                        content_hash=asset.get("content_hash"),
                        size_bytes=asset.get("size_bytes"),
                        observed_at=now,
                        metadata={"source": "niklas-sync"},
                    )
                    summary["moved"] += 1
                    remember_event(event)
                    continue

                summary["missing"] += 1
                conn.execute(
                    """
                    UPDATE source_assets
                    SET status = 'missing', last_seen_at = ?, metadata_json = ?
                    WHERE asset_id = ?
                    """,
                    (
                        now,
                        json.dumps(
                            default_metadata(
                                "source-asset",
                                {"resolution": "missing", "updated_by": "niklas-sync"},
                            ),
                            sort_keys=True,
                        ),
                        asset_id,
                    ),
                )
                if self._last_source_path_event_type(conn, asset_id) != "missing":
                    event = self._insert_source_path_event(
                        conn,
                        asset_id=asset_id,
                        event_type="missing",
                        path=current_path or "<unknown>",
                        node_id=asset.get("node_id"),
                        content_hash=asset.get("content_hash"),
                        size_bytes=asset.get("size_bytes"),
                        observed_at=now,
                        metadata={"source": "niklas-sync"},
                    )
                    remember_event(event)

        summary["finished_at"] = utcnow()
        return summary

    def _insert_source_path_event(
        self,
        conn: sqlite3.Connection,
        *,
        asset_id: str,
        event_type: str,
        path: str,
        previous_path: str | None = None,
        node_id: str | None = None,
        content_hash: str | None = None,
        size_bytes: int | None = None,
        observed_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        observed = observed_at or utcnow()
        event_id = stable_id(
            "path-event",
            f"{asset_id}|{event_type}|{path}|{previous_path or ''}|{observed}",
            32,
        )
        payload = {
            "id": event_id,
            "asset_id": asset_id,
            "event_type": event_type,
            "path": path,
            "previous_path": previous_path,
            "node_id": node_id,
            "content_hash": content_hash,
            "size_bytes": size_bytes,
            "observed_at": observed,
            "metadata_json": json.dumps(
                default_metadata("source-path-event", metadata), sort_keys=True
            ),
        }
        conn.execute(
            """
            INSERT INTO source_path_events (
                id, asset_id, event_type, path, previous_path, node_id,
                content_hash, size_bytes, observed_at, metadata_json
            )
            VALUES (
                :id, :asset_id, :event_type, :path, :previous_path, :node_id,
                :content_hash, :size_bytes, :observed_at, :metadata_json
            )
            """,
            payload,
        )
        payload["metadata"] = json.loads(payload.pop("metadata_json"))
        return payload

    def resolve_source_asset_for_file(
        self,
        *,
        absolute_path: str,
        content_hash: str,
        size_bytes: int,
        node_type: str,
        project: str | None = None,
        mime_type: str | None = None,
        extension: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a file observation to a stable source asset and node id."""
        current_path = str(Path(absolute_path).expanduser().resolve(strict=False))
        now = utcnow()
        with self.connect() as conn:
            root_id, relative_path = self._infer_source_root(conn, current_path)
            exact = conn.execute(
                "SELECT * FROM source_assets WHERE current_path = ? ORDER BY last_seen_at DESC LIMIT 1",
                (current_path,),
            ).fetchone()
            if exact is not None:
                asset_id = exact["asset_id"]
                node_id = exact["node_id"] or self.file_node_id_for_asset(asset_id)
                event_type = (
                    "verified"
                    if exact["content_hash"] == content_hash and exact["size_bytes"] == size_bytes
                    else "observed"
                )
                conn.execute(
                    """
                    UPDATE source_assets
                    SET node_id = ?, root_id = ?, relative_path = ?, project = ?,
                        node_type = ?, mime_type = ?, extension = ?,
                        content_hash = ?, size_bytes = ?,
                        status = 'active', last_seen_at = ?,
                        metadata_json = ?
                    WHERE asset_id = ?
                    """,
                    (
                        node_id,
                        root_id,
                        relative_path,
                        project,
                        node_type,
                        mime_type,
                        extension,
                        content_hash,
                        size_bytes,
                        now,
                        json.dumps(
                            default_metadata(
                                "source-asset",
                                {"resolution": event_type, "updated_by": "niklas-ingest"},
                            ),
                            sort_keys=True,
                        ),
                        asset_id,
                    ),
                )
                self._insert_source_path_event(
                    conn,
                    asset_id=asset_id,
                    event_type=event_type,
                    path=current_path,
                    node_id=node_id,
                    content_hash=content_hash,
                    size_bytes=size_bytes,
                    observed_at=now,
                )
                asset = conn.execute(
                    "SELECT * FROM source_assets WHERE asset_id = ?", (asset_id,)
                ).fetchone()
                out = self._source_asset_to_dict(asset) or {}
                out["resolution_event"] = event_type
                return out

            candidates = conn.execute(
                """
                SELECT *
                FROM source_assets
                WHERE content_hash = ? AND size_bytes = ?
                ORDER BY last_seen_at DESC
                """,
                (content_hash, size_bytes),
            ).fetchall()
            for candidate in candidates:
                previous_path = candidate["current_path"]
                if previous_path and not Path(previous_path).exists():
                    asset_id = candidate["asset_id"]
                    node_id = candidate["node_id"] or self.file_node_id_for_asset(asset_id)
                    conn.execute(
                        """
                        UPDATE source_assets
                        SET node_id = ?, current_path = ?, root_id = ?, relative_path = ?,
                            project = ?, node_type = ?, mime_type = ?, extension = ?,
                            status = 'active',
                            last_seen_at = ?, metadata_json = ?
                        WHERE asset_id = ?
                        """,
                        (
                            node_id,
                            current_path,
                            root_id,
                            relative_path,
                            project,
                            node_type,
                            mime_type,
                            extension,
                            now,
                            json.dumps(
                                default_metadata(
                                    "source-asset",
                                    {"resolution": "moved", "updated_by": "niklas-ingest"},
                                ),
                                sort_keys=True,
                            ),
                            asset_id,
                        ),
                    )
                    self._insert_source_path_event(
                        conn,
                        asset_id=asset_id,
                        event_type="moved",
                        path=current_path,
                        previous_path=previous_path,
                        node_id=node_id,
                        content_hash=content_hash,
                        size_bytes=size_bytes,
                        observed_at=now,
                    )
                    asset = conn.execute(
                        "SELECT * FROM source_assets WHERE asset_id = ?", (asset_id,)
                    ).fetchone()
                    out = self._source_asset_to_dict(asset) or {}
                    out["resolution_event"] = "moved"
                    return out

            copy_source = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate["current_path"] and Path(candidate["current_path"]).exists()
                ),
                None,
            )
            event_type = "copy-candidate" if copy_source is not None else "observed"
            asset_id = stable_id("asset", f"{current_path}|{content_hash}|{size_bytes}", 24)
            node_id = self.file_node_id_for_asset(asset_id)
            event_metadata: dict[str, Any] = {}
            if copy_source is not None:
                event_metadata = {
                    "copy_source_asset_id": copy_source["asset_id"],
                    "copy_source_path": copy_source["current_path"],
                }
            conn.execute(
                """
                INSERT INTO source_assets (
                    asset_id, node_id, current_path, root_id, relative_path, project,
                    node_type, mime_type, extension, content_hash, size_bytes, status,
                    first_seen_at, last_seen_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    node_id = excluded.node_id,
                    current_path = excluded.current_path,
                    root_id = excluded.root_id,
                    relative_path = excluded.relative_path,
                    project = excluded.project,
                    node_type = excluded.node_type,
                    mime_type = excluded.mime_type,
                    extension = excluded.extension,
                    content_hash = excluded.content_hash,
                    size_bytes = excluded.size_bytes,
                    status = excluded.status,
                    last_seen_at = excluded.last_seen_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    asset_id,
                    node_id,
                    current_path,
                    root_id,
                    relative_path,
                    project,
                    node_type,
                    mime_type,
                    extension,
                    content_hash,
                    size_bytes,
                    now,
                    now,
                    json.dumps(
                        default_metadata(
                            "source-asset",
                            {
                                "resolution": event_type,
                                "created_by": "niklas-ingest",
                                **event_metadata,
                            },
                        ),
                        sort_keys=True,
                    ),
                ),
            )
            self._insert_source_path_event(
                conn,
                asset_id=asset_id,
                event_type=event_type,
                path=current_path,
                previous_path=copy_source["current_path"] if copy_source is not None else None,
                node_id=node_id,
                content_hash=content_hash,
                size_bytes=size_bytes,
                observed_at=now,
                metadata=event_metadata,
            )
            asset = conn.execute("SELECT * FROM source_assets WHERE asset_id = ?", (asset_id,)).fetchone()
            out = self._source_asset_to_dict(asset) or {}
            out["resolution_event"] = event_type
            return out

    def get_source_asset_events(self, asset_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if not self.schema_present():
            return []
        with self.connect_readonly() as conn:
            if not self._table_exists(conn, "source_path_events"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM source_path_events
                WHERE asset_id = ?
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                (asset_id, int(limit)),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            events.append(item)
        return events

    def locate_source_asset(self, identifier: str, *, event_limit: int = 10) -> dict[str, Any] | None:
        if not self.schema_present():
            return None
        lookup = identifier.strip()
        if not lookup:
            return None
        with self.connect_readonly() as conn:
            if not self._table_exists(conn, "source_assets"):
                return None
            row = conn.execute(
                "SELECT * FROM source_assets WHERE asset_id = ?",
                (lookup,),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM source_assets WHERE node_id = ?",
                    (lookup,),
                ).fetchone()
            if row is None:
                node = conn.execute("SELECT metadata_json FROM nodes WHERE id = ?", (lookup,)).fetchone()
                if node is not None:
                    try:
                        metadata = json.loads(node["metadata_json"] or "{}")
                    except json.JSONDecodeError:
                        metadata = {}
                    source_asset_id = metadata.get("source_asset_id")
                    if source_asset_id:
                        row = conn.execute(
                            "SELECT * FROM source_assets WHERE asset_id = ?",
                            (source_asset_id,),
                        ).fetchone()
            if row is None:
                path_candidates = [lookup]
                try:
                    path_candidates.append(str(Path(lookup).expanduser().resolve(strict=False)))
                except (OSError, RuntimeError):
                    pass
                for candidate in dict.fromkeys(path_candidates):
                    row = conn.execute(
                        "SELECT * FROM source_assets WHERE current_path = ?",
                        (candidate,),
                    ).fetchone()
                    if row is not None:
                        break
        asset = self._source_asset_to_dict(row)
        if asset is None:
            return None
        with self.connect_readonly() as conn:
            locations, lookup_steps, preferred_uri, resolution_status = self._resolve_asset_locations(
                conn,
                asset,
            )
        asset["locations"] = locations
        asset["lookup_steps"] = lookup_steps
        asset["preferred_uri"] = preferred_uri
        asset["resolution_status"] = resolution_status
        asset["local_path"] = next(
            (
                location["uri"]
                for location in locations
                if location.get("exists") is True
                and not str(location.get("kind") or "").startswith("strada")
            ),
            None,
        )
        asset["strada_path"] = next(
            (
                location["uri"]
                for location in locations
                if str(location.get("kind") or "").startswith("strada")
                and location.get("exists") is True
            ),
            None,
        )
        asset["events"] = self.get_source_asset_events(asset["asset_id"], limit=event_limit)
        return asset

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        if not self.schema_present():
            return None
        with self.connect_readonly() as conn:
            row = conn.execute(
                """
                SELECT n.*, group_concat(t.tag, ',') AS tags
                FROM nodes n
                LEFT JOIN tags t ON t.node_id = n.id
                WHERE n.id = ?
                GROUP BY n.id
                """,
                (node_id,),
            ).fetchone()
        return row_to_dict(row)

    def get_relationships_for_nodes(self, node_ids: Iterable[str], limit: int = 100) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(node_ids))
        if not ids or not self.schema_present():
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.connect_readonly() as conn:
            rows = conn.execute(
                f"""
                SELECT r.*, s.title AS source_title, t.title AS target_title
                FROM relationships r
                LEFT JOIN nodes s ON s.id = r.source_id
                LEFT JOIN nodes t ON t.id = r.target_id
                WHERE r.source_id IN ({placeholders}) OR r.target_id IN ({placeholders})
                ORDER BY r.confidence DESC, r.updated_at DESC
                LIMIT ?
                """,
                [*ids, *ids, int(limit)],
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            out.append(item)
        return out

    def search_nodes(
        self,
        query: str,
        *,
        project_scope: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not self.schema_present():
            return []
        terms = [t for t in re.findall(r"[a-z0-9][a-z0-9_-]*", query.lower()) if len(t) > 1]
        with self.connect_readonly() as conn:
            use_fts = bool(terms) and self._table_exists(conn, "nodes_fts")
            if use_fts:
                clean_query = " OR ".join(f'"{t}"*' for t in terms)
                if project_scope:
                    rows = conn.execute(
                        """
                        SELECT n.*, group_concat(t.tag, ',') AS tags
                        FROM nodes n
                        JOIN nodes_fts fts ON fts.id = n.id
                        LEFT JOIN tags t ON t.node_id = n.id
                        WHERE fts.nodes_fts MATCH ? AND (n.project = ? OR n.id = ?)
                        GROUP BY n.id
                        """,
                        (clean_query, project_scope, f"project:{slugify(project_scope)}"),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT n.*, group_concat(t.tag, ',') AS tags
                        FROM nodes n
                        JOIN nodes_fts fts ON fts.id = n.id
                        LEFT JOIN tags t ON t.node_id = n.id
                        WHERE fts.nodes_fts MATCH ?
                        GROUP BY n.id
                        """,
                        (clean_query,),
                    ).fetchall()
            else:
                if project_scope:
                    rows = conn.execute(
                        """
                        SELECT n.*, group_concat(t.tag, ',') AS tags
                        FROM nodes n
                        LEFT JOIN tags t ON t.node_id = n.id
                        WHERE n.project = ? OR n.id = ?
                        GROUP BY n.id
                        """,
                        (project_scope, f"project:{slugify(project_scope)}"),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT n.*, group_concat(t.tag, ',') AS tags
                        FROM nodes n
                        LEFT JOIN tags t ON t.node_id = n.id
                        GROUP BY n.id
                        """
                    ).fetchall()

        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            item = row_to_dict(row)
            if item is None:
                continue
            score = self._score_node(item, terms)
            if score > 0 or not terms:
                item["score"] = score
                scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].get("updated_at") or ""), reverse=True)
        return [item for _, item in scored[: max(1, int(limit))]]

    @staticmethod
    def _score_node(node: dict[str, Any], terms: list[str]) -> int:
        if not terms:
            return 1
        fields = {
            "title": str(node.get("title") or "").lower(),
            "path": str(node.get("path") or "").lower(),
            "summary": str(node.get("summary") or "").lower(),
            "content_preview": str(node.get("content_preview") or "").lower(),
            "tags": " ".join(node.get("tags") or []).lower(),
            "project": str(node.get("project") or "").lower(),
            "type": str(node.get("type") or "").lower(),
        }
        score = 0
        for term in terms:
            if term in fields["title"]:
                score += 8
            if term in fields["tags"]:
                score += 5
            if term in fields["project"] or term in fields["type"]:
                score += 3
            if term in fields["path"]:
                score += 2
            if term in fields["summary"]:
                score += 2
            if term in fields["content_preview"]:
                score += 1
        return score

    def find_duplicates(
        self,
        *,
        project_scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self.schema_present():
            return []
        params: list[Any] = []
        where = "WHERE content_hash IS NOT NULL AND content_hash != ''"
        if project_scope:
            where += " AND project = ?"
            params.append(project_scope)
        with self.connect_readonly() as conn:
            groups = conn.execute(
                f"""
                SELECT content_hash, COUNT(*) AS n
                FROM nodes
                {where}
                GROUP BY content_hash
                HAVING n > 1
                ORDER BY n DESC
                LIMIT ?
                """,
                [*params, int(limit)],
            ).fetchall()
            out: list[dict[str, Any]] = []
            for group in groups:
                rows = conn.execute(
                    """
                    SELECT id, type, title, path, absolute_path, project, size_bytes, modified_at
                    FROM nodes
                    WHERE content_hash = ?
                    ORDER BY path
                    """,
                    (group["content_hash"],),
                ).fetchall()
                out.append(
                    {
                        "kind": "exact-content-hash",
                        "content_hash": group["content_hash"],
                        "count": group["n"],
                        "suggestion": "Review these files as duplicate work or mirrored assets.",
                        "nodes": [dict(row) for row in rows],
                    }
                )
        return out

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "schema_present": self.schema_present(),
            "node_count": 0,
            "relationship_count": 0,
            "tag_count": 0,
            "source_asset_count": 0,
            "source_path_event_count": 0,
            "source_root_alias_count": 0,
            "nodes_by_type": {},
            "recent_ingest_runs": [],
        }
        if not out["schema_present"]:
            return out
        with self.connect_readonly() as conn:
            node_count = conn.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()["n"]
            rel_count = conn.execute("SELECT COUNT(*) AS n FROM relationships").fetchone()["n"]
            tag_count = conn.execute("SELECT COUNT(DISTINCT tag) AS n FROM tags").fetchone()["n"]
            by_type = conn.execute(
                "SELECT type, COUNT(*) AS n FROM nodes GROUP BY type ORDER BY n DESC"
            ).fetchall()
            runs = conn.execute(
                "SELECT * FROM ingest_runs ORDER BY finished_at DESC LIMIT 5"
            ).fetchall()
            source_asset_count = (
                conn.execute("SELECT COUNT(*) AS n FROM source_assets").fetchone()["n"]
                if self._table_exists(conn, "source_assets")
                else 0
            )
            source_path_event_count = (
                conn.execute("SELECT COUNT(*) AS n FROM source_path_events").fetchone()["n"]
                if self._table_exists(conn, "source_path_events")
                else 0
            )
            source_root_alias_count = (
                conn.execute("SELECT COUNT(*) AS n FROM source_root_aliases").fetchone()["n"]
                if self._table_exists(conn, "source_root_aliases")
                else 0
            )
        out.update(
            {
                "node_count": node_count,
                "relationship_count": rel_count,
                "tag_count": tag_count,
                "source_asset_count": source_asset_count,
                "source_path_event_count": source_path_event_count,
                "source_root_alias_count": source_root_alias_count,
                "nodes_by_type": {row["type"]: row["n"] for row in by_type},
                "recent_ingest_runs": [dict(row) for row in runs],
            }
        )
        return out

    def link_linear_issue(
        self,
        *,
        asset_node_id: str,
        issue_id: str,
        issue_identifier: str | None = None,
        issue_title: str | None = None,
        issue_url: str | None = None,
        relationship_type: str = "linked-to-linear-issue",
    ) -> dict[str, Any]:
        issue_node_id = f"linear:{issue_identifier or issue_id}"
        issue_node = self.upsert_node(
            node_id=issue_node_id,
            node_type="LinearIssue",
            title=issue_title or issue_identifier or issue_id,
            metadata={"linear_id": issue_id, "identifier": issue_identifier, "url": issue_url},
        )
        rel = self.upsert_relationship(
            source_id=asset_node_id,
            target_id=issue_node_id,
            relationship_type=relationship_type,
            confidence=1.0,
            metadata={"source": "linear_link_asset"},
        )
        return {"issue_node": issue_node, "relationship": rel}
