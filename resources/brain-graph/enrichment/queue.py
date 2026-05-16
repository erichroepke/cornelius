"""SQLite queue + proposal tracking for the enrichment orchestrator.

Schema:
- `batches` — units of work (one anchor + 20 candidates per row)
- `proposals` — individual edge proposals (with deterministic IDs)
- `audit` — every status transition for forensic trail

The deterministic proposal ID `sha1(from || ">" || edge_type || ">" || to)`
makes re-runs idempotent at the data layer — running the orchestrator twice
cannot create duplicate proposals.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def proposal_id(from_id: str, edge_type: str, to_id: str) -> str:
    """Deterministic ID for a proposed edge. Re-runs collapse to same row."""
    raw = f"{from_id}>{edge_type}>{to_id}".encode()
    return hashlib.sha1(raw).hexdigest()


def batch_id(anchor_id: str, snapshot_ts: str) -> str:
    """Deterministic ID for a (anchor, snapshot) batch. Re-bootstraps don't double-enqueue."""
    raw = f"{anchor_id}@{snapshot_ts}".encode()
    return hashlib.sha1(raw).hexdigest()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id            TEXT PRIMARY KEY,
    anchor_id     TEXT NOT NULL,
    snapshot_ts   TEXT NOT NULL,
    candidates    TEXT NOT NULL,                -- JSON: list of {id, similarity}
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | inferring | done | failed
    inferred_at   TEXT,
    error         TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS batches_status_idx ON batches(status);

CREATE TABLE IF NOT EXISTS proposals (
    id            TEXT PRIMARY KEY,             -- sha1(from>type>to)
    batch_id      TEXT NOT NULL,
    from_id       TEXT NOT NULL,
    to_id         TEXT NOT NULL,
    edge_type     TEXT NOT NULL,
    direction     TEXT NOT NULL,                -- 'A->B' | 'B->A' | 'bidirectional'
    confidence    REAL NOT NULL,
    rationale     TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'proposed',  -- proposed | committed | review | discarded
    consensus_n   INTEGER DEFAULT 1,            -- how many agents agreed
    created_at    TEXT NOT NULL,
    committed_at  TEXT,
    FOREIGN KEY (batch_id) REFERENCES batches(id)
);
CREATE INDEX IF NOT EXISTS proposals_status_idx ON proposals(status);
CREATE INDEX IF NOT EXISTS proposals_from_idx ON proposals(from_id);
CREATE INDEX IF NOT EXISTS proposals_to_idx ON proposals(to_id);

CREATE TABLE IF NOT EXISTS audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id   TEXT NOT NULL,
    from_status   TEXT,
    to_status     TEXT NOT NULL,
    actor         TEXT NOT NULL,                -- 'consensus' | 'auto-commit' | 'validator' | 'user'
    ts            TEXT NOT NULL,
    note          TEXT,
    FOREIGN KEY (proposal_id) REFERENCES proposals(id)
);
"""


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class Queue:
    """SQLite-backed enrichment queue.

    Single-process safe. For multi-process / multi-machine, switch to a real
    DB (Postgres / Neo4j) — but at current scale (5K atoms × 20 candidates) this
    is more than enough.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- Batches ---------------------------------------------------------

    def enqueue_batch(
        self,
        anchor_id: str,
        snapshot_ts: str,
        candidates: list[dict],
    ) -> str:
        """Add a batch. Returns batch_id. Idempotent on (anchor_id, snapshot_ts)."""
        bid = batch_id(anchor_id, snapshot_ts)
        with self._conn() as c:
            c.execute(
                """
                INSERT OR IGNORE INTO batches (id, anchor_id, snapshot_ts, candidates, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (bid, anchor_id, snapshot_ts, json.dumps(candidates), datetime.utcnow().isoformat()),
            )
        return bid

    def claim_batch(self, worker_id: str) -> Optional[dict]:
        """Atomically claim one pending batch. Returns None if queue is empty."""
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            cur = c.execute(
                """
                UPDATE batches SET status = 'inferring', inferred_at = ?
                WHERE id = (SELECT id FROM batches WHERE status = 'pending' LIMIT 1)
                RETURNING id, anchor_id, snapshot_ts, candidates
                """,
                (now,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def mark_batch_done(self, bid: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE batches SET status = 'done' WHERE id = ?", (bid,))

    def mark_batch_failed(self, bid: str, error: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE batches SET status = 'failed', error = ? WHERE id = ?",
                (error, bid),
            )

    def batch_stats(self) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, count(*) AS n FROM batches GROUP BY status"
            ).fetchall()
            return {row["status"]: row["n"] for row in rows}

    # -- Proposals -------------------------------------------------------

    def propose(
        self,
        batch_id: str,
        from_id: str,
        to_id: str,
        edge_type: str,
        direction: str,
        confidence: float,
        rationale: str,
        agent_version: str,
    ) -> str:
        """Insert a proposal. Returns proposal_id. Idempotent on (from, type, to)."""
        pid = proposal_id(from_id, edge_type, to_id)
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO proposals
                    (id, batch_id, from_id, to_id, edge_type, direction, confidence, rationale, agent_version, status, consensus_n, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', 1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    consensus_n = consensus_n + 1,
                    confidence = (confidence + excluded.confidence) / 2.0,
                    rationale = rationale || ' | ' || excluded.rationale
                """,
                (pid, batch_id, from_id, to_id, edge_type, direction, confidence, rationale, agent_version, now),
            )
            self._log(c, pid, None, "proposed", "agent", note=f"conf={confidence:.2f}")
        return pid

    def mark_committed(self, proposal_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as c:
            row = c.execute("SELECT status FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            prev = row["status"] if row else None
            c.execute(
                "UPDATE proposals SET status = 'committed', committed_at = ? WHERE id = ?",
                (now, proposal_id),
            )
            self._log(c, proposal_id, prev, "committed", "auto-commit")

    def mark_review(self, proposal_id: str, note: str = "") -> None:
        with self._conn() as c:
            row = c.execute("SELECT status FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            prev = row["status"] if row else None
            c.execute("UPDATE proposals SET status = 'review' WHERE id = ?", (proposal_id,))
            self._log(c, proposal_id, prev, "review", "consensus", note=note)

    def mark_discarded(self, proposal_id: str, reason: str = "") -> None:
        with self._conn() as c:
            row = c.execute("SELECT status FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            prev = row["status"] if row else None
            c.execute("UPDATE proposals SET status = 'discarded' WHERE id = ?", (proposal_id,))
            self._log(c, proposal_id, prev, "discarded", "consensus", note=reason)

    def pending_for_consensus(self, min_consensus: int = 1) -> list[dict]:
        """Proposals that have been seen by ≥min_consensus agents and not yet routed."""
        with self._conn() as c:
            cur = c.execute(
                """
                SELECT id, from_id, to_id, edge_type, direction, confidence, rationale, consensus_n
                FROM proposals
                WHERE status = 'proposed' AND consensus_n >= ?
                """,
                (min_consensus,),
            )
            return [dict(r) for r in cur.fetchall()]

    def committed_for_neo4j(self, limit: int = 1000) -> list[dict]:
        """Committed proposals that need MERGE into Neo4j (batched)."""
        with self._conn() as c:
            cur = c.execute(
                """
                SELECT id, from_id, to_id, edge_type, direction, confidence
                FROM proposals
                WHERE status = 'committed'
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def proposal_stats(self) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, count(*) AS n FROM proposals GROUP BY status"
            ).fetchall()
            edge_rows = c.execute(
                "SELECT edge_type, count(*) AS n FROM proposals WHERE status = 'committed' GROUP BY edge_type"
            ).fetchall()
        return {
            "by_status": {r["status"]: r["n"] for r in rows},
            "committed_by_edge_type": {r["edge_type"]: r["n"] for r in edge_rows},
        }

    # -- Audit -----------------------------------------------------------

    def _log(
        self,
        conn: sqlite3.Connection,
        proposal_id: str,
        from_status: Optional[str],
        to_status: str,
        actor: str,
        note: str = "",
    ) -> None:
        conn.execute(
            "INSERT INTO audit (proposal_id, from_status, to_status, actor, ts, note) VALUES (?, ?, ?, ?, ?, ?)",
            (proposal_id, from_status, to_status, actor, datetime.utcnow().isoformat(), note),
        )
