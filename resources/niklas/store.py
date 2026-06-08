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

                CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
                CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project);
                CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
                CREATE INDEX IF NOT EXISTS idx_nodes_hash ON nodes(content_hash);
                CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_id);
                CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_id);
                CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(type);
                CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

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
        out.update(
            {
                "node_count": node_count,
                "relationship_count": rel_count,
                "tag_count": tag_count,
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
