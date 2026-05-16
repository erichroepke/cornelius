"""Edge proposal prompt template + JSON response parser.

Edge type vocabulary mirrors the Cornelius BDG schema EXACTLY
(see ~/Cornelius/resources/brain-graph/models.py::EdgeType). Six types,
each with specific staleness-propagation semantics defined in
BRAIN-DEPENDENCY-GRAPH-ARCHITECTURE.md. Do NOT add new types here —
the BDG schema is the source of truth.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Mirrors Cornelius BDG models.py::EdgeType. Same 6, same string values.
ALLOWED_EDGE_TYPES = (
    "DERIVES_FROM",   # tight coupling (decay 0.8): B was synthesized from A
    "INSTANTIATES",   # structural coupling (decay 0.7): B is a specific case of framework A
    "REFERENCES",     # loose coupling (decay 0.2): B mentions a concept from A
    "ASSOCIATES",     # thematic only (decay 0.05): B is bidirectionally related to A
    "TENSION",        # staleness-immune (decay 0.0): A and B contradict productively
    "SUPERSEDES",     # full coupling (decay 1.0): B replaces A (A deprecated)
)

# Bidirectional edges have no authority on either side; map to BDG semantics.
BIDIRECTIONAL_EDGE_TYPES = {"ASSOCIATES", "TENSION"}

ALLOWED_DIRECTIONS = ("A->B", "B->A", "bidirectional")


SYSTEM_PROMPT = """You analyze pairs of atomic knowledge notes from a Zettelkasten brain (Cornelius BDG schema) and propose typed semantic edges between them.

For each (anchor, candidate) pair, output 0 or 1 edges. Be conservative — prefer NO edge over a weak one. The brain already has structural edges (wikilinks). Your job is to surface SEMANTIC relationships that aren't already encoded.

The six allowed edge types match the BDG schema exactly. Each has a defined staleness-propagation semantic — pick the one that fits, do not invent new types:

- DERIVES_FROM — A's claim depends on B (B is upstream evidence or framework). High-coupling: when B changes, A is potentially stale. (decay 0.8)
- INSTANTIATES — A is a specific case of framework B (B drives downstream insights). Use for framework-to-application links. (decay 0.7)
- REFERENCES — A mentions a concept from B without depending on it. Loose mention. (decay 0.2)
- ASSOCIATES — A and B share thematic territory; bidirectional and weakly coupled. (decay 0.05)
- TENSION — A and B make opposing claims that cannot both be true; bidirectional and immune to staleness propagation (productive contradiction). (decay 0.0)
- SUPERSEDES — A explicitly replaces or refines B's claim (B is now outdated). Full propagation: B is treated as deprecated. (decay 1.0)

Output ONLY valid JSON. No commentary. No markdown fences. Example:

{
  "proposals": [
    {
      "candidate_id": "02-Permanent/dopamine-and-curiosity.md",
      "edge_type": "DERIVES_FROM",
      "direction": "A->B",
      "confidence": 0.82,
      "rationale": "Anchor builds on Berlyne curiosity theory which is the framework articulated in candidate."
    }
  ]
}

If no edges are warranted across all candidates, return: {"proposals": []}

Confidence: 0.0-1.0 only.
Direction: "A->B" means edge points anchor → candidate. Use "B->A" if candidate → anchor. Use "bidirectional" only for ASSOCIATES and TENSION.
Rationale: one sentence, names the specific claim or concept that justifies the edge.
"""


def build_prompt(anchor: dict, candidates: list[dict]) -> str:
    """Build the user prompt for edge inference.

    anchor: {id, title, content_preview, layer}
    candidates: list of {id, title, content_preview, layer, similarity}
    """
    lines = [
        f"ANCHOR ({anchor.get('layer','insight')})",
        f"id: {anchor['id']}",
        f"title: {anchor.get('title', anchor['id'])}",
        "content:",
        anchor.get("content_preview", "")[:1000],
        "",
        f"CANDIDATES ({len(candidates)} vector-similar atoms):",
        "",
    ]
    for i, c in enumerate(candidates, 1):
        lines.extend([
            f"--- Candidate {i} (similarity={c.get('similarity', 0):.2f}, layer={c.get('layer','insight')}) ---",
            f"id: {c['id']}",
            f"title: {c.get('title', c['id'])}",
            "content:",
            c.get("content_preview", "")[:600],
            "",
        ])
    lines.append("Propose typed edges in the JSON schema above. Be conservative.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_response(text: str) -> list[dict]:
    """Parse an LLM response, returning a list of validated proposals.

    Strips accidental markdown fences. Validates each proposal:
    - edge_type ∈ ALLOWED_EDGE_TYPES
    - direction ∈ ALLOWED_DIRECTIONS
    - confidence ∈ [0.0, 1.0]
    - rationale present
    Discards invalid entries (does not raise — over-aggressive validation kills throughput).

    Returns: list of {candidate_id, edge_type, direction, confidence, rationale}
    """
    stripped = _JSON_FENCE_RE.sub("", text.strip()).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return []
    raw = data.get("proposals", []) if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return []

    valid: list[dict] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        candidate_id = p.get("candidate_id")
        edge_type = p.get("edge_type", "").upper()
        direction = p.get("direction", "A->B")
        confidence = p.get("confidence")
        rationale = p.get("rationale", "").strip()

        if not candidate_id or not isinstance(candidate_id, str):
            continue
        if edge_type not in ALLOWED_EDGE_TYPES:
            continue
        if direction not in ALLOWED_DIRECTIONS:
            continue
        # Bidirectional only valid for ASSOCIATES + TENSION (per BDG semantics)
        if direction == "bidirectional" and edge_type not in BIDIRECTIONAL_EDGE_TYPES:
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= confidence <= 1.0):
            continue
        if not rationale:
            continue

        valid.append({
            "candidate_id": candidate_id,
            "edge_type": edge_type,
            "direction": direction,
            "confidence": confidence,
            "rationale": rationale[:500],  # cap rationale length
        })
    return valid
