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

VENV="/Users/erichroepke/Cornelius/resources/local-brain-search/venv/bin/python"
SERVER="/Users/erichroepke/Cornelius/resources/brain-graph/mcp_server.py"

# Load env from .env (BRAIN_NEO4J_PASS, MCP_WRITE_TOKEN)
ENV_FILE="/Users/erichroepke/Cornelius/resources/brain-graph/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

export MCP_TRANSPORT="streamable-http"
export MCP_BIND_HOST="0.0.0.0"
export MCP_BIND_PORT="8788"

cd /Users/erichroepke/Cornelius/resources/brain-graph
exec "$VENV" "$SERVER"
