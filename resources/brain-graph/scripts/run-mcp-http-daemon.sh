#!/usr/bin/env bash
# run-mcp-http-daemon.sh — long-running ZEUS BRAIN MCP server, HTTP transport.
#
# Started by launchd (com.zeus-brain.mcp-daemon.plist) at machine boot.
# Bound to 0.0.0.0:8788 so Studio + future peers can reach it via LAN/Tailscale.
#
# To test manually:
#   ./run-mcp-http-daemon.sh
# Logs at /tmp/zeus-brain-mcp-daemon.{out,err}.log

set -euo pipefail

PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
SERVER="/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/mcp_server.py"

# Load env from .env (BRAIN_NEO4J_PASS, MCP_WRITE_TOKEN)
ENV_FILE="/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# The copied .env stores Neo4j creds with a BRAIN_ prefix to avoid Neo4j's
# env-to-conf translation gotcha inside docker-compose. The MCP server expects
# the plain runtime names, so map them here if they are absent.
export NEO4J_USER="${NEO4J_USER:-${BRAIN_NEO4J_USER:-neo4j}}"
export NEO4J_PASS="${NEO4J_PASS:-${BRAIN_NEO4J_PASS:-}}"

export MCP_TRANSPORT="streamable-http"
export MCP_BIND_HOST="0.0.0.0"
export MCP_BIND_PORT="8788"
export VAULT_ROOT="${VAULT_ROOT:-/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain}"
export LBS_METADATA="${LBS_METADATA:-/Users/erichroepke/Desktop/Cornelius/resources/local-brain-search/data/brain_metadata.pkl}"

cd /Users/erichroepke/Desktop/Cornelius/resources/brain-graph
exec "$PYTHON" "$SERVER"
