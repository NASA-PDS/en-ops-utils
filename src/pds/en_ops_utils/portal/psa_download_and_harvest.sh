#!/bin/bash
# psa_download_and_harvest.sh - Weekly PSA label download → Solr doc generation
#
# Assumes harvest/registry environment variables already set.
# Only validates variables specific to pds_sync_api.py.
#
# Required: PSA_SYNC_DATA_DIR, PSA_SYNC_CONDA_ENV, PSA_SYNC_HARVEST_SOLR_CONFIG_FILE
# Optional: PSA_SYNC_EXCLUDES, LEGACY_REGISTRY_EMAIL_RECIPIENTS
# Assumes set: HARVEST_SOLR_HOME, HARVEST_SOLR_CONF_HOME, PDS4_SOLR_DOC_HOME

set -e

# --- Usage ---
usage() {
    cat <<EOF
Usage: $0

Wrapper for PSA label downloads then Harvest to create new Solr docs.

OPTIONS:
    -c, --config FILE   Load environment variables for Download from config file
    -h, --help          Show this help message

EOF
    exit 0
}

# --- Parse Arguments ---
while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--config)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: -c/--config requires a file path argument" >&2
                exit 1
            fi
            CONFIG_FILE="$2"
            if [[ ! -f "$CONFIG_FILE" ]]; then
                echo "ERROR: Config file not found: $CONFIG_FILE" >&2
                exit 1
            fi
            echo "Loading configuration from: $CONFIG_FILE"
            # shellcheck disable=SC1090
            source "$CONFIG_FILE"
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


# Validate required environment variables
for var in PSA_SYNC_DATA_DIR PSA_SYNC_CONDA_ENV PSA_DOWNLOAD_LOG_DIR PSA_SYNC_HARVEST_SOLR_CONFIG_FILE; do
    if [[ -z "${!var}" ]]; then
        echo "ERROR: $var environment variable is not set" >&2
        exit 1
    fi
done

# Make directory if it doesn't exist
mkdir -p "$PSA_DOWNLOAD_LOG_DIR"
chmod 700 "$PSA_DOWNLOAD_LOG_DIR"

# Acquire exclusive lock using flock (prevents race conditions)
LOCK_FILE="${PSA_DOWNLOAD_LOG_DIR}/psa_download.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Error: Another instance of psa_download_and_harvest is already running."
    echo "Lock file: $LOCK_FILE"
    exit 1
fi
# Lock held via file descriptor 9 until process exits


# Set up logging
PSA_DOWNLOAD_LOG_FILE="$PSA_DOWNLOAD_LOG_DIR/psa_download_$(date +%Y%m%d_%H%M%S).log"
touch "$PSA_DOWNLOAD_LOG_FILE"
chmod 600 "$PSA_DOWNLOAD_LOG_FILE"
exec >> "$PSA_DOWNLOAD_LOG_FILE" 2>&1
echo "=== PSA Download started at $(date -Iseconds) ==="

# Function to send failure notification on exit (only for download phase)
send_failure_notification() {
    local exit_code=$?

    # Only send if we failed (non-zero exit) and email is configured
    if [[ $exit_code -ne 0 ]] && [[ -n "$LEGACY_REGISTRY_EMAIL_RECIPIENTS" ]] && command -v mail >/dev/null 2>&1; then
        HOSTNAME_LABEL="${HOSTNAME_LABEL:-$(hostname)}"
        SUBJECT="[PSA Download] FAILED on ${HOSTNAME_LABEL} (Exit Code: $exit_code)"
        BODY="PSA label download FAILED.

Exit Code: $exit_code
Data Directory: ${PSA_SYNC_DATA_DIR:-not set}
Excludes: ${PSA_SYNC_EXCLUDES:-none}
Timestamp: $(date '+%Y-%m-%d %H:%M:%S')
Host: ${HOSTNAME_LABEL}

Please check logs for details."
        echo "$BODY" | mail -s "$SUBJECT" "$LEGACY_REGISTRY_EMAIL_RECIPIENTS"
    fi

    return $exit_code
}

# Function to clean up lock file on exit (flock auto-releases when process exits)
cleanup_download() {
    rm -f "$LOCK_FILE"
    # Lock automatically released when fd 9 closes on exit
}
#Combined exit handler for download phase
download_exit_handler() {
    send_failure_notification
    cleanup_download
}

# Set trap to catch failures during download phase
trap download_exit_handler EXIT

# Activate conda and run download
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting PSA sync"
if [[ -n "$CONDA_HOME" ]]; then
    conda_sh_path="$CONDA_HOME/etc/profile.d/conda.sh"
else
    conda_sh_path="$(conda info --base)/etc/profile.d/conda.sh"
fi
. "$conda_sh_path"
conda activate "$PSA_SYNC_CONDA_ENV"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running pds-sync-api"
if [[ -n "$PSA_SYNC_EXCLUDES" ]]; then
    pds-sync-api -p "$PSA_SYNC_DATA_DIR" -e "$PSA_SYNC_EXCLUDES"
else
    pds-sync-api -p "$PSA_SYNC_DATA_DIR"
fi

# Download succeeded - send success notification manually
if [[ -n "$LEGACY_REGISTRY_EMAIL_RECIPIENTS" ]] && command -v mail >/dev/null 2>&1; then
    HOSTNAME_LABEL="${HOSTNAME_LABEL:-$(hostname)}"
    SUBJECT="[PSA Download] Success on ${HOSTNAME_LABEL}"
    BODY="PSA label download completed successfully.

Downloaded to: ${PSA_SYNC_DATA_DIR}
Timestamp: $(date '+%Y-%m-%d %H:%M:%S')
Host: ${HOSTNAME_LABEL}

Note: Harvest email will follow separately."
    echo "$BODY" | mail -s "$SUBJECT" "$LEGACY_REGISTRY_EMAIL_RECIPIENTS"
fi

# Disable trap with download failure notification since it was successful
trap - EXIT
cleanup_download

# Run harvest (assumes env vars set)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running harvest-solr"
"$HARVEST_SOLR_HOME/bin/harvest-solr" \
    -c "$HARVEST_SOLR_CONF_HOME/$PSA_SYNC_HARVEST_SOLR_CONFIG_FILE" \
    -o "$PDS4_SOLR_DOC_HOME"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Completed successfully"
