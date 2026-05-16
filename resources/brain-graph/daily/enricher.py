"""
Brain Daily Ingest - Enricher

Re-runs the BDG bootstrap (classify.py) and Neo4j load (load_neo4j.sh) so
the graph stays current after new files are ingested.

Both scripts are idempotent (bootstrap uses MERGE logic; load_neo4j.sh uses
MERGE in Cypher) so re-running on the same day is safe.

Design notes:
  - This module is a thin delegation layer — it calls the existing shell scripts
    rather than duplicating their logic, keeping the enricher's blast radius small.
  - If Neo4j is not running, the Neo4j step is skipped with a warning (not fatal).
  - LBS re-index is also triggered so semantic search reflects new notes.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BDG_DIR = Path(__file__).parent.parent  # .../brain-graph/

RUN_BDG_SCRIPT  = _BDG_DIR / "run_brain_graph.sh"
LOAD_NEO4J_SCRIPT = _BDG_DIR / "load_neo4j.sh"
LBS_DIR = _BDG_DIR.parent / "local-brain-search"
RUN_INDEX_SCRIPT = LBS_DIR / "run_index.sh"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EnrichResult:
    bdg_success: bool = False
    bdg_output: str = ""
    neo4j_success: bool = False
    neo4j_output: str = ""
    neo4j_skipped: bool = False
    lbs_success: bool = False
    lbs_output: str = ""
    lbs_skipped: bool = False

    def summary(self) -> str:
        parts = []
        parts.append(f"BDG={'ok' if self.bdg_success else 'FAIL'}")
        if self.neo4j_skipped:
            parts.append("Neo4j=SKIP")
        else:
            parts.append(f"Neo4j={'ok' if self.neo4j_success else 'FAIL'}")
        if self.lbs_skipped:
            parts.append("LBS=SKIP")
        else:
            parts.append(f"LBS={'ok' if self.lbs_success else 'FAIL'}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_script(script: Path, *args: str, timeout: int = 600) -> tuple[bool, str]:
    """
    Run a shell script and return (success, combined_output).
    timeout in seconds (default 10 min).
    """
    if not script.exists():
        return False, f"Script not found: {script}"

    cmd = ["/bin/zsh", str(script)] + list(args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(script.parent),
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"Script timed out after {timeout}s: {script.name}"
    except OSError as exc:
        return False, f"OS error running {script.name}: {exc}"


def _neo4j_is_reachable() -> bool:
    """Quick check: is the zeus-brain-neo4j Docker container running?"""
    try:
        result = subprocess.run(
            ["/bin/zsh", "-c",
             "docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^zeus-brain-neo4j$'"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_enrichment(
    force_bootstrap: bool = False,
    skip_neo4j: bool = False,
    skip_lbs: bool = False,
    dry_run: bool = False,
) -> EnrichResult:
    """
    Run BDG bootstrap, LBS re-index, and Neo4j load in sequence.

    Parameters
    ----------
    force_bootstrap : bool
        Pass --force to run_brain_graph.sh bootstrap (re-classifies all nodes).
    skip_neo4j : bool
        Skip the Neo4j load step entirely.
    skip_lbs : bool
        Skip the LBS re-index step.
    dry_run : bool
        Print what would be done but do not execute.
    """
    result = EnrichResult()

    # ------------------------------------------------------------------
    # Step 1: BDG bootstrap
    # ------------------------------------------------------------------
    bootstrap_args = ["bootstrap"]
    if force_bootstrap:
        bootstrap_args.append("--force")

    if dry_run:
        print(f"[enricher dry-run] would run: {RUN_BDG_SCRIPT} {' '.join(bootstrap_args)}")
        result.bdg_success = True
        result.bdg_output = "[dry-run]"
    else:
        print("[enricher] Running BDG bootstrap...")
        ok, out = _run_script(RUN_BDG_SCRIPT, *bootstrap_args, timeout=300)
        result.bdg_success = ok
        result.bdg_output = out
        if not ok:
            print(f"[enricher] WARNING: BDG bootstrap failed:\n{out}", file=sys.stderr)
        else:
            print("[enricher] BDG bootstrap complete.")

    # ------------------------------------------------------------------
    # Step 2: LBS re-index
    # ------------------------------------------------------------------
    if skip_lbs:
        result.lbs_skipped = True
        result.lbs_output = "skipped by caller"
    elif not RUN_INDEX_SCRIPT.exists():
        result.lbs_skipped = True
        result.lbs_output = f"script not found: {RUN_INDEX_SCRIPT}"
        print(f"[enricher] WARNING: LBS index script not found — skipping.", file=sys.stderr)
    elif dry_run:
        print(f"[enricher dry-run] would run: {RUN_INDEX_SCRIPT}")
        result.lbs_success = True
        result.lbs_output = "[dry-run]"
    else:
        print("[enricher] Re-indexing LBS...")
        ok, out = _run_script(RUN_INDEX_SCRIPT, timeout=600)
        result.lbs_success = ok
        result.lbs_output = out
        if not ok:
            print(f"[enricher] WARNING: LBS re-index failed:\n{out}", file=sys.stderr)
        else:
            print("[enricher] LBS re-index complete.")

    # ------------------------------------------------------------------
    # Step 3: Neo4j load (optional, skipped if container not running)
    # ------------------------------------------------------------------
    if skip_neo4j:
        result.neo4j_skipped = True
        result.neo4j_output = "skipped by caller"
    elif not _neo4j_is_reachable():
        result.neo4j_skipped = True
        result.neo4j_output = "zeus-brain-neo4j container not running"
        print("[enricher] Neo4j container not detected — skipping Neo4j load.", file=sys.stderr)
    elif dry_run:
        print(f"[enricher dry-run] would run: {LOAD_NEO4J_SCRIPT}")
        result.neo4j_success = True
        result.neo4j_output = "[dry-run]"
    else:
        print("[enricher] Loading BDG into Neo4j...")
        ok, out = _run_script(LOAD_NEO4J_SCRIPT, timeout=300)
        result.neo4j_success = ok
        result.neo4j_output = out
        if not ok:
            print(f"[enricher] WARNING: Neo4j load failed:\n{out}", file=sys.stderr)
        else:
            print("[enricher] Neo4j load complete.")

    return result
