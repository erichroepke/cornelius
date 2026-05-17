"""
Brain Daily Ingest - Router

Classifies each incoming file and proposes a destination inside the Brain vault.

Classification order (first match wins):
    1. Frontmatter `type` field (for .md files)
    2. Extension group (audio, video, PDF, EPUB, etc.)
    3. Filename / path heuristics (contains "inbox", "session", etc.)
    4. Default: 00-Inbox/To Process/

Trust levels:
    - AUTO  : Router is highly confident; processor may act immediately.
    - REVIEW: Confidence is moderate; file lands in 00-Inbox/* for human review.
    - SKIP  : File should not be ingested (temporary, binary noise, etc.).

The router NEVER proposes 02-Permanent/ as a destination — that requires
explicit human action (the graduate-insights skill).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .sweeper import FileRecord, BRAIN_PATH

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Trust(str, Enum):
    AUTO   = "auto"    # High confidence — processor may act
    REVIEW = "review"  # Moderate — drop in inbox for human
    SKIP   = "skip"    # Do not ingest


class SourceType(str, Enum):
    """Maps to Cornelius skill selection."""
    PERSONAL_NOTE   = "personal_note"    # extract-insights
    DOCUMENT        = "document"         # extract-document-insights
    AUDIO           = "audio"            # (future: whisper transcription)
    VIDEO           = "video"            # (future: footage-analysis)
    IMAGE           = "image"            # (future: vision OCR)
    SESSION_CAPTURE = "session_capture"  # extract-insights (high priority)
    DATA            = "data"             # skip processing; just route
    ARCHIVE         = "archive"          # skip processing; just route
    UNKNOWN         = "unknown"


# ---------------------------------------------------------------------------
# Destination map (relative to BRAIN_PATH)
# ---------------------------------------------------------------------------

class Dest(str, Enum):
    # Paths reflect v2.2 raw/+wiki/ two-tier Brain layout.
    INBOX_QUICK       = "raw/Quick Captures"
    INBOX_EXTRACTIONS = "raw/Content Extractions"
    INBOX_TO_PROCESS  = "raw/To Process"
    SOURCES_BOOKS     = "wiki/Sources/Books"
    SOURCES_ARTICLES  = "wiki/Sources/Articles"
    SOURCES_VIDEOS    = "wiki/Sources/Videos"
    SOURCES_PODCASTS  = "wiki/Sources/Podcasts"
    SOURCES_SESSIONS  = "wiki/Sources/Sessions"
    SOURCES_ROOT      = "wiki/Sources"
    AI_EXTRACTED      = "wiki/AI Extracted Notes"
    DOC_INSIGHTS      = "wiki/Document Insights"


# Backward-compat alias for tests that reference router.Destinations
Destinations = Dest


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    """Result of routing a single file."""
    source_type: SourceType
    destination: Dest
    trust: Trust
    reason: str
    proposed_filename: Optional[str] = None  # None = keep original

    @property
    def destination_path(self) -> Path:
        return BRAIN_PATH / self.destination.value


# ---------------------------------------------------------------------------
# Frontmatter reader (re-uses pattern from classify.py)
# ---------------------------------------------------------------------------

def _parse_frontmatter(path: Path) -> dict:
    """Extract YAML frontmatter fields from a markdown file."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}

    result: dict = {}
    for line in content[3:end].strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

# Extension → (source_type, destination, trust)
_EXT_MAP: dict[str, tuple[SourceType, Dest, Trust]] = {
    # Audio
    ".mp3":  (SourceType.AUDIO, Dest.SOURCES_PODCASTS, Trust.REVIEW),
    ".m4a":  (SourceType.AUDIO, Dest.SOURCES_PODCASTS, Trust.REVIEW),
    ".wav":  (SourceType.AUDIO, Dest.SOURCES_PODCASTS, Trust.REVIEW),
    ".ogg":  (SourceType.AUDIO, Dest.SOURCES_PODCASTS, Trust.REVIEW),
    ".flac": (SourceType.AUDIO, Dest.SOURCES_PODCASTS, Trust.REVIEW),
    # Video
    ".mp4":  (SourceType.VIDEO, Dest.SOURCES_VIDEOS, Trust.REVIEW),
    ".mov":  (SourceType.VIDEO, Dest.SOURCES_VIDEOS, Trust.REVIEW),
    ".mkv":  (SourceType.VIDEO, Dest.SOURCES_VIDEOS, Trust.REVIEW),
    # Documents
    ".pdf":  (SourceType.DOCUMENT, Dest.INBOX_TO_PROCESS, Trust.AUTO),
    ".epub": (SourceType.DOCUMENT, Dest.SOURCES_BOOKS, Trust.AUTO),
    ".mobi": (SourceType.DOCUMENT, Dest.SOURCES_BOOKS, Trust.AUTO),
    ".docx": (SourceType.DOCUMENT, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".doc":  (SourceType.DOCUMENT, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".rtf":  (SourceType.DOCUMENT, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    # Images
    ".jpg":  (SourceType.IMAGE, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".jpeg": (SourceType.IMAGE, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".png":  (SourceType.IMAGE, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".gif":  (SourceType.IMAGE, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".webp": (SourceType.IMAGE, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".heic": (SourceType.IMAGE, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    # Data / config
    ".json": (SourceType.DATA, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".yaml": (SourceType.DATA, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".yml":  (SourceType.DATA, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".csv":  (SourceType.DATA, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    # Code
    ".py":   (SourceType.DATA, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".js":   (SourceType.DATA, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".ts":   (SourceType.DATA, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    ".sh":   (SourceType.DATA, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
    # Archive
    ".zip":  (SourceType.ARCHIVE, Dest.INBOX_TO_PROCESS, Trust.REVIEW),
}

# Filename patterns that signal a session capture (high-priority personal note)
_SESSION_PATTERNS: list[re.Pattern] = [
    re.compile(r"session", re.IGNORECASE),
    re.compile(r"\b(transcript|meeting|call|interview)\b", re.IGNORECASE),
    re.compile(r"\d{4}[-_]\d{2}[-_]\d{2}", re.IGNORECASE),  # dated files
]

# Daily ingest outputs are operational records, not source notes. Their dated
# filenames otherwise match _SESSION_PATTERNS and can get re-sent to extraction.
_GENERATED_OPERATIONAL_REPORT_SUFFIXES: tuple[str, ...] = (
    "quick_action_queue",
    "daily_action_queue",
    "quick_librarian_brief",
    "daily_librarian_brief",
    "quick_vault_sweep",
    "daily_vault_sweep",
)

# Frontmatter type → source type override
_FM_TYPE_MAP: dict[str, SourceType] = {
    "session":      SourceType.SESSION_CAPTURE,
    "transcript":   SourceType.SESSION_CAPTURE,
    "insight":      SourceType.PERSONAL_NOTE,
    "permanent":    SourceType.PERSONAL_NOTE,
    "note":         SourceType.PERSONAL_NOTE,
    "article":      SourceType.DOCUMENT,
    "source":       SourceType.DOCUMENT,
    "book":         SourceType.DOCUMENT,
    "podcast":      SourceType.AUDIO,
    "video":        SourceType.VIDEO,
}


def _normalized_stem(path: Path) -> str:
    """Normalize common separator variants for filename suffix matching."""
    return re.sub(r"[\s\-]+", "_", path.stem.lower())


def _is_generated_operational_report(path: Path) -> bool:
    """Return True for machine-generated ingest outputs that must not recurse."""
    stem = _normalized_stem(path)
    return any(stem.endswith(suffix) for suffix in _GENERATED_OPERATIONAL_REPORT_SUFFIXES)


def _route_markdown(record: FileRecord) -> RoutingDecision:
    """Apply frontmatter + heuristic classification for .md/.txt/.org files."""
    if _is_generated_operational_report(record.path):
        return RoutingDecision(
            source_type=SourceType.DATA,
            destination=Dest.SOURCES_SESSIONS,
            trust=Trust.SKIP,
            reason="generated operational report; not sent to insight extraction",
        )

    fm = _parse_frontmatter(record.path) if record.extension in (".md",) else {}
    note_type_raw = fm.get("type", "")
    if isinstance(note_type_raw, list):
        note_type_raw = note_type_raw[0] if note_type_raw else ""
    note_type = note_type_raw.lower()

    # Frontmatter override
    if note_type in _FM_TYPE_MAP:
        src_type = _FM_TYPE_MAP[note_type]
        if src_type == SourceType.SESSION_CAPTURE:
            return RoutingDecision(
                source_type=src_type,
                destination=Dest.SOURCES_SESSIONS,
                trust=Trust.AUTO,
                reason=f"frontmatter type='{note_type}'",
            )
        if src_type == SourceType.PERSONAL_NOTE:
            return RoutingDecision(
                source_type=src_type,
                destination=Dest.INBOX_QUICK,
                trust=Trust.AUTO,
                reason=f"frontmatter type='{note_type}'",
            )
        if src_type == SourceType.DOCUMENT:
            return RoutingDecision(
                source_type=src_type,
                destination=Dest.INBOX_EXTRACTIONS,
                trust=Trust.AUTO,
                reason=f"frontmatter type='{note_type}'",
            )

    # Session pattern in filename or parent dir
    stem = record.path.stem
    parent_name = record.path.parent.name
    for pat in _SESSION_PATTERNS:
        if pat.search(stem) or pat.search(parent_name):
            return RoutingDecision(
                source_type=SourceType.SESSION_CAPTURE,
                destination=Dest.SOURCES_SESSIONS,
                trust=Trust.AUTO,
                reason=f"filename/path matches session pattern '{pat.pattern}'",
            )

    # "Inbox" in parent path → quick capture
    if any(seg in INBOX_NAMES for seg in record.path.parts):
        return RoutingDecision(
            source_type=SourceType.PERSONAL_NOTE,
            destination=Dest.INBOX_QUICK,
            trust=Trust.AUTO,
            reason="file is inside an Inbox directory",
        )

    # Default for markdown
    return RoutingDecision(
        source_type=SourceType.PERSONAL_NOTE,
        destination=Dest.INBOX_QUICK,
        trust=Trust.REVIEW,
        reason="markdown with no type frontmatter — defaulting to Quick Captures",
    )


# Inbox-dir names (kept local to router too)
INBOX_NAMES: frozenset[str] = frozenset({"Inbox", "inbox", "INBOX"})


def route(record: FileRecord) -> RoutingDecision:
    """
    Classify a single FileRecord and return a RoutingDecision.

    This is the public API; everything else is implementation detail.
    """
    ext = record.extension

    # Markdown / text: deep heuristic
    if ext in (".md", ".txt", ".org"):
        return _route_markdown(record)

    # All other extensions: use extension map
    if ext in _EXT_MAP:
        src_type, dest, trust = _EXT_MAP[ext]

        # Refine audio: if filename contains "podcast" → podcasts; else voice memo
        if src_type == SourceType.AUDIO:
            stem_lower = record.path.stem.lower()
            if any(kw in stem_lower for kw in ("podcast", "episode", "ep")):
                dest = Dest.SOURCES_PODCASTS
            else:
                dest = Dest.INBOX_TO_PROCESS

        # Refine PDF: if parent dir name contains "book" → sources root
        if src_type == SourceType.DOCUMENT and ext == ".pdf":
            parent_lower = record.path.parent.name.lower()
            if "book" in parent_lower:
                dest = Dest.SOURCES_BOOKS

        return RoutingDecision(
            source_type=src_type,
            destination=dest,
            trust=trust,
            reason=f"extension '{ext}' mapped by EXT_MAP",
        )

    # Unknown extension — park in inbox
    return RoutingDecision(
        source_type=SourceType.UNKNOWN,
        destination=Dest.INBOX_TO_PROCESS,
        trust=Trust.REVIEW,
        reason=f"extension '{ext}' not in WANTED_EXTENSIONS (unexpected path here)",
    )


def route_batch(records: list[FileRecord]) -> list[tuple[FileRecord, RoutingDecision]]:
    """Route a list of FileRecords in one call. Returns (record, decision) pairs."""
    return [(r, route(r)) for r in records]
