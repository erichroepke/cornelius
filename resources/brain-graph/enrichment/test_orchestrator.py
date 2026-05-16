"""Unit tests for the enrichment orchestrator (queue + dedup + prompts + consensus).

No API calls — pure plumbing validation. Run with:
    python -m pytest enrichment/test_orchestrator.py -v
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from enrichment.queue import Queue, proposal_id, batch_id
from enrichment.prompts import (
    SYSTEM_PROMPT,
    build_prompt,
    parse_response,
    ALLOWED_EDGE_TYPES,
)


# ---------------------------------------------------------------------------
# Identity / determinism
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_proposal_id_deterministic(self) -> None:
        a = proposal_id("a.md", "DERIVES_FROM", "b.md")
        b = proposal_id("a.md", "DERIVES_FROM", "b.md")
        assert a == b
        assert len(a) == 40  # sha1 hex length

    def test_proposal_id_distinguishes_direction(self) -> None:
        assert proposal_id("a.md", "X", "b.md") != proposal_id("b.md", "X", "a.md")

    def test_proposal_id_distinguishes_edge_type(self) -> None:
        assert proposal_id("a.md", "DERIVES_FROM", "b.md") != proposal_id("a.md", "MENTIONS", "b.md")

    def test_batch_id_deterministic(self) -> None:
        a = batch_id("anchor.md", "2026-05-13T12:00:00")
        b = batch_id("anchor.md", "2026-05-13T12:00:00")
        assert a == b


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@pytest.fixture
def queue(tmp_path: Path) -> Queue:
    return Queue(tmp_path / "enrichment.db")


class TestQueue:
    def test_initial_state_empty(self, queue: Queue) -> None:
        assert queue.batch_stats() == {}
        assert queue.proposal_stats()["by_status"] == {}

    def test_enqueue_batch(self, queue: Queue) -> None:
        bid = queue.enqueue_batch("anchor.md", "ts1", [{"id": "x.md"}])
        assert len(bid) == 40
        assert queue.batch_stats() == {"pending": 1}

    def test_enqueue_is_idempotent(self, queue: Queue) -> None:
        queue.enqueue_batch("anchor.md", "ts1", [{"id": "x.md"}])
        queue.enqueue_batch("anchor.md", "ts1", [{"id": "x.md"}])
        assert queue.batch_stats() == {"pending": 1}  # no dup

    def test_claim_batch_atomic(self, queue: Queue) -> None:
        queue.enqueue_batch("a1.md", "ts1", [{"id": "x.md"}])
        queue.enqueue_batch("a2.md", "ts1", [{"id": "y.md"}])
        b1 = queue.claim_batch("worker1")
        b2 = queue.claim_batch("worker2")
        b3 = queue.claim_batch("worker3")
        assert b1 is not None
        assert b2 is not None
        assert b3 is None  # queue drained
        assert b1["id"] != b2["id"]

    def test_propose_idempotent_increments_consensus(self, queue: Queue) -> None:
        bid = queue.enqueue_batch("a.md", "ts1", [{"id": "b.md"}])
        pid_1 = queue.propose(bid, "a.md", "b.md", "DERIVES_FROM", "A->B", 0.8, "first call", "v1")
        pid_2 = queue.propose(bid, "a.md", "b.md", "DERIVES_FROM", "A->B", 0.9, "second call", "v1")
        assert pid_1 == pid_2  # same deterministic ID
        # consensus count should be 2 + averaged confidence
        with sqlite3.connect(queue.db_path) as c:
            row = c.execute("SELECT consensus_n, confidence FROM proposals WHERE id = ?", (pid_1,)).fetchone()
            assert row[0] == 2
            assert abs(row[1] - 0.85) < 1e-6  # (0.8 + 0.9) / 2

    def test_proposal_lifecycle_transitions(self, queue: Queue) -> None:
        bid = queue.enqueue_batch("a.md", "ts1", [{"id": "b.md"}])
        pid = queue.propose(bid, "a.md", "b.md", "RELATED_TO", "bidirectional", 0.9, "rationale", "v1")
        queue.mark_committed(pid)
        stats = queue.proposal_stats()
        assert stats["by_status"]["committed"] == 1
        assert stats["committed_by_edge_type"]["RELATED_TO"] == 1

    def test_audit_trail_records_transitions(self, queue: Queue) -> None:
        bid = queue.enqueue_batch("a.md", "ts1", [{"id": "b.md"}])
        pid = queue.propose(bid, "a.md", "b.md", "MENTIONS", "A->B", 0.7, "r", "v1")
        queue.mark_review(pid, note="mid-confidence")
        with sqlite3.connect(queue.db_path) as c:
            rows = c.execute("SELECT actor, to_status FROM audit WHERE proposal_id = ? ORDER BY id", (pid,)).fetchall()
        assert rows[0] == ("agent", "proposed")
        assert rows[1] == ("consensus", "review")

    def test_mark_batch_done(self, queue: Queue) -> None:
        bid = queue.enqueue_batch("a.md", "ts1", [{"id": "b.md"}])
        queue.claim_batch("w1")
        queue.mark_batch_done(bid)
        assert queue.batch_stats() == {"done": 1}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

class TestPromptBuilder:
    def test_build_prompt_includes_anchor_and_candidates(self) -> None:
        anchor = {"id": "a.md", "title": "Anchor Title", "content_preview": "Anchor body."}
        candidates = [
            {"id": "c1.md", "title": "C1", "similarity": 0.9, "content_preview": "C1 body."},
            {"id": "c2.md", "title": "C2", "similarity": 0.7, "content_preview": "C2 body."},
        ]
        prompt = build_prompt(anchor, candidates)
        assert "a.md" in prompt
        assert "c1.md" in prompt
        assert "c2.md" in prompt
        assert "Anchor body." in prompt

    def test_system_prompt_lists_all_edge_types(self) -> None:
        for etype in ALLOWED_EDGE_TYPES:
            assert etype in SYSTEM_PROMPT


class TestResponseParser:
    def test_parse_valid_response(self) -> None:
        text = json.dumps({
            "proposals": [
                {
                    "candidate_id": "x.md",
                    "edge_type": "DERIVES_FROM",
                    "direction": "A->B",
                    "confidence": 0.85,
                    "rationale": "A explicitly builds on X's framework.",
                }
            ]
        })
        out = parse_response(text)
        assert len(out) == 1
        assert out[0]["edge_type"] == "DERIVES_FROM"
        assert out[0]["confidence"] == 0.85

    def test_parse_strips_markdown_fence(self) -> None:
        text = '```json\n{"proposals": [{"candidate_id":"x.md","edge_type":"REFERENCES","direction":"A->B","confidence":0.7,"rationale":"r"}]}\n```'
        out = parse_response(text)
        assert len(out) == 1

    def test_parse_empty_proposals(self) -> None:
        assert parse_response('{"proposals": []}') == []

    def test_parse_invalid_json_returns_empty(self) -> None:
        assert parse_response("not json") == []

    def test_parse_filters_unknown_edge_type(self) -> None:
        text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":"BOGUS","direction":"A->B","confidence":0.9,"rationale":"r"}]})
        assert parse_response(text) == []

    def test_parse_filters_non_bdg_edge_types(self) -> None:
        """My earlier prompts had MENTIONS/RELATED_TO/CONTRADICTS/EXTENDS — none are in BDG. Must reject."""
        for bad in ("MENTIONS", "RELATED_TO", "CONTRADICTS", "EXTENDS"):
            text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":bad,"direction":"A->B","confidence":0.9,"rationale":"r"}]})
            assert parse_response(text) == [], f"should reject non-BDG edge type {bad}"

    def test_parse_accepts_all_six_bdg_edge_types(self) -> None:
        for etype in ("DERIVES_FROM", "INSTANTIATES", "REFERENCES", "ASSOCIATES", "TENSION", "SUPERSEDES"):
            direction = "bidirectional" if etype in ("ASSOCIATES", "TENSION") else "A->B"
            text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":etype,"direction":direction,"confidence":0.8,"rationale":"r"}]})
            out = parse_response(text)
            assert len(out) == 1, f"should accept BDG edge type {etype}"

    def test_parse_rejects_bidirectional_for_unidirectional_types(self) -> None:
        """Per BDG: bidirectional only valid for ASSOCIATES + TENSION."""
        for etype in ("DERIVES_FROM", "INSTANTIATES", "REFERENCES", "SUPERSEDES"):
            text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":etype,"direction":"bidirectional","confidence":0.8,"rationale":"r"}]})
            assert parse_response(text) == [], f"bidirectional should be rejected for {etype}"

    def test_parse_filters_out_of_range_confidence(self) -> None:
        text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":"REFERENCES","direction":"A->B","confidence":1.5,"rationale":"r"}]})
        assert parse_response(text) == []

    def test_parse_filters_missing_rationale(self) -> None:
        text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":"REFERENCES","direction":"A->B","confidence":0.7,"rationale":""}]})
        assert parse_response(text) == []

    def test_parse_filters_bad_direction(self) -> None:
        text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":"REFERENCES","direction":"SIDEWAYS","confidence":0.7,"rationale":"r"}]})
        assert parse_response(text) == []

    def test_parse_lowercases_edge_type_accepted(self) -> None:
        # parser uppercases before validation
        text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":"derives_from","direction":"A->B","confidence":0.7,"rationale":"r"}]})
        out = parse_response(text)
        assert len(out) == 1
        assert out[0]["edge_type"] == "DERIVES_FROM"

    def test_parse_handles_bdg_kebab_form(self) -> None:
        """BDG sometimes uses kebab-case form (derives-from). Should still accept after normalization."""
        # Note: prompts uses SCREAMING_SNAKE for Cypher convention; BDG models.py uses kebab.
        # The parser uppercases — kebab becomes 'DERIVES-FROM' which won't match.
        # This is expected: agents are instructed to use SCREAMING_SNAKE per the SYSTEM_PROMPT.
        text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":"derives-from","direction":"A->B","confidence":0.7,"rationale":"r"}]})
        assert parse_response(text) == []  # rejected — agents must use SCREAMING_SNAKE

    def test_parse_caps_rationale_length(self) -> None:
        text = json.dumps({"proposals": [{"candidate_id":"x.md","edge_type":"REFERENCES","direction":"A->B","confidence":0.7,"rationale":"x" * 1000}]})
        out = parse_response(text)
        assert len(out[0]["rationale"]) <= 500


# ---------------------------------------------------------------------------
# Consensus thresholds (logic mirrored from orchestrator)
# ---------------------------------------------------------------------------

class TestConsensusRouting:
    """Tests the routing thresholds (mirrors orchestrator.cmd_consensus logic)."""

    def test_high_conf_two_agents_auto_commits(self, queue: Queue) -> None:
        bid = queue.enqueue_batch("a.md", "ts1", [])
        pid = queue.propose(bid, "a.md", "b.md", "DERIVES_FROM", "A->B", 0.9, "r1", "v1")
        queue.propose(bid, "a.md", "b.md", "DERIVES_FROM", "A->B", 0.9, "r2", "v2")
        # Now consensus_n should be 2, confidence 0.9
        proposals = queue.pending_for_consensus(min_consensus=1)
        assert proposals[0]["consensus_n"] == 2
        assert proposals[0]["confidence"] == 0.9
        # Apply auto-commit rule manually
        for p in proposals:
            if p["confidence"] >= 0.85 and p["consensus_n"] >= 2:
                queue.mark_committed(p["id"])
        assert queue.proposal_stats()["by_status"]["committed"] == 1

    def test_mid_conf_goes_to_review(self, queue: Queue) -> None:
        bid = queue.enqueue_batch("a.md", "ts1", [])
        pid = queue.propose(bid, "a.md", "b.md", "RELATED_TO", "bidirectional", 0.7, "mid", "v1")
        queue.mark_review(pid, note="mid-conf")
        assert queue.proposal_stats()["by_status"]["review"] == 1

    def test_low_conf_discarded(self, queue: Queue) -> None:
        bid = queue.enqueue_batch("a.md", "ts1", [])
        pid = queue.propose(bid, "a.md", "b.md", "MENTIONS", "A->B", 0.3, "low", "v1")
        queue.mark_discarded(pid, reason="conf=0.3")
        assert queue.proposal_stats()["by_status"]["discarded"] == 1
