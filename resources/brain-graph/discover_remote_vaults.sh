#!/usr/bin/env bash
# Discover vaults on a remote Tailscale peer + merge into vaults-registry.json.
#
# Prereqs:
#   1. Tailscale running locally + remote peer online (`tailscale status` shows it)
#   2. SSH alias for the remote peer configured (default: `home`)
#   3. jq installed locally (for registry merge)
#
# Usage:
#   ./discover_remote_vaults.sh                  # default: ssh home
#   ./discover_remote_vaults.sh <ssh-alias>      # custom alias
#   ./discover_remote_vaults.sh home --dry-run   # show what would be added, don't write
#
# Output:
#   - Prints discovered remote vaults to stdout
#   - Updates the canonical Brain registry (unless --dry-run)
#   - Adds `host: <alias>` + `tailscale_name: <hostname>` + `reachable_now: true` per vault

set -euo pipefail

SSH_ALIAS="${1:-home}"
DRY_RUN="${2:-}"
REGISTRY="/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/05-Meta/vaults-registry.json"

# Verify Tailscale running + peer reachable
if ! command -v tailscale >/dev/null; then
    echo "ERROR: tailscale CLI not found. Install: brew install tailscale" >&2
    exit 1
fi

if ! tailscale status >/dev/null 2>&1; then
    echo "ERROR: tailscale service not running. Launch Tailscale.app and log in." >&2
    exit 1
fi

# Get the peer's tailnet hostname for the registry
TAILSCALE_NAME=$(tailscale status 2>/dev/null | awk -v a="$SSH_ALIAS" '
    /^[0-9]/ {
        # Each peer line: <ip> <hostname> <login> <os> <state>
        if ($2 ~ a || $3 ~ a) { print $2; exit }
    }
')

if [[ -z "$TAILSCALE_NAME" ]]; then
    echo "WARN: could not resolve Tailscale name for '$SSH_ALIAS' — continuing with SSH alias only" >&2
fi

# Verify SSH reachability (fast — 5s timeout, no host key prompts)
if ! ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
        "$SSH_ALIAS" "echo ok" >/dev/null 2>&1; then
    echo "ERROR: ssh $SSH_ALIAS failed. Configure ~/.ssh/config or pass full host." >&2
    exit 1
fi

echo "Discovering vaults on $SSH_ALIAS (tailnet name: ${TAILSCALE_NAME:-unknown})..." >&2

# Remote discovery — single SSH invocation, find + jq-friendly output
REMOTE_OUTPUT=$(ssh "$SSH_ALIAS" 'bash -s' <<'REMOTE_SCRIPT'
set -e
# Find .obsidian/ vault roots in common locations
ROOTS=(
    "$HOME/Desktop"
    "$HOME/Documents"
    "$HOME/Cornelius/Brain"
    "$HOME"
)
declare -a VAULTS

for root in "${ROOTS[@]}"; do
    [[ -d "$root" ]] || continue
    # find .obsidian dirs (depth-limited to avoid endless walks)
    while IFS= read -r obs_dir; do
        vault_root=$(dirname "$obs_dir")
        VAULTS+=("$vault_root")
    done < <(find "$root" -maxdepth 5 -type d -name ".obsidian" 2>/dev/null)

    # find Cornelius-schema folders (has 02-Permanent or wiki/atoms)
    while IFS= read -r cand; do
        VAULTS+=("$cand")
    done < <(find "$root" -maxdepth 5 -type d \
        \( -name "02-Permanent" -o -name "atoms" \) 2>/dev/null | xargs -I{} dirname {} | sort -u)
done

# Deduplicate
mapfile -t UNIQUE_VAULTS < <(printf '%s\n' "${VAULTS[@]}" | sort -u)

# Emit JSON lines (NDJSON) for each vault
HOST=$(hostname -s)
for v in "${UNIQUE_VAULTS[@]}"; do
    [[ -d "$v" ]] || continue
    md_count=$(find "$v" -type f -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
    size=$(du -sh "$v" 2>/dev/null | cut -f1)
    last_mod=$(stat -f "%Sm" -t "%Y-%m-%dT%H:%M:%SZ" "$v" 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)
    has_obs=$([[ -d "$v/.obsidian" ]] && echo true || echo false)
    has_cornelius=$([[ -d "$v/02-Permanent" || -d "$v/01-Sources" ]] && echo true || echo false)
    has_wiki=$([[ -d "$v/wiki/atoms" || -d "$v/wiki" ]] && echo true || echo false)
    is_git=$([[ -d "$v/.git" ]] && echo true || echo false)

    # Classify
    if [[ "$has_cornelius" == "true" ]]; then type="cornelius"
    elif [[ "$has_obs" == "true" ]]; then type="obsidian"
    elif [[ "$has_wiki" == "true" ]]; then type="misc-markdown"
    elif [[ "$is_git" == "true" ]]; then type="git-repo"
    else type="misc-markdown"
    fi

    printf '{"path":"%s","host":"%s","type":"%s","markdown_count":%s,"total_size":"%s","last_modified":"%s","has_dot_obsidian":%s,"has_cornelius_schema":%s,"is_git_repo":%s}\n' \
        "$v" "$HOST" "$type" "$md_count" "$size" "$last_mod" "$has_obs" "$has_cornelius" "$is_git"
done
REMOTE_SCRIPT
)

REMOTE_COUNT=$(printf '%s\n' "$REMOTE_OUTPUT" | grep -c '"path"' || echo 0)
echo "Found $REMOTE_COUNT vaults on $SSH_ALIAS" >&2

if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "$REMOTE_OUTPUT"
    echo "(dry-run: registry NOT updated)" >&2
    exit 0
fi

# Merge into local registry
if [[ ! -f "$REGISTRY" ]]; then
    echo "ERROR: registry not found at $REGISTRY. Run local discovery first." >&2
    exit 1
fi

if ! command -v jq >/dev/null; then
    echo "WARN: jq not installed; emitting NDJSON to stdout, not merging." >&2
    echo "$REMOTE_OUTPUT"
    exit 0
fi

# Build a jq filter that appends remote vaults + sets registry-wide metadata
TMP_REMOTE=$(mktemp)
printf '%s\n' "$REMOTE_OUTPUT" | jq -s --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg alias "$SSH_ALIAS" --arg tname "${TAILSCALE_NAME:-unknown}" '
    map(. + {
        tailscale_name: $tname,
        reachable_now: true,
        last_seen: $ts,
        ssh_alias: $alias,
        notes: "Discovered via Tailscale ssh \($alias) on \($ts)",
        kind: (if .has_cornelius_schema then "brain" elif .has_dot_obsidian then "project" else "project" end)
    })' > "$TMP_REMOTE"

# Backup current registry
BACKUP="${REGISTRY%.json}.backup-$(date +%Y%m%d-%H%M%S).json"
cp "$REGISTRY" "$BACKUP"

# Merge: append remote entries (filter out duplicates by path)
TMP_OUT=$(mktemp)
jq --slurpfile remote "$TMP_REMOTE" '
    .generated_at = (now | strftime("%Y-%m-%dT%H:%M:%SZ"))
    | .vaults = (.vaults + ($remote | .[0]) | unique_by(.path))
    | .vault_count = (.vaults | length)
' "$REGISTRY" > "$TMP_OUT"

mv "$TMP_OUT" "$REGISTRY"
rm -f "$TMP_REMOTE"

echo "Registry updated: $REGISTRY" >&2
echo "Backup: $BACKUP" >&2
echo "Vault count: $(jq '.vault_count' "$REGISTRY")" >&2
