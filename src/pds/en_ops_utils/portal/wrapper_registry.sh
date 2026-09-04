#!/bin/bash
#
# wrapper_registry.sh - Registry loader with multi-machine coordination
#
# Description:
#   Checks for harvest success marker, runs registry-mgr-solr to load docs,
#   creates registry success marker, and coordinates cleanup across multiple machines.
#
# Usage:
#   ./wrapper_registry.sh
#
# Cron setup (both dev and prod machines):
#   0 * * * * cd /path/to/scripts && ./wrapper_registry.sh >> /var/log/registry-cron.log 2>&1
#
# Author: NASA PDS Engineering Node

set -e

# --- Usage ---
usage() {
    cat <<EOF
Usage: $0

Wrapper for registry-mgr-solr to automatically run if Harvest has new Solr docs.

OPTIONS:
    -h, --help          Show this help message

EOF
    exit 0
}

# --- Parse Arguments ---
while [[ $# -gt 0 ]]; do
    case $1 in
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
for var in HOSTNAME_LABEL HARVEST_SOLR_MARKER_FILE LEGACY_REGISTRY_MARKER_DIR REGISTRY_MGR_SOLR_LOG_FILE \
           LEGACY_REGISTRY_EMAIL_RECIPIENTS PDS4_SOLR_DOC_HOME REGISTRY_MGR_SOLR_HOME; do                                                                                                                                        
    if [[ -z "${!var}" ]]; then                                                                                                                                                                                                  
        echo "ERROR: $var environment variable is not set" >&2                                                                                                                                                                   
        exit 1                                                                                                                                                                                                                   
    fi                                                                                                                                                                                                                           
done 

send_notification() {
    # Send email notification ($1=exit_code, $2=log_file)
    local exit_code=$1
    local log_file=$2
    local status_subject="[Registry Mgr Solr] Succeeded on ${HOSTNAME_LABEL}"

    if [ $exit_code -ne 0 ]; then
        status_subject="[Registry Mgr Solr] FAILED on ${HOSTNAME_LABEL} (Exit Code: $exit_code)"
    fi

    local email_body="Registry mgr load completed.

Hostname: ${HOSTNAME_LABEL}
Job Status: $([ $exit_code -eq 0 ] && echo "SUCCESS" || echo "FAILED (Exit Code: $exit_code)")
Timestamp: $(date -Iseconds)
Log File: ${log_file}
"

    # Add last 50 lines of log for context
    if [ -f "$REGISTRY_MGR_SOLR_LOG_FILE" ]; then
        email_body="${email_body}
--- LAST 50 LOG LINES ---
$(tail -n 50 "$REGISTRY_MGR_SOLR_LOG_FILE")
"
    fi

    # Send email (non-fatal)
    if command -v mail > /dev/null 2>&1; then
        if echo "$email_body" | mail -s "$status_subject" "$LEGACY_REGISTRY_EMAIL_RECIPIENTS"; then
            echo "[$(date -Iseconds)] Email notification sent successfully"
        else
            echo "[$(date -Iseconds)] WARNING: Failed to send email notification" >&2
        fi
    else
        echo "[$(date -Iseconds)] WARNING: mail command not found, skipping email" >&2
    fi
}

# --- Main Logic ---
# 1a. Check if harvest marker exists (exit silently if not - no work to do)
if [[ ! -f "$HARVEST_SOLR_MARKER_FILE" ]]; then
    exit 0
else
    # 1b. Check if registry already processed this harvest (exit silently if so - no work to do)
    REGISTRY_MGR_SOLR_MARKER_FILE="${LEGACY_REGISTRY_MARKER_DIR}/.registry_mgr_success_${HOSTNAME_LABEL}"
    if [[ -f "$REGISTRY_MGR_SOLR_MARKER_FILE" ]]; then
        exit 0
    fi
fi

# 2. Set up logging
REGISTRY_MGR_SOLR_LOG_DIR=$(dirname "${REGISTRY_MGR_SOLR_LOG_FILE}")
mkdir -p "${REGISTRY_MGR_SOLR_LOG_DIR}"
chmod 700 "${REGISTRY_MGR_SOLR_LOG_DIR}"
touch "${REGISTRY_MGR_SOLR_LOG_FILE}"
chmod 600 "${REGISTRY_MGR_SOLR_LOG_FILE}"
exec > >(tee -a "${REGISTRY_MGR_SOLR_LOG_FILE}") 2>&1
echo "=== Registry Manager started at $(date -Iseconds) ==="
echo "Harvest marker: $HARVEST_SOLR_MARKER_FILE ($(date -Iseconds -r "$HARVEST_SOLR_MARKER_FILE" 2>/dev/null || echo "timestamp unknown"))"
echo "[$(date -Iseconds)] Starting registry load"

# 3. Run registry-mgr-solr
SOLR_DOCS_DIR="${PDS4_SOLR_DOC_HOME}/solr-docs"
if [ ! -d "$SOLR_DOCS_DIR" ]; then
    echo "[$(date -Iseconds)] ERROR: Solr docs directory not found: $SOLR_DOCS_DIR" >&2
    send_notification 1 "$REGISTRY_MGR_SOLR_LOG_FILE"
    exit 1
fi

echo "[$(date -Iseconds)] Running registry-mgr-solr on $SOLR_DOCS_DIR"
set +e
"${REGISTRY_MGR_SOLR_HOME}/bin/registry-mgr-solr" "$SOLR_DOCS_DIR" >> "$REGISTRY_MGR_SOLR_LOG_FILE" 2>&1
REGISTRY_MGR_SOLR_EXIT=$?
set -e

if [[ $REGISTRY_MGR_SOLR_EXIT -ne 0 ]]; then
    echo "[$(date -Iseconds)] ERROR: registry-mgr-solr failed with exit code $REGISTRY_MGR_SOLR_EXIT" >&2
    send_notification $REGISTRY_MGR_SOLR_EXIT "$REGISTRY_MGR_SOLR_LOG_FILE"
    exit $REGISTRY_MGR_SOLR_EXIT
fi

echo "[$(date -Iseconds)] Registry load completed successfully" 

# 4. Create registry marker
echo "[$(date -Iseconds)] Creating registry success marker: $REGISTRY_MGR_SOLR_MARKER_FILE" 
{
    echo "# Registry Success Marker"
    echo "# This file signals that registry loaded docs successfully on this machine."
    echo "timestamp=$(date +%s)"
    echo "datetime=$(date -Iseconds)"
    echo "hostname=$HOSTNAME_LABEL"
    echo "log_file=$REGISTRY_MGR_SOLR_LOG_FILE"
} > "$REGISTRY_MGR_SOLR_MARKER_FILE"
chmod 600 "$REGISTRY_MGR_SOLR_MARKER_FILE"
echo "[$(date -Iseconds)] ✓ Registry marker created" 

# 5. Send success email
send_notification 0 "$REGISTRY_MGR_SOLR_LOG_FILE"

# 6. Possible cleanup - are both registry markers present?
REGISTRY_MARKER_COUNT=$(ls "${LEGACY_REGISTRY_MARKER_DIR}"/.registry_mgr_success_* 2>/dev/null | wc -l | tr -d ' ')

echo "[$(date -Iseconds)] Checking for cleanup: found $REGISTRY_MARKER_COUNT registry marker(s)" 

if [[ "$REGISTRY_MARKER_COUNT" -eq 2 ]]; then
    echo "[$(date -Iseconds)] All machines complete - cleaning up markers" 

    # Remove harvest marker
    if [[ -f "$HARVEST_SOLR_MARKER_FILE" ]]; then
        rm -f "$HARVEST_SOLR_MARKER_FILE"
        echo "[$(date -Iseconds)] ✓ Removed harvest marker: $HARVEST_SOLR_MARKER_FILE" 
    fi

    # Remove all registry markers
    for marker in "${LEGACY_REGISTRY_MARKER_DIR}"/.registry_mgr_success_*; do
        if [[ -f "$marker" ]]; then
            rm -f "$marker"
            echo "[$(date -Iseconds)] ✓ Removed registry marker: $marker" 
        fi
    done

    echo "[$(date -Iseconds)] ✓ Cleanup complete" 
else
    echo "[$(date -Iseconds)] Waiting for other machine to complete - this marker remains" 
fi

echo "[$(date -Iseconds)] Done" 
exit 0
