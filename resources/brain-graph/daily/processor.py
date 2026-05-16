"""
Brain Daily Ingest - Processor

For each routed file, the processor:
    1. Copies the file into the proposed Brain destination (NEVER moves — original preserved).
    2. If source_type is PERSONAL_NOTE or SESSION_CAPTURE, invokes /extract-insights
       via `claude -p` headless mode.
    3. If source_type is DOCUMENT (PDF/EPUB/article), invokes /extract-document-insights.
    4. Skips audio/video/image/data files (no skill invocation; file copy only).
    5. Enforces a per-run budget cap (--max-cost-cents). Aborts skill invocations
       when the cap is exceeded; file copies continue regardless.

Trust graduated:
    - AUTO   → file is copied immediately.
    - REVIEW → file is copied to destination; no skill invocation until human promotes.
    - SKIP   → nothing happens.

All actions are logged to the SQLite audit database (daily_audit.db) via _log_action().

Iron laws:
    - rm is FORBIDDEN. Originals are never touched.
    - 02-Permanent/ is FORBIDDEN as a copy destination.
    - External-drive writes use zsh -c subprocess (TCC-safe).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .sweeper import FileRecord, BRAIN_PATH, DATA_DIR
from .router import RoutingDecision, SourceType, Trust, Dest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
AUDIT_DB = DATA_DIR / "daily_audit.db"

#: Cornelius root (two levels up from brain-graph/)
CORNELIUS_ROOT = Path(__file__).parent.parent.parent.parent

#: Headless claude binary
CLAUDE_BIN = "claude"

#: Default budget cap in US cents
DEFAULT_MAX_COST_CENTS: int = 500  # $5.00

#: Session folder prefix for document-insight-extractor
SESSION_PREFIX = "daily-ingest"

# ---------------------------------------------------------------------------
# Audit DB
# ---------------------------------------------------------------------------

def _ensure_db() -> sqlite3.Connection:
    """Create/open the audit DB and ensure the actions table exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUDIT_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingest_actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date    TEXT NOT NULL,
            ts          TEXT NOT NULL,
            action      TEXT NOT NULL,
            src_path    TEXT NOT NULL,
            dst_path    TEXT,
            skill       TEXT,
            trust       TEXT,
            source_type TEXT,
            success     INTEGER NOT NULL DEFAULT 1,
            notes       TEXT
        )
    """)
    conn.commit()
    return conn


def _log_action(
    conn: sqlite3.Connection,
    run_date: str,
    action: str,
    src_path: str,
    dst_path: Optional[str] = None,
    skill: Optional[str] = None,
    trust: str = "",
    source_type: str = "",
    success: bool = True,
    notes: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO ingest_actions
            (run_date, ts, action, src_path, dst_path, skill, trust, source_type, success, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_date,
            datetime.now().isoformat(),
            action,
            src_path,
            dst_path,
            skill,
            trust,
            source_type,
            1 if success else 0,
            notes,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ProcessResult:
    """Outcome of processing a single file."""
    record: FileRecord
    decision: RoutingDecision
    copied: bool = False
    dst_path: Optional[Path] = None
    skill_invoked: Optional[str] = None
    skill_success: bool = False
    skill_output_path: Optional[Path] = None
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""


@dataclass
class BatchProcessResult:
    """Aggregate outcome for the whole processor run."""
    results: list[ProcessResult] = field(default_factory=list)
    total_cost_cents: int = 0
    budget_hit: bool = False

    @property
    def copied_count(self) -> int:
        return sum(1 for r in self.results if r.copied)

    @property
    def skill_count(self) -> int:
        return sum(1 for r in self.results if r.skill_success)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.error)


# ---------------------------------------------------------------------------
# File copy (TCC-safe)
# ---------------------------------------------------------------------------

def _safe_copy(src: Path, dst: Path) -> bool:
    """
    Copy src to dst using zsh -c to preserve TCC (FDA) on external drives.
    dst parent is created if needed.
    Returns True on success.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Use zsh subprocess — Ghostty/zsh has FDA, Python subprocess may not
    cmd = f'cp -n {_shell_quote(str(src))} {_shell_quote(str(dst))}'
    try:
        result = subprocess.run(
            ["/bin/zsh", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        # Fallback to shutil for internal drives
        try:
            shutil.copy2(str(src), str(dst))
            return True
        except OSError:
            return False


def _shell_quote(s: str) -> str:
    """Minimal shell quoting for single-argument paths."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _unique_dst(dst_dir: Path, filename: str) -> Path:
    """Return a unique destination path (appends _N if collision exists)."""
    dst = dst_dir / filename
    if not dst.exists():
        return dst
    stem = dst.stem
    suffix = dst.suffix
    n = 1
    while True:
        candidate = dst_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Skill invocation via `claude -p`
# ---------------------------------------------------------------------------

def _invoke_extract_insights(src_path: Path, session_date: str) -> tuple[bool, str, Optional[Path]]:
    """
    Invoke Cornelius /extract-insights in headless mode.
    Returns (success, output_text, output_path_or_None).
    """
    prompt = (
        f"/extract-insights {src_path}\n\n"
        f"Session context: daily-ingest {session_date}. "
        f"Extract unique personal insights and route to AI Extracted Notes/."
    )
    return _run_claude_headless(prompt, "extract-insights")


def _invoke_extract_document_insights(
    src_path: Path,
    session_date: str,
) -> tuple[bool, str, Optional[Path]]:
    """
    Invoke Cornelius /extract-document-insights in headless mode.
    Session folder: "daily-ingest YYYY-MM-DD".
    Returns (success, output_text, output_path_or_None).
    """
    session_folder = f"daily-ingest {session_date}"
    prompt = (
        f"/extract-document-insights {src_path}\n\n"
        f"Session folder: {session_folder}. "
        f"This is an external document — extract key insights with proper attribution."
    )
    return _run_claude_headless(prompt, "extract-document-insights")


def _run_claude_headless(prompt: str, skill_name: str) -> tuple[bool, str, Optional[Path]]:
    """
    Run `claude -p <prompt>` from the Cornelius root directory.
    Returns (success, stdout_text, None).  Output path detection is left to the
    caller — skills write files to known locations inside Brain.

    IMPORTANT: `claude -p` uses the active Cornelius session/context because we
    cd into CORNELIUS_ROOT where CLAUDE.md lives.  No API key needed — uses
    Anthropic auth from Claude Code's own credential store.
    """
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--output-format", "text"],
            cwd=str(CORNELIUS_ROOT),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes max per skill invocation
        )
        success = proc.returncode == 0
        output = proc.stdout.strip() if proc.stdout else ""
        if proc.returncode != 0:
            output += f"\n[stderr]: {proc.stderr.strip()}"
        return success, output, None
    except subprocess.TimeoutExpired:
        return False, f"[{skill_name}] timed out after 300s", None
    except FileNotFoundError:
        return False, f"[{skill_name}] 'claude' binary not found in PATH", None
    except OSError as exc:
        return False, f"[{skill_name}] OS error: {exc}", None


# ---------------------------------------------------------------------------
# Core processor
# ---------------------------------------------------------------------------

def _should_invoke_skill(decision: RoutingDecision) -> Optional[str]:
    """
    Returns the skill name to invoke, or None if no skill should run.

    Skills are only invoked when trust is AUTO and source_type warrants it.
    REVIEW-trust files are copied but not processed (human promotes them).
    """
    if decision.trust != Trust.AUTO:
        return None
    if decision.source_type in (SourceType.PERSONAL_NOTE, SourceType.SESSION_CAPTURE):
        return "extract-insights"
    if decision.source_type == SourceType.DOCUMENT:
        return "extract-document-insights"
    return None


def process_file(
    record: FileRecord,
    decision: RoutingDecision,
    conn: sqlite3.Connection,
    run_date: str,
    dry_run: bool = False,
    max_cost_cents: int = DEFAULT_MAX_COST_CENTS,
    current_cost_cents: int = 0,
) -> ProcessResult:
    """
    Process a single file:
      1. Validate destination (never 02-Permanent).
      2. Copy file to destination (skipped in dry-run).
      3. Invoke skill if warranted and budget allows.
    Returns a ProcessResult.
    """
    result = ProcessResult(record=record, decision=decision)

    # Guard: trust=SKIP → do nothing
    if decision.trust == Trust.SKIP:
        result.skipped = True
        result.skip_reason = "trust=SKIP"
        return result

    # Guard: oversized → copy only, no skill
    if record.oversized:
        result.skip_reason = f"file exceeds {100}MB limit; copy only, no skill"

    # Guard: destination must never be 02-Permanent
    dst_dir = decision.destination_path
    if "02-Permanent" in str(dst_dir):
        result.skipped = True
        result.skip_reason = "destination 02-Permanent is forbidden; routing to To Process instead"
        dst_dir = BRAIN_PATH / Dest.INBOX_TO_PROCESS.value
        _log_action(conn, run_date, "REROUTE", str(record.path),
                    str(dst_dir), trust=decision.trust.value,
                    source_type=decision.source_type.value, success=True,
                    notes=result.skip_reason)
        decision = RoutingDecision(
            source_type=decision.source_type,
            destination=Dest.INBOX_TO_PROCESS,
            trust=Trust.REVIEW,
            reason="rerouted away from 02-Permanent",
        )

    # Determine destination filename
    filename = record.path.name
    dst_path = _unique_dst(dst_dir, filename)
    result.dst_path = dst_path

    if not dry_run:
        ok = _safe_copy(record.path, dst_path)
        result.copied = ok
        _log_action(
            conn, run_date, "COPY",
            str(record.path), str(dst_path),
            trust=decision.trust.value,
            source_type=decision.source_type.value,
            success=ok,
            notes=decision.reason if not ok else "",
        )
        if not ok:
            result.error = f"copy failed: {record.path} -> {dst_path}"
            return result
    else:
        result.copied = True  # pretend in dry-run

    # Skill invocation
    skill = _should_invoke_skill(decision)
    if skill is None or record.oversized:
        return result

    # Budget check — cost estimation is approximate (1 page PDF ~$0.001)
    # We use a simple heuristic: each skill call costs ~10 cents max
    ESTIMATED_SKILL_COST_CENTS = 10
    if current_cost_cents + ESTIMATED_SKILL_COST_CENTS > max_cost_cents:
        result.skip_reason = (
            f"budget cap {max_cost_cents}c reached "
            f"(current={current_cost_cents}c); skill skipped"
        )
        return result

    result.skill_invoked = skill

    if not dry_run:
        if skill == "extract-insights":
            success, output, out_path = _invoke_extract_insights(
                dst_path, run_date
            )
        else:
            success, output, out_path = _invoke_extract_document_insights(
                dst_path, run_date
            )

        result.skill_success = success
        result.skill_output_path = out_path

        _log_action(
            conn, run_date, f"SKILL:{skill}",
            str(record.path), str(out_path) if out_path else None,
            skill=skill,
            trust=decision.trust.value,
            source_type=decision.source_type.value,
            success=success,
            notes=output[:500] if output else "",
        )
    else:
        result.skill_success = True  # pretend in dry-run

    return result


def process_batch(
    pairs: list[tuple[FileRecord, RoutingDecision]],
    run_date: str,
    dry_run: bool = False,
    max_cost_cents: int = DEFAULT_MAX_COST_CENTS,
) -> BatchProcessResult:
    """
    Process all (record, decision) pairs in sequence.
    Maintains a rolling cost counter to enforce the budget cap.
    """
    conn = _ensure_db()
    batch = BatchProcessResult()
    cost = 0

    for record, decision in pairs:
        if batch.budget_hit:
            # Budget exhausted — copy only, no more skills
            decision_no_skill = RoutingDecision(
                source_type=decision.source_type,
                destination=decision.destination,
                trust=Trust.REVIEW,  # demote to REVIEW so no skill fires
                reason=decision.reason + " [budget cap]",
            )
            pr = process_file(
                record, decision_no_skill, conn, run_date,
                dry_run=dry_run, max_cost_cents=max_cost_cents,
                current_cost_cents=cost,
            )
        else:
            pr = process_file(
                record, decision, conn, run_date,
                dry_run=dry_run, max_cost_cents=max_cost_cents,
                current_cost_cents=cost,
            )
            if pr.skill_success and pr.skill_invoked:
                cost += 10  # rough estimate per skill call
                if cost >= max_cost_cents:
                    batch.budget_hit = True

        batch.results.append(pr)

    batch.total_cost_cents = cost
    conn.close()
    return batch


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def rollback_date(run_date: str, dry_run: bool = False) -> list[str]:
    """
    Undo all COPY actions logged for run_date by moving dst_path to Trash.
    Returns list of rollback messages.

    Files are MOVED to ~/.Trash/<original_name> (not deleted).
    """
    if not AUDIT_DB.exists():
        return ["Audit DB not found — nothing to roll back."]

    conn = sqlite3.connect(str(AUDIT_DB))
    rows = conn.execute(
        "SELECT src_path, dst_path FROM ingest_actions WHERE run_date=? AND action='COPY' AND success=1",
        (run_date,),
    ).fetchall()
    conn.close()

    if not rows:
        return [f"No successful COPY actions found for {run_date}."]

    trash = Path.home() / ".Trash"
    messages: list[str] = []

    for src_path, dst_path in rows:
        if not dst_path:
            continue
        dst = Path(dst_path)
        if not dst.exists():
            messages.append(f"SKIP (already gone): {dst_path}")
            continue

        trash_target = _unique_dst(trash, dst.name)
        if not dry_run:
            cmd = (
                f'mv {_shell_quote(str(dst))} {_shell_quote(str(trash_target))}'
            )
            result = subprocess.run(
                ["/bin/zsh", "-c", cmd],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                messages.append(f"MOVED to Trash: {dst_path}")
            else:
                messages.append(f"ERROR moving {dst_path}: {result.stderr.strip()}")
        else:
            messages.append(f"[dry-run] would move to Trash: {dst_path}")

    return messages
