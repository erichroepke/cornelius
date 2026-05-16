"""Daily routine CLI entry point.

Usage:
    python -m daily.cli run [--dry-run] [--max-cost-cents N]
    python -m daily.cli rollback YYYY-MM-DD
    python -m daily.cli status

The `run` subcommand chains: sweeper → router → processor → enricher → digest.
Each step writes audit rows to `data/daily_audit.db` for reversibility.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

# Import the daily routine modules. Works under both `python -m daily.cli` and direct file run.
try:
    from . import __version__
    from . import sweeper as _sweeper
    from . import router as _router
    from . import processor as _processor
    from . import enricher as _enricher
    from . import digest as _digest
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from daily import __version__
    from daily import sweeper as _sweeper
    from daily import router as _router
    from daily import processor as _processor
    from daily import enricher as _enricher
    from daily import digest as _digest


AUDIT_DB = Path(__file__).resolve().parent.parent / "data" / "daily_audit.db"
TRASH_DIR = Path.home() / ".Trash"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    """Chain the 5 steps. Each module is responsible for its own audit logging."""
    started = datetime.utcnow().isoformat()
    run_date = date.today().isoformat()
    print(f"[daily v{__version__}] run started at {started}Z (date={run_date})", file=sys.stderr)
    if args.dry_run:
        print("  --dry-run: NO writes, NO API calls; sweeper + router only", file=sys.stderr)

    # 1. Sweep
    print("[1/5] Sweeper...", file=sys.stderr)
    sweep_result = _sweeper.run_sweep(dry_run=args.dry_run)
    print(f"  -> {sweep_result.summary()}", file=sys.stderr)
    records = sweep_result.all_changed
    if not records:
        print("  (nothing new — exiting after sweep)", file=sys.stderr)
        return 0

    # 2. Route
    print("[2/5] Router...", file=sys.stderr)
    pairs = _router.route_batch(records)
    print(f"  -> {len(pairs)} routing decisions", file=sys.stderr)

    if args.dry_run:
        print("  (dry-run: stopping after router; would have invoked processor + enricher + digest)", file=sys.stderr)
        for record, decision in pairs[:10]:
            print(f"    {record.path}  ->  {decision.destination}  [trust={decision.trust}]", file=sys.stderr)
        if len(pairs) > 10:
            print(f"    ... +{len(pairs) - 10} more", file=sys.stderr)
        return 0

    # 3. Process (invoke Cornelius skills via headless claude -p)
    print("[3/5] Processor...", file=sys.stderr)
    batch_result = _processor.process_batch(
        pairs, run_date=run_date, dry_run=args.dry_run, max_cost_cents=args.max_cost_cents
    )
    print(f"  -> processed={batch_result.processed_count}, skills_invoked={batch_result.skill_invocations}, budget_hit={batch_result.budget_hit}", file=sys.stderr)

    # 4. Enrich (re-bootstrap BDG + reload Neo4j)
    print("[4/5] Enricher...", file=sys.stderr)
    enrich_result = _enricher.run_enrichment(force_bootstrap=True, dry_run=args.dry_run)
    print(f"  -> bdg={enrich_result.bdg_success}, neo4j={enrich_result.neo4j_success}", file=sys.stderr)

    # 5. Digest
    print("[5/5] Digest...", file=sys.stderr)
    digest_path = _digest.write_digest(date.today())
    print(f"  -> {digest_path}", file=sys.stderr)

    print(f"[daily v{__version__}] run complete at {datetime.utcnow().isoformat()}Z", file=sys.stderr)
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    """Reverse a given day's moves. Delegates to processor.rollback_date()."""
    day = args.date  # YYYY-MM-DD
    try:
        date.fromisoformat(day)
    except ValueError:
        print(f"Invalid date: {day} (expected YYYY-MM-DD)", file=sys.stderr)
        return 1

    if not AUDIT_DB.exists():
        print(f"No audit DB at {AUDIT_DB}; nothing to rollback.", file=sys.stderr)
        return 0

    print(f"Rolling back moves from {day}...", file=sys.stderr)
    reverted = _processor.rollback_date(day)
    print(f"Rollback complete: {len(reverted)} files reverted.", file=sys.stderr)
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Baseline the sweeper state with the current filesystem, without processing.

    After this runs, daily routine sees the snapshot as 'already seen' and only
    catches files added/modified AFTER the snapshot. Use as the one-time install
    step before activating the launchd job — prevents the first run from
    ingesting years of distributed-Inbox archives in bulk.
    """
    from . import sweeper as _sw
    print(f"[daily v{__version__}] snapshot started at {datetime.utcnow().isoformat()}Z", file=sys.stderr)
    result = _sw.run_sweep(dry_run=False)
    print(f"  {result.summary()}", file=sys.stderr)
    print(f"  State saved to {_sw.STATE_PATH if hasattr(_sw, 'STATE_PATH') else 'data/raw-inventory.last.json'}", file=sys.stderr)
    print(f"  Daily routine will now catch ONLY files modified after this snapshot.", file=sys.stderr)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print quick state summary."""
    print(f"daily v{__version__}")
    print(f"audit_db: {AUDIT_DB} {'(exists)' if AUDIT_DB.exists() else '(MISSING)'}")
    state_file = Path(__file__).resolve().parent.parent / "data" / "raw-inventory.last.json"
    print(f"sweeper state: {state_file} {'(exists)' if state_file.exists() else '(MISSING)'}")
    if AUDIT_DB.exists():
        with sqlite3.connect(AUDIT_DB) as conn:
            for tbl in ("sweeper_events", "router_decisions", "router_moves", "processor_invocations", "enricher_runs"):
                try:
                    n = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
                    print(f"  {tbl}: {n} rows")
                except sqlite3.OperationalError:
                    print(f"  {tbl}: (table missing)")
    return 0


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Daily Brain ingestion routine")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Sweep + route + process + enrich + digest")
    p_run.add_argument("--dry-run", action="store_true", help="Sweep + route only; no file moves or API calls")
    p_run.add_argument("--max-cost-cents", type=int, default=500, help="Abort processor if running cost exceeds N cents (default 500 = $5)")
    p_run.set_defaults(func=cmd_run)

    p_roll = sub.add_parser("rollback", help="Reverse all moves from a given day")
    p_roll.add_argument("date", help="YYYY-MM-DD")
    p_roll.set_defaults(func=cmd_rollback)

    p_status = sub.add_parser("status", help="Show audit DB stats")
    p_status.set_defaults(func=cmd_status)

    p_snap = sub.add_parser(
        "snapshot",
        help="Baseline current filesystem state without processing. "
             "Use this ONCE before installing the launchd job, so daily runs "
             "only catch genuinely-new content going forward.",
    )
    p_snap.set_defaults(func=cmd_snapshot)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
