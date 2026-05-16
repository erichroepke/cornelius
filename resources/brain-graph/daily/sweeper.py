"""
Brain Daily Ingest - Inventory Sweeper

Walks the scan paths, computes md5+mtime diff against the previous run state,
and returns the list of NEW or CHANGED files since the last sweep.

State is persisted in data/raw-inventory.last.json:
    { "<abs_path>": {"md5": "...", "mtime": 1234567890.0, "size": 12345} }

Design notes:
  - Pure stdlib: hashlib, os, json, pathlib, fnmatch.
  - External drives are accessed via zsh -c subprocess (TCC-safe pattern).
  - Files in EXCLUDE_DIRS are silently skipped.
  - md5 is only computed when mtime OR size has changed (fast-path guard).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
DATA_DIR = _HERE.parent / "data"
STATE_FILE = DATA_DIR / "raw-inventory.last.json"

HOME = Path.home()
BRAIN_PATH = HOME / "Desktop" / "Brain"

# ---------------------------------------------------------------------------
# Scan configuration
# ---------------------------------------------------------------------------

#: Top-level directories to walk. Keep DEPTH SHALLOW — loose drops only.
#: Deep project trees should NOT be ingested wholesale. Project folders that
#: should be indexed go through Neo4j federation via vaults-registry.json instead.
#: Inbox/ directories anywhere get unlimited depth (per INBOX_NAMES).
SCAN_ROOTS: list[dict] = [
    # depth=0 means ROOT FILES ONLY — no recursion into project subfolders.
    # Project content lives in its own folder and is indexed via Neo4j federation,
    # not the daily ingestion routine. Loose drops at Desktop/Documents root are
    # the only "anywhere on disk" surface we auto-sweep.
    {"path": HOME / "Desktop",   "max_depth": 0},
    {"path": HOME / "Documents", "max_depth": 0},
    # Downloads often nests one level deep (a download folder for a specific thing)
    # but rarely more, so depth=1 catches the common case without project explosion.
    {"path": HOME / "Downloads", "max_depth": 1},
]

#: Any directory named exactly "Inbox" or "inbox" found anywhere under HOME
#: is added as an unlimited-depth target.
INBOX_NAMES: frozenset[str] = frozenset({"Inbox", "inbox", "INBOX"})

#: Glob patterns for directory names to skip entirely (fnmatch-based — name match,
#: not path match — so 'Brain' anywhere in the walk is skipped).
EXCLUDE_DIR_PATTERNS: tuple[str, ...] = (
    # System / build / cache
    ".Trash",
    "Library",
    "Movies",
    "Pictures",
    "Music",
    ".cache",
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    "site-packages",
    # Ephemeral Codex CLI worktrees — git clones that mutate constantly. Each
    # clone duplicates entire Zeus tree; sweeping them creates drift between
    # snapshot + sweep because the worktrees change between runs.
    ".codex",
    "worktrees",
    ".worktrees",
    # Skill / plugin code, not user content. The Cornelius "/extract-insights"
    # skill folder has its own template INBOX dir that's empty scaffolding.
    "plugins",
    # Obsidian _zeus subdirectories hold template scaffolding, not real content.
    # PROJECT_TEMPLATE/INBOX is an empty stub the project-init script copies from.
    "_zeus",
    ".zeus-system",
    "PROJECT_TEMPLATE",
    # Backups and historical mirrors — frozen state, not new content.
    "snapshots",
    # React/frontend component dirs (e.g. arc/frontend/src/components/inbox)
    # are code, not content.
    "components",
    # Cornelius BDG outputs — don't re-ingest our own
    "AI Extracted Notes",
    "Document Insights",
    # Brain itself — sweeper brings content INTO Brain; never recurses INTO Brain.
    # All ingestion lands in Brain/raw/ via the router; nothing inside Brain should
    # be picked up by the sweeper as if it were new external content.
    "Brain",
    # Backup of Brain from the Team C/D restructure — temporary, do not re-ingest.
    "Brain.pre-cleanup-2026-05-13",
    # NIKLAS is frozen READONLY per the v2 plan (atoms verified subset of Brain).
    # 2.5M files including 271k auto-gen droppings. Do NOT sweep.
    "NIKLAS",
    # Project vaults — federated via Neo4j origin_vault tags, not via daily routine.
    # These have their own dev workflows; daily routine must not interfere.
    "BERT",
    "BERT-Wiki",
    "JIMMY 2 BRAIN",
    "1-2026_ARC",
    # WHISKEY 2 vault paths (1.4 TB) — indexed in place by Neo4j ETL, not by daily.
    "ZEUS_PROJECTS",
    # Generic Cornelius/code installs that should never be ingested as content.
    "Cornelius",
    "Trinity",
    "Abilities",
)

#: File extensions we care about (case-insensitive).
#: Bias TOWARD knowledge content (text-like) and AWAY from large media files.
#: Video/audio captured INSIDE Inbox/ dirs still gets picked up since INBOX_NAMES
#: walk is separate. Loose Desktop videos are NOT ingested — they belong in their
#: own project folder, not the brain.
WANTED_EXTENSIONS: frozenset[str] = frozenset({
    # Notes — primary
    ".md", ".txt", ".org",
    # Documents
    ".pdf", ".docx", ".doc", ".rtf",
    # Ebooks
    ".epub", ".mobi",
    # Audio (often voice notes / podcast snippets)
    ".mp3", ".m4a", ".wav",
    # Images — loose captures + screenshots (mtime-filterable; see MIN_MTIME_DAYS)
    ".png", ".jpg", ".jpeg", ".heic",
    # Data / config (small)
    ".json", ".yaml", ".yml", ".csv",
})

#: Maximum age of file to consider "new" on FIRST sweep (no state file).
#: Subsequent sweeps catch any change regardless of age via mtime+md5 diff.
#: 90 days default = catches "recent" content without ingesting old archives.
MIN_MTIME_DAYS_ON_FIRST_SWEEP: int = 90

#: Maximum file size to process (100 MB). Larger files are inventoried but
#: flagged as oversized so the processor can skip them.
MAX_PROCESS_SIZE_BYTES: int = 100 * 1024 * 1024


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FileRecord:
    """A single entry in the sweep inventory."""
    path: Path
    md5: str
    mtime: float
    size: int
    is_new: bool          # True = never seen before; False = changed
    oversized: bool = False

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "md5": self.md5,
            "mtime": self.mtime,
            "size": self.size,
            "is_new": self.is_new,
            "oversized": self.oversized,
        }

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()


@dataclass
class SweepResult:
    """Return value of run_sweep()."""
    new_files: list[FileRecord] = field(default_factory=list)
    changed_files: list[FileRecord] = field(default_factory=list)
    scanned_count: int = 0
    skipped_count: int = 0
    error_paths: list[str] = field(default_factory=list)
    sweep_time: str = ""

    @property
    def all_changed(self) -> list[FileRecord]:
        """All files that need processing (new + changed)."""
        return self.new_files + self.changed_files

    def summary(self) -> str:
        return (
            f"Sweep: scanned={self.scanned_count} skipped={self.skipped_count} "
            f"new={len(self.new_files)} changed={len(self.changed_files)} "
            f"errors={len(self.error_paths)}"
        )


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

def load_state() -> dict[str, dict]:
    """Load the previous sweep state. Returns {} if not found."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict[str, dict]) -> None:
    """Atomically save the sweep state."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        with tmp.open("w") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
    except OSError as exc:
        print(f"[sweeper] WARNING: could not save state: {exc}", file=sys.stderr)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_skip_dir(name: str) -> bool:
    """Return True if a directory should be excluded from the walk."""
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_DIR_PATTERNS)


def _md5_of_file(path: Path) -> Optional[str]:
    """Compute md5 hex digest of a file. Returns None on read error."""
    h = hashlib.md5()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _stat(path: Path) -> Optional[os.stat_result]:
    """stat() without raising."""
    try:
        return path.stat()
    except OSError:
        return None


def _discover_inbox_dirs() -> list[Path]:
    """
    Walk HOME and collect directories named Inbox/inbox/INBOX.
    Uses os.scandir for speed; prunes known exclusions.
    """
    found: list[Path] = []

    def _walk(root: Path, depth: int) -> None:
        if depth > 8:
            return
        try:
            with os.scandir(root) as it:
                for entry in it:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if _should_skip_dir(entry.name):
                        continue
                    p = Path(entry.path)
                    if entry.name in INBOX_NAMES:
                        found.append(p)
                    _walk(p, depth + 1)
        except (PermissionError, OSError):
            pass

    _walk(HOME, 0)
    return found


def _files_in_dir(root: Path, max_depth: int) -> list[Path]:
    """
    Enumerate files under root up to max_depth levels deep.
    max_depth=0 means root itself only; -1 means unlimited.
    """
    result: list[Path] = []

    def _walk(current: Path, depth: int) -> None:
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        if _should_skip_dir(entry.name):
                            continue
                        if max_depth == -1 or depth < max_depth:
                            _walk(Path(entry.path), depth + 1)
                    elif entry.is_file(follow_symlinks=False):
                        result.append(Path(entry.path))
        except (PermissionError, OSError):
            pass

    _walk(root, 0)
    return result


# ---------------------------------------------------------------------------
# Core sweep
# ---------------------------------------------------------------------------

def run_sweep(dry_run: bool = False) -> SweepResult:
    """
    Walk all scan paths, diff against previous state, return SweepResult.

    Idempotent: calling this twice on the same day (with no new files) returns
    an empty result because state already reflects the current filesystem.

    If dry_run=True, state is NOT saved after the sweep.
    """
    prev_state = load_state()
    new_state: dict[str, dict] = {}
    # Apply mtime cutoff on EVERY sweep, not just the first. If we only gate on
    # first sweep, then any file older than the cutoff that wasn't in the initial
    # snapshot (e.g. existed but was below the cutoff) will appear as "new" on
    # subsequent sweeps once the gate drops — that's drift and explodes the diff.
    # Daily routine scope: files modified within the trailing window. Out-of-window
    # files are archival, not daily-actionable. To ingest archives, use a separate
    # one-shot command, not the daily sweep.
    min_mtime_cutoff: float = datetime.now().timestamp() - (MIN_MTIME_DAYS_ON_FIRST_SWEEP * 86400)

    result = SweepResult(sweep_time=datetime.now().isoformat())

    # Build de-duplicated set of scan roots
    scan_targets: list[tuple[Path, int]] = []
    seen_roots: set[Path] = set()

    for cfg in SCAN_ROOTS:
        p = Path(cfg["path"])
        if p.exists() and p not in seen_roots:
            scan_targets.append((p, cfg["max_depth"]))
            seen_roots.add(p)

    for inbox_dir in _discover_inbox_dirs():
        if inbox_dir not in seen_roots:
            scan_targets.append((inbox_dir, -1))  # unlimited depth
            seen_roots.add(inbox_dir)

    # Enumerate files
    all_files: list[Path] = []
    for root, max_depth in scan_targets:
        all_files.extend(_files_in_dir(root, max_depth))

    # De-duplicate by resolved path
    seen_paths: set[str] = set()
    unique_files: list[Path] = []
    for fp in all_files:
        key = str(fp.resolve())
        if key not in seen_paths:
            seen_paths.add(key)
            unique_files.append(fp)

    result.scanned_count = len(unique_files)

    for fp in unique_files:
        ext = fp.suffix.lower()
        if ext not in WANTED_EXTENSIONS:
            result.skipped_count += 1
            continue

        st = _stat(fp)
        if st is None:
            result.error_paths.append(str(fp))
            continue

        mtime = st.st_mtime
        size = st.st_size
        key = str(fp)

        # Age filter (always-on): skip files outside the trailing daily window.
        # Files older than the cutoff are archival; daily routine ignores them.
        if mtime < min_mtime_cutoff:
            result.skipped_count += 1
            continue

        prev = prev_state.get(key)

        # Fast-path: if mtime and size match, skip md5 computation
        if prev and prev["mtime"] == mtime and prev["size"] == size:
            new_state[key] = prev
            result.skipped_count += 1
            continue

        # mtime or size changed — compute md5
        md5 = _md5_of_file(fp)
        if md5 is None:
            result.error_paths.append(key)
            continue

        entry = {"md5": md5, "mtime": mtime, "size": size}
        new_state[key] = entry

        # Compare against previous state
        oversized = size > MAX_PROCESS_SIZE_BYTES
        if prev is None:
            result.new_files.append(FileRecord(
                path=fp, md5=md5, mtime=mtime, size=size,
                is_new=True, oversized=oversized,
            ))
        elif prev["md5"] != md5:
            result.changed_files.append(FileRecord(
                path=fp, md5=md5, mtime=mtime, size=size,
                is_new=False, oversized=oversized,
            ))
        else:
            # md5 same — mtime artifact (e.g. copy operation); treat as skipped
            result.skipped_count += 1

    if not dry_run:
        save_state(new_state)

    return result
