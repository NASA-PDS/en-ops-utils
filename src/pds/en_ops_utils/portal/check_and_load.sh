#!/bin/bash
#
# check_and_load.sh - Production checker for PSA sync coordination
#
# Description:
#   Checks for success marker from development machine, runs step 3 (load)
#   if marker exists and is fresh, then removes marker.
#
# Use Case:
#   - Development machine: Runs psa_sync_wrapper.sh with SUCCESS_MARKER_FILE set
#   - Production machine: Runs this script via cron to check for completion
#   - Shared filesystem: Both machines can access the marker file
#   - Mirrored structure: Both machines have same directory layout
#
# Usage:
#   ./check_and_load.sh -c /path/to/check_and_load.env
#
# Installation:
#   1. Copy check_and_load.sh and check_and_load.env.example to production
#   2. Customize check_and_load.env for your environment
#   3. Set permissions: chmod 600 check_and_load.env
#   4. Add to production crontab:
#      0 */4 * * * /opt/psa-sync/check_and_load.sh -c /opt/psa-sync/check_and_load.env
#
# Author: NASA PDS Engineering Node

set -eo pipefail

# --- Usage ---
usage() {
    cat <<EOF
Usage: $0 -c CONFIG_FILE

Production checker for PSA sync multi-machine coordination.

OPTIONS:
    -c, --config FILE   Load configuration from file (required)
    -h, --help          Show this help message

EXAMPLE:
    $0 -c /opt/psa-sync/check_and_load.env

EOF
    exit 1
}

# --- Parse Arguments ---
CONFIG_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--config)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: -c/--config requires a file path argument" >&2
                exit 1
            fi
            CONFIG_FILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "ERROR: Unknown argument '$1'" >&2
            usage
            ;;
    esac
done

# Require config file
if [[ -z "$CONFIG_FILE" ]]; then
    echo "ERROR: Config file required. Use -c flag." >&2
    usage
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: Config file not found: $CONFIG_FILE" >&2
    exit 1
fi

# Load configuration
# shellcheck disable=SC1090
source "$CONFIG_FILE"

# --- Validate Required Variables ---
MISSING_VARS=()
for var in MARKER_FILE WRAPPER_SCRIPT WRAPPER_CONFIG; do
    if [[ -z "${!var:-}" ]]; then
        MISSING_VARS+=("$var")
    fi
done

if [[ ${#MISSING_VARS[@]} -gt 0 ]]; then
    echo "ERROR: Missing required variables in config file:" >&2
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var" >&2
    done
    exit 1
fi

# Set defaults for optional variables
MAX_AGE_HOURS="${MAX_AGE_HOURS:-24}"
ERROR_EMAIL="${ERROR_EMAIL:-}"

# --- Main Logic ---

# Exit silently if no marker file exists
if [[ ! -f "$MARKER_FILE" ]]; then
    exit 0
fi

# Check marker age (don't process stale markers)
if [[ "$(uname)" = "Linux" ]]; then
    # Linux
    MARKER_MTIME=$(stat -c %Y "$MARKER_FILE" 2>/dev/null || echo 0)
else
    # macOS/BSD
    MARKER_MTIME=$(stat -f %m "$MARKER_FILE" 2>/dev/null || echo 0)
fi

CURRENT_TIME=$(date +%s)
AGE_SECONDS=$((CURRENT_TIME - MARKER_MTIME))
AGE_HOURS=$((AGE_SECONDS / 3600))

if [[ "$AGE_SECONDS" -gt $((MAX_AGE_HOURS * 3600)) ]]; then
    echo "[$(date -Iseconds)] Marker is stale (${AGE_HOURS}h old), ignoring"
    exit 0
fi

# Log marker info
echo "[$(date -Iseconds)] Found fresh marker (${AGE_HOURS}h old)"
echo "[$(date -Iseconds)] Marker contents:"
cat "$MARKER_FILE" | sed 's/^/  /'

# Run step 3 (load into production registry)
echo "[$(date -Iseconds)] Running step 3 on production..."

if "$WRAPPER_SCRIPT" -c "$WRAPPER_CONFIG" --load -n; then
    echo "[$(date -Iseconds)] ✓ Production load completed successfully"

    # Remove marker after successful load
    rm -f "$MARKER_FILE"
    echo "[$(date -Iseconds)] ✓ Marker removed"

    exit 0
else
    EXIT_CODE=$?
    echo "[$(date -Iseconds)] ✗ Production load FAILED (exit code: $EXIT_CODE)" >&2

    # Optional: Send error notification
    if [[ -n "$ERROR_EMAIL" ]] && command -v mail >/dev/null 2>&1; then
        echo "Production PSA sync load failed. Check logs: $(hostname)" | \
            mail -s "[PSA Sync] Production Load Failed" "$ERROR_EMAIL"
    fi

    # Don't remove marker on failure - allow retry on next cron run
    exit "$EXIT_CODE"
fi
