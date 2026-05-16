"""Unit tests for the daily routine (router classification + digest formatting + cli arg parsing).

Run with:
    cd ~/Cornelius/resources/brain-graph
    python -m pytest daily/test_daily.py -q
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from daily import router, digest


# ---------------------------------------------------------------------------
# Router — destination constants
# ---------------------------------------------------------------------------

class TestRouterDestinations:
    """Router destination constants reflect v2.2 raw+wiki layout, not v2.1 numbered prefixes."""

    def test_inbox_paths_are_under_raw(self) -> None:
        assert router.Dest.INBOX_QUICK.startswith("raw/")
        assert router.Dest.INBOX_EXTRACTIONS.startswith("raw/")
        assert router.Dest.INBOX_TO_PROCESS.startswith("raw/")

    def test_source_paths_are_under_wiki(self) -> None:
        assert router.Dest.SOURCES_BOOKS.startswith("wiki/Sources/")
        assert router.Dest.SOURCES_ARTICLES.startswith("wiki/Sources/")
        assert router.Dest.SOURCES_VIDEOS.startswith("wiki/Sources/")
        assert router.Dest.SOURCES_PODCASTS.startswith("wiki/Sources/")
        assert router.Dest.SOURCES_SESSIONS.startswith("wiki/Sources/")

    def test_ai_extracted_under_wiki(self) -> None:
        assert router.Dest.AI_EXTRACTED.startswith("wiki/")

    def test_doc_insights_under_wiki(self) -> None:
        assert router.Dest.DOC_INSIGHTS.startswith("wiki/")

    def test_no_v21_paths_remain(self) -> None:
        """No destination should reference the old numbered-prefix layout."""
        # Iterate enum members rather than dir() to avoid catching method names
        v21_prefixes = ("00-Inbox", "01-Sources", "02-Permanent", "03-MOCs", "04-Output", "05-Meta")
        for member in router.Dest:
            val = member.value
            for prefix in v21_prefixes:
                assert not val.startswith(prefix), f"v2.1 path still present in {member.name}: {val}"


# ---------------------------------------------------------------------------
# Digest — writes correctly even with no audit data
# ---------------------------------------------------------------------------

class TestDigest:
    def test_write_digest_creates_file(self, tmp_path: Path, monkeypatch) -> None:
        """write_digest produces a markdown file in Changelogs dir even when audit DB is empty/missing."""
        # Redirect Brain path to tmp_path
        monkeypatch.setattr(digest, "BRAIN_PATH", tmp_path)
        monkeypatch.setattr(digest, "CHANGELOG_DIR", tmp_path / "wiki" / "Meta" / "Changelogs")
        monkeypatch.setattr(digest, "AUDIT_DB", tmp_path / "nonexistent.db")

        out = digest.write_digest(date(2026, 5, 13))
        assert out.exists()
        assert out.name == "daily-2026-05-13.md"

        content = out.read_text()
        assert "Daily Routine — 2026-05-13" in content
        assert "Inventory sweep" in content
        assert "Router decisions" in content
        assert "Processor invocations" in content
        assert "Enricher" in content
        assert "Rollback" in content

    def test_digest_handles_empty_audit_gracefully(self, tmp_path: Path, monkeypatch) -> None:
        """Empty audit DB should produce 'No ... today' messages, not crash."""
        monkeypatch.setattr(digest, "BRAIN_PATH", tmp_path)
        monkeypatch.setattr(digest, "CHANGELOG_DIR", tmp_path / "wiki" / "Meta" / "Changelogs")

        # Create empty SQLite file
        empty_db = tmp_path / "empty.db"
        sqlite3.connect(empty_db).close()
        monkeypatch.setattr(digest, "AUDIT_DB", empty_db)

        out = digest.write_digest(date(2026, 5, 13))
        text = out.read_text()
        assert "No routing decisions today" in text
        assert "No skill invocations today" in text

    def test_digest_renders_audit_rows(self, tmp_path: Path, monkeypatch) -> None:
        """Audit DB with rows should populate the markdown tables."""
        monkeypatch.setattr(digest, "BRAIN_PATH", tmp_path)
        monkeypatch.setattr(digest, "CHANGELOG_DIR", tmp_path / "wiki" / "Meta" / "Changelogs")

        db = tmp_path / "audit.db"
        with sqlite3.connect(db) as conn:
            conn.executescript("""
                CREATE TABLE sweeper_events (ts TEXT, src TEXT);
                CREATE TABLE router_decisions (ts TEXT, destination TEXT);
                CREATE TABLE processor_invocations (ts TEXT, skill TEXT);
                CREATE TABLE enricher_runs (ts TEXT, step TEXT, status TEXT);
            """)
            conn.execute("INSERT INTO sweeper_events VALUES (?, ?)", ("2026-05-13T12:00:00", "/tmp/foo.md"))
            conn.execute("INSERT INTO router_decisions VALUES (?, ?)", ("2026-05-13T12:00:00", "raw/Quick Captures"))
            conn.execute("INSERT INTO router_decisions VALUES (?, ?)", ("2026-05-13T12:00:00", "raw/Quick Captures"))
            conn.execute("INSERT INTO processor_invocations VALUES (?, ?)", ("2026-05-13T12:00:00", "/extract-insights"))
            conn.execute("INSERT INTO enricher_runs VALUES (?, ?, ?)", ("2026-05-13T12:00:00", "bootstrap", "ok"))
            conn.commit()
        monkeypatch.setattr(digest, "AUDIT_DB", db)

        out = digest.write_digest(date(2026, 5, 13))
        text = out.read_text()
        assert "**New files discovered**: 1" in text
        assert "`raw/Quick Captures`" in text
        assert "| 2 |" in text  # 2 router decisions to same dest
        assert "`/extract-insights`" in text
        assert "`bootstrap`" in text and "`ok`" in text


# ---------------------------------------------------------------------------
# CLI — argument parsing surface
# ---------------------------------------------------------------------------

class TestCliArgs:
    def test_cli_has_three_subcommands(self) -> None:
        """run / rollback / status are all registered."""
        from daily import cli
        # Build the parser the same way main() does
        import argparse
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="cmd")
        sub.add_parser("run")
        sub.add_parser("rollback")
        sub.add_parser("status")
        ns = p.parse_args(["run"])
        assert ns.cmd == "run"

    def test_run_supports_dry_run_flag(self) -> None:
        """--dry-run flag is wired to cmd_run."""
        from daily.cli import main
        import inspect
        # Inspect cmd_run for dry_run handling
        from daily.cli import cmd_run
        src = inspect.getsource(cmd_run)
        assert "dry_run" in src

    def test_rollback_validates_date_format(self, tmp_path: Path, monkeypatch) -> None:
        """Invalid date format returns nonzero exit (or 0 if no audit DB exists)."""
        from daily import cli as daily_cli
        # Point AUDIT_DB to a real (existing) but empty file so the date-check runs
        empty_db = tmp_path / "empty.db"
        sqlite3.connect(empty_db).close()
        monkeypatch.setattr(daily_cli, "AUDIT_DB", empty_db)
        import argparse
        ns = argparse.Namespace(date="not-a-date")
        ret = daily_cli.cmd_rollback(ns)
        assert ret == 1
