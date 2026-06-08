#!/usr/bin/env bash
# run-mcp-readonly-http-daemon.sh - read-only Niklas MCP HTTP daemon.
#
# Intended for HTTPS tunnel exposure to cloud clients such as Perplexity.
# It binds only to loopback and disables write tools even if .env contains
# MCP_WRITE_TOKEN.

set -euo pipefail

PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
SERVER="/Users/erichroepke/Desktop/Niklas/03-Runtime/Cornelius/resources/brain-graph/mcp_server.py"
ENV_FILE="/Users/erichroepke/Desktop/Niklas/03-Runtime/Cornelius/resources/brain-graph/.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

if [ -z "${NIKLAS_READ_TOKEN:-}" ]; then
    echo "NIKLAS_READ_TOKEN is required for the read-only HTTP daemon" >&2
    exit 2
fi

export NEO4J_USER="${NEO4J_USER:-${BRAIN_NEO4J_USER:-neo4j}}"
export NEO4J_PASS="${NEO4J_PASS:-${BRAIN_NEO4J_PASS:-}}"

unset MCP_WRITE_TOKEN
export NIKLAS_DISABLE_WRITES="true"
export MCP_TRANSPORT="streamable-http"
export MCP_BIND_HOST="${MCP_BIND_HOST:-127.0.0.1}"
export MCP_BIND_PORT="${MCP_BIND_PORT:-8787}"
export VAULT_ROOT="${VAULT_ROOT:-/Users/erichroepke/Desktop/Niklas/01-Brain}"
export LBS_METADATA="${LBS_METADATA:-/Users/erichroepke/Desktop/Niklas/03-Runtime/Cornelius/resources/local-brain-search/data/brain_metadata.pkl}"

cd /Users/erichroepke/Desktop/Niklas/03-Runtime/Cornelius/resources/brain-graph
exec "$PYTHON" "$SERVER"
