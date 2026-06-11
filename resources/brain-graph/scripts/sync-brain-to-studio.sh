#!/usr/bin/env bash
# sync-brain-to-studio.sh — one-way rsync of laptop's canonical Brain to Studio.
#
# Studio's Obsidian opens ~/Desktop/Brain-replica/ as a read-only-by-convention vault.
# DO NOT modify Brain on Studio — changes won't sync back. Use MCP write endpoint
# (Phase 7) or edit on laptop.
#
# Cron schedule: 4am MT daily via launchd (com.niklas.sync-to-studio.plist).
# Manual run: ./sync-brain-to-studio.sh

set -euo pipefail

LOG_FILE="/tmp/sync-brain-to-studio.log"
SOURCE="/Users/erichroepke/Desktop/Niklas/Brain/"
DEST="studio:~/Desktop/Brain-replica/"

# Pre-flight: ensure Studio reachable on LAN
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes studio "echo ok" >/dev/null 2>&1; then
    echo "[$(date -Iseconds)] ERROR: Studio unreachable via ssh. Skip sync." | tee -a "$LOG_FILE"
    exit 1
fi

# Pre-flight: ensure Studio Desktop has at least 1GB free (Brain is ~200MB but need headroom)
FREE_GB=$(ssh studio "df -k ~/Desktop | tail -1 | awk '{print int(\$4/1024/1024)}'")
if [ "$FREE_GB" -lt 1 ]; then
    echo "[$(date -Iseconds)] ERROR: Studio Desktop has <1GB free ($FREE_GB GB). Skip sync to avoid filling disk." | tee -a "$LOG_FILE"
    exit 1
fi

echo "[$(date -Iseconds)] Starting Brain rsync to Studio. Free space: ${FREE_GB}GB" | tee -a "$LOG_FILE"

# rsync: archive mode, compress, delete extras on dest, exclude .git
# macOS ships openrsync 2.6.9 — strip 3.x-only flags (--info=, --partial-dir).
# --stats for summary works on 2.x.
rsync -az --delete --stats \
    --exclude ".git" \
    --exclude ".DS_Store" \
    "$SOURCE" "$DEST" 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "[$(date -Iseconds)] Sync OK." | tee -a "$LOG_FILE"
else
    echo "[$(date -Iseconds)] rsync exited $EXIT_CODE" | tee -a "$LOG_FILE"
    exit "$EXIT_CODE"
fi

# Verify atom count parity (best-effort)
# -L: Brain is a symlink to 01-Brain; without it find returns 0
LOCAL_COUNT=$(find -L /Users/erichroepke/Desktop/Niklas/Brain -type f -name "*.md" -not -path "*/.git/*" | wc -l | tr -d ' ')
REMOTE_COUNT=$(ssh studio "find ~/Desktop/Brain-replica -type f -name '*.md' -not -path '*/.git/*' 2>/dev/null | wc -l" | tr -d ' ')
echo "[$(date -Iseconds)] Atom parity: laptop=$LOCAL_COUNT studio=$REMOTE_COUNT" | tee -a "$LOG_FILE"

if [ "$LOCAL_COUNT" != "$REMOTE_COUNT" ]; then
    echo "[$(date -Iseconds)] WARN: counts differ (likely .gitignored files; manual investigation if persistent)" | tee -a "$LOG_FILE"
fi
