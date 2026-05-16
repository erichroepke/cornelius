"""Main enrichment orchestrator entry point.

Usage:
    python -m enrichment.orchestrator --dry-run               # walk + report, no API calls
    python -m enrichment.orchestrator --bootstrap-queue       # enqueue all atoms (run once)
    python -m enrichment.orchestrator --first-pass            # run inference (long)
    python -m enrichment.orchestrator --consensus             # promote proposals (auto-commit / review / discard)
    python -m enrichment.orchestrator --status                # show queue + proposal stats

Flow:
    1. bootstrap-queue: read data/graph_enrichments.json, enqueue one batch per atom
    2. first-pass: 20 workers consume batches, call Anthropic, write proposals
    3. consensus: scan proposals, route by confidence + agreement count
    4. (Phase F+) auto-commit applies committed proposals to Neo4j via MERGE
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Import siblings (works under both `python -m enrichment.orchestrator` and direct file run)
try:
    from . import __version__
    from .queue import Queue
    from .prompts import SYSTEM_PROMPT, build_prompt, parse_response
    from .agent_pool import AnthropicClient, run_pool
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from enrichment import __version__
    from enrichment.queue import Queue
    from enrichment.prompts import SYSTEM_PROMPT, build_prompt, parse_response
    from enrichment.agent_pool import AnthropicClient, run_pool


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BRAIN_GRAPH_DIR = Path(__file__).resolve().parent.parent
SIDECAR_PATH = BRAIN_GRAPH_DIR / "data" / "graph_enrichments.json"
DB_PATH = BRAIN_GRAPH_DIR / "data" / "enrichment.db"

# Confidence thresholds (overridable via --auto-commit-threshold etc.)
AUTO_COMMIT_CONFIDENCE = 0.85
AUTO_COMMIT_MIN_AGENTS = 2
REVIEW_MIN_CONFIDENCE = 0.6


# ---------------------------------------------------------------------------
# Vector pre-filter (placeholder: top-K by alphabetical ID for dry-run; real LBS later)
# ---------------------------------------------------------------------------

def vector_neighbors(atom_id: str, all_ids: list[str], k: int = 20) -> list[dict]:
    """Return top-K vector-similar atoms for `atom_id`.

    DRY-RUN VERSION: alphabetical sort, NOT real similarity. Replace with
    LBS FAISS call once orchestrator is wired to the real index. The shape
    of the output is the contract — callers should not depend on ordering
    quality in --dry-run mode.
    """
    others = [a for a in all_ids if a != atom_id]
    return [{"id": a, "similarity": 0.0} for a in others[:k]]


# ---------------------------------------------------------------------------
# Bootstrap: enqueue all atoms
# ---------------------------------------------------------------------------

def cmd_bootstrap_queue(args: argparse.Namespace) -> None:
    if not SIDECAR_PATH.exists():
        print(f"ERROR: {SIDECAR_PATH} not found. Run ./run_brain_graph.sh bootstrap first.", file=sys.stderr)
        sys.exit(1)
    with SIDECAR_PATH.open() as f:
        sidecar = json.load(f)
    nodes = sidecar.get("nodes", {})
    snapshot_ts = sidecar.get("last_bootstrap", datetime.utcnow().isoformat())
    all_ids = list(nodes.keys())

    queue = Queue(DB_PATH)
    enqueued = 0
    for atom_id in all_ids:
        candidates = vector_neighbors(atom_id, all_ids, k=20)
        queue.enqueue_batch(atom_id, snapshot_ts, candidates)
        enqueued += 1
        if enqueued % 500 == 0:
            print(f"  enqueued {enqueued}/{len(all_ids)}", file=sys.stderr)
    print(f"Done. Enqueued {enqueued} batches to {DB_PATH}")
    print("Stats:", queue.batch_stats())


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> None:
    queue = Queue(DB_PATH)
    print(f"Enrichment Orchestrator v{__version__}")
    print(f"DB: {DB_PATH}")
    print(f"Sidecar: {SIDECAR_PATH} {'(exists)' if SIDECAR_PATH.exists() else '(MISSING)'}")
    print()
    print("Batches:")
    for status, n in sorted(queue.batch_stats().items()):
        print(f"  {status:12s}: {n:6d}")
    stats = queue.proposal_stats()
    print()
    print("Proposals (by status):")
    for status, n in sorted(stats["by_status"].items()):
        print(f"  {status:12s}: {n:6d}")
    if stats["committed_by_edge_type"]:
        print()
        print("Committed edges (by type):")
        for etype, n in sorted(stats["committed_by_edge_type"].items(), key=lambda x: -x[1]):
            print(f"  {etype:14s}: {n:6d}")


# ---------------------------------------------------------------------------
# Dry-run (no API calls)
# ---------------------------------------------------------------------------

def cmd_dry_run(args: argparse.Namespace) -> None:
    if not SIDECAR_PATH.exists():
        print(f"ERROR: {SIDECAR_PATH} not found. Run ./run_brain_graph.sh bootstrap first.", file=sys.stderr)
        sys.exit(1)
    with SIDECAR_PATH.open() as f:
        sidecar = json.load(f)
    nodes = sidecar.get("nodes", {})
    print(f"DRY-RUN: would enqueue {len(nodes)} batches")
    sample = list(nodes.keys())[:3]
    print(f"First 3 atoms: {sample}")
    print(f"Estimated cost @ {AUTO_COMMIT_CONFIDENCE} threshold, 20 candidates/batch, ~750 input tokens + 200 output:")
    n_batches = len(nodes)
    # Sonnet 4.6 pricing: $3 in / $15 out per 1M
    in_tokens = n_batches * 750
    out_tokens = n_batches * 200
    cost = (in_tokens / 1_000_000) * 3 + (out_tokens / 1_000_000) * 15
    print(f"  ~${cost:.2f} (single pass, conservative)")
    print()
    print("To proceed:")
    print("  python -m enrichment.orchestrator --bootstrap-queue")
    print("  python -m enrichment.orchestrator --first-pass")
    print("  python -m enrichment.orchestrator --consensus")


# ---------------------------------------------------------------------------
# First-pass inference
# ---------------------------------------------------------------------------

async def _first_pass(n_workers: int, max_batches: int | None) -> None:
    queue = Queue(DB_PATH)
    if "pending" not in queue.batch_stats():
        print("Queue empty. Run --bootstrap-queue first.", file=sys.stderr)
        return
    client = AnthropicClient()
    agent_version = f"enrichment-v{__version__}"

    print(f"Starting {n_workers}-worker inference. Initial stats: {queue.batch_stats()}")
    result = await run_pool(
        n_workers=n_workers,
        client=client,
        queue=queue,
        prompt_builder=build_prompt,
        response_parser=parse_response,
        system_prompt=SYSTEM_PROMPT,
        agent_version=agent_version,
        max_batches=max_batches,
    )
    await client.aclose()
    print(f"Done. Processed {result['processed']} batches in {result['elapsed_s']}s.")
    print(f"Final stats: {queue.batch_stats()}")


def cmd_first_pass(args: argparse.Namespace) -> None:
    asyncio.run(_first_pass(n_workers=args.workers, max_batches=args.max_batches))


# ---------------------------------------------------------------------------
# Consensus + routing
# ---------------------------------------------------------------------------

def cmd_consensus(args: argparse.Namespace) -> None:
    queue = Queue(DB_PATH)
    pending = queue.pending_for_consensus(min_consensus=1)
    print(f"Routing {len(pending)} proposals...")
    auto, review, discard = 0, 0, 0
    for p in pending:
        if p["confidence"] >= AUTO_COMMIT_CONFIDENCE and p["consensus_n"] >= AUTO_COMMIT_MIN_AGENTS:
            queue.mark_committed(p["id"])
            auto += 1
        elif p["confidence"] >= REVIEW_MIN_CONFIDENCE:
            queue.mark_review(p["id"], note=f"conf={p['confidence']:.2f}, n={p['consensus_n']}")
            review += 1
        else:
            queue.mark_discarded(p["id"], reason=f"low conf={p['confidence']:.2f}")
            discard += 1
    print(f"  auto-committed: {auto}")
    print(f"  queued for review: {review}")
    print(f"  discarded: {discard}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ZEUS BRAIN Semantic Enrichment Orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dry = sub.add_parser("dry-run", help="Walk + cost estimate, no API calls")
    p_dry.set_defaults(func=cmd_dry_run)

    p_status = sub.add_parser("status", help="Show queue + proposal stats")
    p_status.set_defaults(func=cmd_status)

    p_boot = sub.add_parser("bootstrap-queue", help="Enqueue all atoms from sidecar (run once)")
    p_boot.set_defaults(func=cmd_bootstrap_queue)

    p_first = sub.add_parser("first-pass", help="Run inference workers")
    p_first.add_argument("--workers", type=int, default=20, help="Concurrent workers (default: 20)")
    p_first.add_argument("--max-batches", type=int, default=None, help="Stop after N batches (testing)")
    p_first.set_defaults(func=cmd_first_pass)

    p_cons = sub.add_parser("consensus", help="Route proposals to committed/review/discarded")
    p_cons.set_defaults(func=cmd_consensus)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
