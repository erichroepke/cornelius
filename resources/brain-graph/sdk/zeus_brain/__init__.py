"""zeus_brain — Python SDK for the Brain Dependency Graph + Neo4j.

Lightweight client that talks directly to Neo4j (bypassing MCP) for in-process
use by Cornelius skills, scripts, and notebooks. For external project integration,
use the MCP server (mcp_server.py) instead.

Example:
    from zeus_brain import Client

    brain = Client.from_env()
    print(brain.status())
    orphans = brain.orphans(limit=20)
    hubs = brain.hubs(min_degree=10)
    path = brain.path("02-Permanent/foo.md", "02-Permanent/bar.md")
"""
from __future__ import annotations

from .client import Client

__all__ = ["Client"]
__version__ = "0.1.0"
