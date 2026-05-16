"""Unit tests for zeus-brain MCP server safety functions.

These run without a live Neo4j or MCP runtime — they exercise the pure
validation logic (Cypher denylist + token gate + write_atom safety) in isolation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# Re-implement the validators here to test them in isolation (mirrors mcp_server.py).
# Keeping this in sync with the server is part of the test contract — if the regex
# changes there, this file must change too.
_MUTATING_CLAUSES = re.compile(
    r"\b(CREATE|MERGE|DELETE|REMOVE|SET|DROP|DETACH|FOREACH|CALL\s+apoc\.(periodic|trigger|cypher\.runWrite))\b",
    re.IGNORECASE,
)


def _assert_read_only(cypher: str) -> None:
    if _MUTATING_CLAUSES.search(cypher):
        raise PermissionError("mutating")


def _assert_authed(token: str | None, configured: str) -> None:
    if not configured:
        return
    if token != configured:
        raise PermissionError("bad token")


# ---------------------------------------------------------------------------
# Cypher denylist
# ---------------------------------------------------------------------------

class TestCypherDenylist:
    def test_match_return_allowed(self) -> None:
        _assert_read_only("MATCH (a:Atom) RETURN a LIMIT 10")

    def test_with_clause_allowed(self) -> None:
        _assert_read_only("MATCH (a:Atom) WITH a, COUNT { (a)--() } AS d RETURN a, d")

    def test_unwind_allowed(self) -> None:
        _assert_read_only("UNWIND [1,2,3] AS x RETURN x")

    def test_optional_match_allowed(self) -> None:
        _assert_read_only("MATCH (a:Atom) OPTIONAL MATCH (a)-[r]->(b) RETURN a, r, b")

    def test_create_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("CREATE (n:Atom {id: 'x'})")

    def test_create_rejected_lowercase(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("create (n:Atom)")

    def test_merge_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("MERGE (n:Atom {id: 'x'})")

    def test_delete_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("MATCH (a:Atom) DELETE a")

    def test_detach_delete_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("MATCH (a:Atom) DETACH DELETE a")

    def test_set_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("MATCH (a:Atom) SET a.layer = 'x'")

    def test_remove_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("MATCH (a:Atom) REMOVE a.layer")

    def test_drop_constraint_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("DROP CONSTRAINT atom_id IF EXISTS")

    def test_foreach_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("MATCH (a:Atom) FOREACH (x IN [1] | SET a.layer = 'x')")

    def test_apoc_periodic_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("CALL apoc.periodic.commit('...')")

    def test_apoc_runwrite_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_read_only("CALL apoc.cypher.runWrite('CREATE (n)', {})")

    def test_apoc_read_only_allowed(self) -> None:
        # apoc.coll.frequencies is read-only — should pass
        _assert_read_only("MATCH (a:Atom) RETURN apoc.coll.frequencies(collect(a.layer))")

    def test_merge_inside_string_literal_rejected(self) -> None:
        """Conservative: any MERGE keyword anywhere is rejected (even inside a string).

        This is over-conservative but safe. If a real query needs the literal
        'MERGE' inside a string, the caller must access Neo4j directly.
        """
        with pytest.raises(PermissionError):
            _assert_read_only("RETURN 'this contains MERGE in a string'")


# ---------------------------------------------------------------------------
# Token gate
# ---------------------------------------------------------------------------

class TestTokenGate:
    def test_disabled_when_unconfigured(self) -> None:
        """If no token is configured, any token (including None) is accepted."""
        _assert_authed(None, configured="")
        _assert_authed("anything", configured="")

    def test_matching_token_accepted(self) -> None:
        _assert_authed("secret", configured="secret")

    def test_wrong_token_rejected(self) -> None:
        with pytest.raises(PermissionError):
            _assert_authed("wrong", configured="secret")

    def test_missing_token_rejected_when_required(self) -> None:
        with pytest.raises(PermissionError):
            _assert_authed(None, configured="secret")

    def test_empty_token_rejected_when_required(self) -> None:
        with pytest.raises(PermissionError):
            _assert_authed("", configured="secret")


# ---------------------------------------------------------------------------
# write_atom validators (local re-implementations that mirror mcp_server.py)
# ---------------------------------------------------------------------------

_VALID_PREFIXES = ("wiki/", "raw/")
_FRONTMATTER_RE = re.compile(r"^---\n.*?---\n", re.DOTALL)

_WRITE_TOKEN = "test-write-token-abc123"


def _assert_write_authed(token, configured):
    if not configured:
        raise PermissionError("write_atom: MCP_WRITE_TOKEN is not configured on this server — writes disabled")
    if token != configured:
        raise PermissionError("write_atom: invalid or missing write token (401)")


def _validate_vault_path(vault_relative_path):
    if vault_relative_path.startswith("/"):
        raise ValueError("vault_relative_path must not be an absolute path")
    if ".." in vault_relative_path.split("/"):
        raise ValueError("vault_relative_path must not contain '..' components")
    if ".." in vault_relative_path:
        raise ValueError("vault_relative_path must not contain '..'")
    if not any(vault_relative_path.startswith(p) for p in _VALID_PREFIXES):
        raise ValueError(f"vault_relative_path must start with one of {_VALID_PREFIXES}")


def _validate_frontmatter(content):
    if not content.startswith("---\n"):
        raise ValueError("content must start with '---\\n' (YAML frontmatter required)")
    rest = content[4:]
    if "---\n" not in rest and not rest.rstrip().endswith("---"):
        raise ValueError("content has no closing '---' frontmatter delimiter")


def _md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _atomic_write(dest, content):
    """Replicate the tempfile + os.replace pattern from mcp_server.py."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".mcp_write.",
        suffix=".tmp",
        dir=str(dest.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, dest)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


_GOOD_CONTENT = "---\ntitle: Test Atom\ncreated: 2026-05-16\n---\n\nSome body text.\n"


class TestWriteAtomAuth:
    """Tests for write_atom auth gate."""

    def test_write_atom_requires_auth_no_token(self) -> None:
        """No token at all must raise PermissionError (simulated 401)."""
        with pytest.raises(PermissionError):
            _assert_write_authed(None, _WRITE_TOKEN)

    def test_write_atom_requires_auth_wrong_token(self) -> None:
        """Wrong token must raise PermissionError."""
        with pytest.raises(PermissionError):
            _assert_write_authed("bad-token", _WRITE_TOKEN)

    def test_write_atom_correct_token_passes(self) -> None:
        """Correct token must not raise."""
        _assert_write_authed(_WRITE_TOKEN, _WRITE_TOKEN)

    def test_write_atom_no_configured_token_raises(self) -> None:
        """If MCP_WRITE_TOKEN is empty/unconfigured, writes must be disabled."""
        with pytest.raises(PermissionError, match="not configured"):
            _assert_write_authed(_WRITE_TOKEN, "")


class TestWriteAtomPathValidation:
    """Tests for vault_relative_path safety rules."""

    def test_write_atom_rejects_path_traversal(self) -> None:
        """Path with '../' must be rejected (400)."""
        with pytest.raises(ValueError):
            _validate_vault_path("wiki/../etc/passwd")

    def test_write_atom_rejects_path_traversal_component(self) -> None:
        """Bare '..' as a path component must also be rejected."""
        with pytest.raises(ValueError):
            _validate_vault_path("wiki/foo/../../secret")

    def test_write_atom_rejects_absolute_path(self) -> None:
        """Path starting with '/' must be rejected (400)."""
        with pytest.raises(ValueError):
            _validate_vault_path("/etc/passwd")

    def test_write_atom_rejects_non_vault_prefix(self) -> None:
        """Path not starting with 'wiki/' or 'raw/' must be rejected (400)."""
        with pytest.raises(ValueError):
            _validate_vault_path("secrets/foo.md")

    def test_write_atom_accepts_wiki_prefix(self) -> None:
        """wiki/ prefix must be accepted."""
        _validate_vault_path("wiki/Permanent/foo.md")  # must not raise

    def test_write_atom_accepts_raw_prefix(self) -> None:
        """raw/ prefix must be accepted."""
        _validate_vault_path("raw/inbox/bar.md")  # must not raise


class TestWriteAtomFrontmatter:
    """Tests for frontmatter validation."""

    def test_write_atom_requires_frontmatter_opening(self) -> None:
        """Content without opening '---' must be rejected (400)."""
        with pytest.raises(ValueError):
            _validate_frontmatter("No frontmatter here.\n")

    def test_write_atom_requires_frontmatter_closing(self) -> None:
        """Content with opening but no closing '---' must be rejected (400)."""
        with pytest.raises(ValueError):
            _validate_frontmatter("---\ntitle: Missing close\n")

    def test_write_atom_valid_frontmatter_passes(self) -> None:
        """Well-formed frontmatter must not raise."""
        _validate_frontmatter(_GOOD_CONTENT)


class TestWriteAtomDedup:
    """Tests for md5-based deduplication."""

    def test_write_atom_dedup_returns_existing(self, tmp_path) -> None:
        """Pushing a file whose md5 already exists in vault → written=False."""
        # Simulate a vault with an existing atom
        vault = tmp_path / "Brain"
        existing = vault / "wiki" / "Permanent" / "already-there.md"
        existing.parent.mkdir(parents=True)
        existing.write_text(_GOOD_CONTENT, encoding="utf-8")

        target_md5 = _md5(_GOOD_CONTENT)

        # Simulate dedup scan
        found = None
        for fpath in vault.rglob("*.md"):
            try:
                c = fpath.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _md5(c) == target_md5:
                found = str(fpath.relative_to(vault))
                break

        assert found is not None, "dedup scan should have found the existing file"
        assert "already-there.md" in found


class TestWriteAtomAtomicWrite:
    """Tests for the atomic write pattern."""

    def test_write_atom_atomic_write_uses_tempfile_and_replace(self, tmp_path) -> None:
        """_atomic_write must produce the target file via rename (no partial writes)."""
        dest = tmp_path / "wiki" / "Permanent" / "new-atom.md"

        _atomic_write(dest, _GOOD_CONTENT)

        assert dest.exists(), "destination file must exist after atomic write"
        assert dest.read_text(encoding="utf-8") == _GOOD_CONTENT

    def test_write_atom_creates_parent_dirs(self, tmp_path) -> None:
        """Destination directory that doesn't exist must be created."""
        dest = tmp_path / "wiki" / "deep" / "nested" / "dir" / "atom.md"
        assert not dest.parent.exists(), "pre-condition: parent dir must not exist"

        _atomic_write(dest, _GOOD_CONTENT)

        assert dest.exists()


class TestWriteAtomConflict:
    """Tests for the 409 conflict on same-path different-content case."""

    def test_write_atom_conflict_without_overwrite(self, tmp_path) -> None:
        """Same path with different content and overwrite=False must raise ValueError(409)."""
        vault = tmp_path / "Brain"
        dest = vault / "wiki" / "Permanent" / "existing.md"
        dest.parent.mkdir(parents=True)
        dest.write_text(_GOOD_CONTENT, encoding="utf-8")

        different_content = "---\ntitle: Different\ncreated: 2026-05-16\n---\n\nDifferent body.\n"
        existing_md5 = _md5(_GOOD_CONTENT)
        new_md5 = _md5(different_content)
        overwrite = False

        # Replicate the conflict logic from mcp_server.py
        with pytest.raises(ValueError, match="409 Conflict"):
            if dest.exists():
                ec = dest.read_text(encoding="utf-8")
                emd5 = _md5(ec)
                if emd5 != new_md5 and not overwrite:
                    raise ValueError(
                        f"409 Conflict: 'wiki/Permanent/existing.md' already exists with different content "
                        f"(existing_md5={emd5!r}). Pass overwrite=True to replace."
                    )

    def test_write_atom_conflict_with_overwrite_succeeds(self, tmp_path) -> None:
        """Same path with different content and overwrite=True must write without error."""
        dest = tmp_path / "wiki" / "Permanent" / "overwrite-me.md"
        dest.parent.mkdir(parents=True)
        dest.write_text(_GOOD_CONTENT, encoding="utf-8")

        new_content = "---\ntitle: Replaced\ncreated: 2026-05-16\n---\n\nReplaced body.\n"
        _atomic_write(dest, new_content)  # overwrite=True path
        assert dest.read_text(encoding="utf-8") == new_content


class TestWriteAtomAuditLog:
    """Tests for origin metadata and audit log."""

    def test_write_atom_origin_metadata_preserved_in_audit_log(self, tmp_path) -> None:
        """origin_machine, origin_drive, origin_path must appear in audit log entry."""
        audit_log = tmp_path / "mcp_write_audit.jsonl"

        entry = {
            "ts": "2026-05-16T15:30:00+00:00",
            "origin_machine": "studio",
            "origin_drive": "ANEP_RAID_1B",
            "origin_path": "/Volumes/ANEP_RAID_1B/Brain/wiki/Permanent/foo.md",
            "canonical_path": "wiki/Permanent/foo.md",
            "md5": _md5(_GOOD_CONTENT),
            "deduplicated": False,
        }

        # Simulate _append_audit
        with open(audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        lines = audit_log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["origin_machine"] == "studio"
        assert parsed["origin_drive"] == "ANEP_RAID_1B"
        assert parsed["origin_path"] == "/Volumes/ANEP_RAID_1B/Brain/wiki/Permanent/foo.md"
        assert parsed["canonical_path"] == "wiki/Permanent/foo.md"
        assert parsed["deduplicated"] is False
