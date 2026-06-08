from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parent / "mcp_server.py"
SPEC = importlib.util.spec_from_file_location("mcp_server_runtime_test", SCRIPT)
assert SPEC is not None
mcp_server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["mcp_server_runtime_test"] = mcp_server
SPEC.loader.exec_module(mcp_server)


def test_graph_search_uses_metadata_fallback_when_neo4j_is_down(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_read(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise mcp_server.ServiceUnavailable("neo4j down")

    monkeypatch.setattr(mcp_server, "NIKLAS_READ_TOKEN", "")
    monkeypatch.setattr(mcp_server, "_run_read", fail_read)
    monkeypatch.setattr(mcp_server, "_full_text_index_exists", lambda: False)
    monkeypatch.setattr(
        mcp_server,
        "_metadata_keyword_search",
        lambda query, k, seen: [
            {"id": "wiki/Operations/Niklas/example.md", "source": "local-search-metadata"}
        ],
    )

    results = asyncio.run(mcp_server.niklas_graph_search("Niklas", mode="hybrid", k=3))

    assert results[0]["id"] == "wiki/Operations/Niklas/example.md"
    assert results[0]["degraded"] is True
    assert "neo4j unavailable" in results[0]["degraded_reason"]


def test_graph_search_returns_structured_degraded_result_without_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_read(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise mcp_server.ServiceUnavailable("neo4j down")

    monkeypatch.setattr(mcp_server, "NIKLAS_READ_TOKEN", "")
    monkeypatch.setattr(mcp_server, "_run_read", fail_read)
    monkeypatch.setattr(mcp_server, "_full_text_index_exists", lambda: False)
    monkeypatch.setattr(mcp_server, "_metadata_keyword_search", lambda query, k, seen: [])

    results = asyncio.run(mcp_server.niklas_graph_search("no-match", mode="graph", k=3))

    assert results == [
        {
            "source": "degraded",
            "degraded": True,
            "degraded_reason": "neo4j unavailable and local metadata fallback returned no matches",
            "query": "no-match",
        }
    ]


def test_disable_writes_blocks_even_valid_write_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(mcp_server, "NIKLAS_DISABLE_WRITES", True)
    monkeypatch.setattr(mcp_server, "MCP_WRITE_TOKEN", "write-token")

    with pytest.raises(PermissionError, match="disabled"):
        mcp_server._assert_write_authed("write-token")



def test_http_header_auth_allows_tool_calls_without_token_arg(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(mcp_server, "NIKLAS_READ_TOKEN", "read-token")
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")

    mcp_server._assert_authed(None)


def test_stdio_read_auth_still_requires_tool_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(mcp_server, "NIKLAS_READ_TOKEN", "read-token")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")

    with pytest.raises(PermissionError, match="invalid or missing token"):
        mcp_server._assert_authed(None)


def test_static_read_token_verifier_accepts_only_read_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(mcp_server, "NIKLAS_READ_TOKEN", "read-token")

    accepted = asyncio.run(mcp_server._StaticReadTokenVerifier().verify_token("read-token"))
    rejected = asyncio.run(mcp_server._StaticReadTokenVerifier().verify_token("wrong-token"))

    assert accepted is not None
    assert accepted.client_id == "niklas-readonly"
    assert accepted.scopes == [mcp_server.NIKLAS_READ_SCOPE]
    assert rejected is None


def test_niklas_orient_exposes_positioning_packet(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(mcp_server, "NIKLAS_READ_TOKEN", "")
    monkeypatch.setattr(
        mcp_server,
        "niklas_orientation_impl",
        lambda **kwargs: {
            "orientation_version": "niklas-orient-v1",
            "position": {"state": "needs_questions"},
            "questions": [{"id": "goal", "question": "What is the goal?"}],
            "inputs": kwargs,
        },
    )

    result = asyncio.run(
        mcp_server.niklas_orient(
            current_request="Install Niklas",
            cwd="/Users/erichroepke/Desktop/PROJECTS/NIKLAS-BUILDER",
        )
    )

    assert result["orientation_version"] == "niklas-orient-v1"
    assert result["position"]["state"] == "needs_questions"
    assert result["inputs"]["current_request"] == "Install Niklas"
