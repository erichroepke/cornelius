"""Semantic Enrichment Orchestrator for ZEUS BRAIN.

Walks the BDG sidecar, vector-pre-filters via LBS FAISS, dispatches 20 parallel
LLM agents to propose typed edges (MENTIONS / DERIVES_FROM / RELATED_TO /
CONTRADICTS / SUPERSEDES / EXTENDS), reaches consensus, and MERGEs high-confidence
proposals into Neo4j. Mid-confidence proposals queue for human review.

Entry points:
- `python -m enrichment.orchestrator --dry-run`  → walk queue, no API calls
- `python -m enrichment.orchestrator --first-pass`  → full enrichment run
- `python -m enrichment.orchestrator --resume`  → continue from last queue position

Output state:
- `data/enrichment.db` (SQLite — queue, proposals, audit log)
- `_outputs/edge-review/{date}.md` (mid-confidence proposals for human review)
"""
from __future__ import annotations

__version__ = "0.1.0"
