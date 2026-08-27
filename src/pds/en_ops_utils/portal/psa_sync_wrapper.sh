#!/bin/bash
#
# psa_sync_wrapper.sh - Automated PSA label ingestion pipeline
#
# Description:
#   Orchestrates three-step process to sync PSA (Planetary Science Archive) labels:
#   1. Download labels from PDS Search API
#   2. Generate Solr documents with Harvest
#   3. Load documents into Registry
#
# Usage:
#   ./psa_sync_wrapper.sh [OPTIONS] [STEPS]
#   Run with -h for detailed help
#
# Author: NASA PDS Engineering Node
# Repository: https://github.com/NASA-PDS/en-ops-utils

# Require bash 4.0+ (associative arrays)
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "ERROR: Bash 4.0 or higher required (current: $BASH_VERSION)" >&2
    echo "macOS users: install bash via Homebrew (brew install bash)" >&2
    exit 1
fi

# Strict error handling: exit on error, fail on pipe errors
# Note: -u (nounset) omitted due to associative array compatibility
set -eo pipefail

# --- Constants ---
readonly STEP_DOWNLOAD=1
readonly STEP_HARVEST=2
readonly STEP_LOAD=3

# Harvest log parsing constants (brittle - tied to Harvest 3.x output format)
readonly HARVEST_SUMMARY_LINES=22        # Lines from "Summary:" to "End of Log"
readonly HARVEST_LOG_TAIL_LINES=100      # Last N lines to search for summary block
readonly HARVEST_LOG_ERROR_LINES=1000    # Lines to scan backwards for errors
readonly HARVEST_LOG_ERROR_DISPLAY=20    # Max errors to display in email

# Command output caches (populated on first use)
CONDA_ENV_LIST_CACHE=""

# --- Helper Functions ---
validate_directory() {
# Validate directory exists ($1=var_name, $2=path)
    local var_name=$1
    local dir_path=$2

    if [[ ! -d "$dir_path" ]]; then
        echo "ERROR: Directory does not exist: $var_name=$dir_path" >&2
        return 1
    fi
    return 0
}

validate_executable() {
# Validate executable exists and is executable ($1=description, $2=path)
    local description=$1
    local exec_path=$2

    if [[ ! -x "$exec_path" ]]; then
        echo "ERROR: $description not found or not executable" >&2
        echo "Expected: $exec_path" >&2
        return 1
    fi
    return 0
}

validate_file() {
# Validate file exists ($1=description, $2=path)
    local description=$1
    local file_path=$2

    if [[ ! -f "$file_path" ]]; then
        echo "ERROR: $description not found" >&2
        echo "Expected: $file_path" >&2
        return 1
    fi
    return 0
}

validate_command() {
# Validate command available in PATH ($1=cmd_name, $2=hint)
    local cmd_name=$1
    local hint=$2

    if ! command -v "$cmd_name" &> /dev/null; then
        echo "ERROR: $cmd_name required but not found in PATH" >&2
        [ -n "$hint" ] && echo "$hint" >&2
        return 1
    fi
    return 0
}

parse_harvest_summary() {
# Parse harvest summary from log file ($1=log_path)
# Returns: "LABELS_REGISTERED DOCS_CREATED" (space-separated)
# Note: Parsing is brittle, tied to Harvest output format
    local log_file=$1

    [[ ! -f "$log_file" ]] && echo "0 0" && return 0

    read -r labels_registered docs_created < <(awk '
        /Product Labels:/{flag1=1; next}
        flag1 && /Successfully registered/{labels=$1; flag1=0}
        /Registry Search Solr Documents:/{flag2=1; next}
        flag2 && /Successfully created/{docs=$1; flag2=0}
        END {print (labels ? labels : 0), (docs ? docs : 0)}
    ' "$log_file")

    echo "${labels_registered:-0} ${docs_created:-0}"
}

step_is_enabled() {
# Check if step is enabled ($1=step_number)
    local step=$1
    [[ ${STEPS_TO_RUN[$step]:-0} -eq 1 ]]
}

validate_step_1_resources() {
# Validate step 1 resources: directories, pds_sync_api.py, python/conda
    local validation_failed=false

    # Validate directories using helper
    validate_directory "EN_OPS_UTILS_HOME" "$EN_OPS_UTILS_HOME" || validation_failed=true
    validate_directory "PSA_SYNC_DATA_DIR" "$PSA_SYNC_DATA_DIR" || validation_failed=true

    # Validate Python script exists using helper
    local pds_sync_script="$EN_OPS_UTILS_HOME/src/pds/en_ops_utils/portal/pds_sync_api.py"
    validate_file "pds_sync_api.py" "$pds_sync_script" || validation_failed=true

    # Validate Python/conda availability
    if [ -n "$CONDA_ENV" ]; then
        validate_command "conda" "conda required for CONDA_ENV=$CONDA_ENV" || validation_failed=true

        if [ "$validation_failed" = "false" ]; then
            # Cache conda env list for performance (only call once)
            if [ -z "$CONDA_ENV_LIST_CACHE" ]; then
                CONDA_ENV_LIST_CACHE=$(conda env list 2>/dev/null)
            fi

            if ! echo "$CONDA_ENV_LIST_CACHE" | grep -q "^${CONDA_ENV} "; then
                echo "ERROR: Conda environment '$CONDA_ENV' not found" >&2
                echo "Available environments: $(echo "$CONDA_ENV_LIST_CACHE" | grep -v '^#' | awk '{print $1}' | tr '\n' ' ')" >&2
                validation_failed=true
            else
                # Check if conda.sh can be sourced
                local conda_sh_path=$(_find_conda_sh)
                if [ -z "$conda_sh_path" ]; then
                    echo "ERROR: conda.sh not found for sourcing conda environment" >&2
                    echo "Set CONDA_HOME or ensure conda.sh exists in standard locations" >&2
                    validation_failed=true
                fi
            fi
        fi
    else
        # No conda, validate system Python
        validate_command "python" "" || validation_failed=true
    fi

    [ "$validation_failed" = "true" ] && return 1
    return 0
}

validate_step_2_resources() {
# Validate step 2 resources: directories, harvest-solr, config, java
    local validation_failed=false

    # Validate directories using helper
    validate_directory "HARVEST_SOLR_CONF_HOME" "$HARVEST_SOLR_CONF_HOME" || validation_failed=true
    validate_directory "PDS4_SOLR_DOC_HOME" "$PDS4_SOLR_DOC_HOME" || validation_failed=true

    # Validate harvest-solr executable using helper
    validate_executable "harvest-solr" "$HARVEST_SOLR_HOME/bin/harvest-solr" || validation_failed=true

    # Validate harvest config file using helper
    local harvest_config="$HARVEST_SOLR_CONF_HOME/$HARVEST_CONFIG_FILE"
    validate_file "Harvest config ($HARVEST_CONFIG_FILE)" "$harvest_config" || validation_failed=true

    # Validate Java availability
    if [ -n "$JAVA_HOME" ]; then
        # User specified JAVA_HOME, validate it points to valid JDK
        validate_executable "Java (JAVA_HOME/bin/java)" "$JAVA_HOME/bin/java" || validation_failed=true
    else
        # No JAVA_HOME, validate system java
        validate_command "java" "Set JAVA_HOME or ensure java is in your PATH" || validation_failed=true
    fi

    [ "$validation_failed" = "true" ] && return 1
    return 0
}

validate_step_3_resources() {
# Validate step 3 resources: PDS4_SOLR_DOC_HOME, registry-mgr-solr
    local validation_failed=false

    # Validate directory using helper
    validate_directory "PDS4_SOLR_DOC_HOME" "$PDS4_SOLR_DOC_HOME" || validation_failed=true

    # Validate registry-mgr-solr executable using helper
    validate_executable "registry-mgr-solr" "$REGISTRY_MGR_SOLR_HOME/bin/registry-mgr-solr" || validation_failed=true

    [ "$validation_failed" = "true" ] && return 1
    return 0
}

validate_email_config() {
# Validate email config: EMAIL_RECIPIENTS format, mail command availability
    local validation_failed=false

    # Basic email format check
    if [[ ! "$EMAIL_RECIPIENTS" =~ @ ]] || [[ ! "$EMAIL_RECIPIENTS" =~ \. ]]; then
        echo "ERROR: EMAIL_RECIPIENTS may be invalid: $EMAIL_RECIPIENTS" >&2
        echo "Expected format: email@domain.com or email1@domain.com,email2@domain.com" >&2
        validation_failed=true
    fi

    # Check if mail command is available (warning only - not fatal)
    if ! command -v mail &> /dev/null; then
        echo "ERROR: mail command not found - email notifications will be skipped" >&2
        echo "Install mailutils or mailx if email notifications are needed" >&2
        validation_failed=true
    fi

    [ "$validation_failed" = "true" ] && return 1
    return 0
}

_find_conda_sh() {
# Find conda.sh path: $CONDA_HOME, standard paths, or derive from conda command
    local conda_sh_path=""

    # Priority 1: Explicit CONDA_HOME
    if [ -n "$CONDA_HOME" ] && [ -f "$CONDA_HOME/etc/profile.d/conda.sh" ]; then
        conda_sh_path="$CONDA_HOME/etc/profile.d/conda.sh"
    # Priority 2: Common installation paths
    elif [ -f "$HOME/.conda/etc/profile.d/conda.sh" ]; then
        conda_sh_path="$HOME/.conda/etc/profile.d/conda.sh"
    elif [ -f "/opt/conda/etc/profile.d/conda.sh" ]; then
        conda_sh_path="/opt/conda/etc/profile.d/conda.sh"
    # Priority 3: Derive from conda command location
    elif command -v conda &> /dev/null; then
        local conda_bin=$(command -v conda)
        local conda_base=$(dirname "$(dirname "$conda_bin")")
        if [ -f "$conda_base/etc/profile.d/conda.sh" ]; then
            conda_sh_path="$conda_base/etc/profile.d/conda.sh"
        fi
    fi

    echo "$conda_sh_path"
}

# --- Usage ---
usage() {
    cat <<EOF
Usage: $0 [OPTIONS] [STEPS]

Wrapper script to sync PSA labels through download, harvest, and registry load.

STEPS (optional, defaults to all three):
    --download-labels   Download PSA Labels
    --create-docs       Run Harvest (generate Solr docs)
    --load              Load Solr docs into Registry

    If no steps are specified, all three steps will run.

    Examples:
        $0                          # Run all three steps (default)
        $0 --download-labels        # Run only download step
        $0 --create-docs --load     # Run harvest and load (in order)
        $0 --load --download-labels # Run download then load (auto-sorted)
        $0 -c my.env                # Load config from file, then run all steps
        $0 -c my.env --create-docs  # Load config from file, run harvest only

OPTIONS:
    -c, --config FILE   Load environment variables from config file
    -n, --no-email      Suppress email notification (default: email always sent)
    -h, --help          Show this help message

REQUIRED ENVIRONMENT VARIABLES:
    LOG_DIR                    Directory for log files
    PSA_SYNC_DATA_DIR          Directory for PSA label data
    EN_OPS_UTILS_HOME          Path to en-ops-utils repository
    HARVEST_SOLR_HOME          Path to harvest-solr installation
    HARVEST_SOLR_CONF_HOME     Path to harvest config directory
    PDS4_SOLR_DOC_HOME         Path for Solr document output
    REGISTRY_MGR_SOLR_HOME     Path to registry-manager-solr installation
    EMAIL_RECIPIENTS           Email addresses for notifications

OPTIONAL ENVIRONMENT VARIABLES:
    HOSTNAME_LABEL             Hostname label for email subject (default: hostname)
    CONDA_ENV                  Conda environment name (default: use system python)
    CONDA_HOME                 Conda installation path (default: auto-detect)
    JAVA_HOME                  Java installation path (default: use system java)
    HARVEST_CONFIG_FILE        Harvest policy file (default: harvest-policy-ipda.xml)
    PSA_SYNC_EXCLUDES          Exclusion pattern for pds-sync-api (default: nasa/pds)
    SUCCESS_MARKER_FILE        Path to write success timestamp (for coordination)

Default behavior:
    - All 3 steps run if none specified
    - Email notification is always sent (use -n to suppress)

EOF
    exit 1
}

# --- Parse Arguments (single pass) ---
# Use associative arrays for O(1) lookups
declare -A STEPS_TO_RUN
declare -A STEP_NAME_MAP=(
    [$STEP_DOWNLOAD]="download-labels"
    [$STEP_HARVEST]="create-docs"
    [$STEP_LOAD]="load"
)

NO_EMAIL=false

# Single-pass argument parsing with inline config loading
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
        -n|--no-email)
            NO_EMAIL=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        --download-labels)
            STEPS_TO_RUN[$STEP_DOWNLOAD]=1
            shift
            ;;
        --create-docs)
            STEPS_TO_RUN[$STEP_HARVEST]=1
            shift
            ;;
        --load)
            STEPS_TO_RUN[$STEP_LOAD]=1
            shift
            ;;
        *)
            echo "ERROR: Unknown argument '$1'" >&2
            usage
            ;;
    esac
done

# If no steps specified, default to all three
if [ ${#STEPS_TO_RUN[@]} -eq 0 ]; then
    STEPS_TO_RUN[$STEP_DOWNLOAD]=1
    STEPS_TO_RUN[$STEP_HARVEST]=1
    STEPS_TO_RUN[$STEP_LOAD]=1
fi

# Build ordered list of step names for display (sorted by step number)
STEP_NAMES=()
for step_num in $(printf '%s\n' "${!STEPS_TO_RUN[@]}" | sort -n); do
    STEP_NAMES+=("${STEP_NAME_MAP[$step_num]}")
done

# Determine if email should be sent (keep it simple)
if [ "$NO_EMAIL" = true ]; then
    SEND_EMAIL=false
else
    SEND_EMAIL=true
fi

# --- Validate Required Environment Variables (step-conditional) ---
# Use associative array to track required variables (avoids duplicates)
declare -A REQUIRED_VARS
REQUIRED_VARS["LOG_DIR"]=1  # Always needed

if step_is_enabled "$STEP_DOWNLOAD"; then
    REQUIRED_VARS["EN_OPS_UTILS_HOME"]=1
    REQUIRED_VARS["PSA_SYNC_DATA_DIR"]=1
fi

if step_is_enabled "$STEP_HARVEST"; then
    REQUIRED_VARS["HARVEST_SOLR_HOME"]=1
    REQUIRED_VARS["HARVEST_SOLR_CONF_HOME"]=1
    REQUIRED_VARS["PDS4_SOLR_DOC_HOME"]=1
fi

if step_is_enabled "$STEP_LOAD"; then
    REQUIRED_VARS["REGISTRY_MGR_SOLR_HOME"]=1
    REQUIRED_VARS["PDS4_SOLR_DOC_HOME"]=1  # No duplicate check needed with assoc array
fi

if [ "$SEND_EMAIL" = true ]; then
    REQUIRED_VARS["EMAIL_RECIPIENTS"]=1
fi

# Check all required variables for enabled steps
MISSING_VARS=()
for var in "${!REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "ERROR: Missing required environment variables for selected steps:" >&2
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var" >&2
    done
    echo "" >&2
    echo "Run '$0 --help' for more information." >&2
    exit 1
fi       


# Export required variables so they're available to child processes
export LOG_DIR
export PSA_SYNC_DATA_DIR
export EN_OPS_UTILS_HOME
export HARVEST_SOLR_HOME
export HARVEST_SOLR_CONF_HOME
export PDS4_SOLR_DOC_HOME
export REGISTRY_MGR_SOLR_HOME
export EMAIL_RECIPIENTS

# Optional environment variables (set defaults for set -u compatibility)
HOSTNAME_LABEL="${HOSTNAME_LABEL:-$(hostname)}"
CONDA_ENV="${CONDA_ENV:-}"
CONDA_HOME="${CONDA_HOME:-}"
JAVA_HOME="${JAVA_HOME:-}"
HARVEST_CONFIG_FILE="${HARVEST_CONFIG_FILE:-harvest-policy-ipda.xml}"
PSA_SYNC_EXCLUDES="${PSA_SYNC_EXCLUDES:-nasa/pds}"
SUCCESS_MARKER_FILE="${SUCCESS_MARKER_FILE:-}"

# --- Setup Logging ---
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"  # Only owner can access log directory

# Timestamp is set once for log grouping/naming - individual messages use $(date) for real-time stamps
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/psa_sync_$TIMESTAMP.log"

# Create log file with restrictive permissions
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"  # Only owner can read/write

# Redirect stdout & stderr to the log file
exec > >(tee -a "$LOG_FILE") 2>&1

# --- Validate All Resources Before Execution ---
# Validate only the steps that will run
if step_is_enabled "$STEP_DOWNLOAD"; then
    if ! validate_step_1_resources; then
        echo "Validation failed for step 1 (download-labels)" >&2
        exit 1
    fi
fi

if step_is_enabled "$STEP_HARVEST"; then
    if ! validate_step_2_resources; then
        echo "Validation failed for step 2 (create-docs)" >&2
        exit 1
    fi
fi

if step_is_enabled "$STEP_LOAD"; then
    if ! validate_step_3_resources; then
        echo "Validation failed for step 3 (load)" >&2
        exit 1
    fi
fi

# Validate email config
if [ "$SEND_EMAIL" = true ]; then
    if ! validate_email_config; then
        echo "Validation failed for email notification. If non-critical, use `-n, --no-email` to disable this."
        exit 1
    fi
fi

echo "✓ Configuration validated for steps: ${STEP_NAMES[*]}"

send_notification() {
# Send email with job status, harvest summary, and errors (called via EXIT trap)
    local exit_code=$?
    local status_subject="[PSA Label Sync] Ingestion Succeeded on ${HOSTNAME_LABEL} (Steps: ${STEP_NAMES[*]})"

    if [ $exit_code -ne 0 ]; then
        status_subject="[PSA Label Sync] FAILED on ${HOSTNAME_LABEL} (Exit Code: $exit_code, Steps: ${STEP_NAMES[*]})"
    fi

    # Build email body
    local email_body="PSA Label Sync Completed.

Hostname: ${HOSTNAME_LABEL}
Steps Executed: ${STEP_NAMES[*]}
Job Status: $( [ $exit_code -eq 0 ] && echo "SUCCESS" || echo "FAILED (Exit Code: $exit_code)" )
Log File: $LOG_FILE
"

    # Add harvest summary only if step 2 was run
    if step_is_enabled "$STEP_HARVEST"; then
        # Consolidated log parsing: single tail operation extracts both summary and errors
        # This reads the last N lines once and processes them in memory
        local log_tail=$(tail -n "$HARVEST_LOG_ERROR_LINES" "$LOG_FILE")

        # Extract harvest summary block
        local summary_text=$(echo "$log_tail" | tail -n "$HARVEST_LOG_TAIL_LINES" | \
                             grep -A "$HARVEST_SUMMARY_LINES" "Summary :" || \
                             echo "No summary block generated.")

        # Extract errors, filtering out known XML parsing warnings
        # Note: "Content is not allowed in prolog" is emitted by Harvest for malformed XML but processing continues
        local errors_text=$(echo "$log_tail" | \
                            grep ERROR | \
                            grep -v "line 1: Content is not allowed in prolog" | \
                            head -n "$HARVEST_LOG_ERROR_DISPLAY" || \
                            echo "No non-ignorable errors found.")

        email_body="$email_body
--- HARVEST SUMMARY ---
$summary_text

--- RELEVANT LOG ERRORS (First $HARVEST_LOG_ERROR_DISPLAY) ---
$errors_text
"
    fi

    # Send summary email (non-fatal - don't let mail failure change script exit code)
    if command -v mail &> /dev/null; then
        if mail -s "$status_subject" "$EMAIL_RECIPIENTS" <<EOF
$email_body
EOF
        then
            echo "Email notification sent successfully" >&2
        else
            echo "WARNING: Failed to send email notification (mail command failed)" >&2
        fi
    else
        echo "WARNING: mail command not found, skipping email notification" >&2
    fi

    # Preserve original exit code
    return $exit_code
}

# Register the trap only if email should be sent
if [ "$SEND_EMAIL" = true ]; then
    trap send_notification EXIT
fi

start_log() {
# Log configuration summary
    echo "=============================================="
    echo "=== [$(date)] Configuration Summary ==="
    echo "Log file:           $LOG_FILE"
    echo "Hostname:           $HOSTNAME_LABEL"
    echo "Running ${#STEP_NAMES[@]} steps: ${STEP_NAMES[*]}"
    if [ "$SEND_EMAIL" = true ]; then
        echo "Email notification: Enabled"
        echo "Email recipients:   $EMAIL_RECIPIENTS"
    else
        echo "Email notification: Disabled"
    fi
    echo "==========================================="
}

step_1_download() {
# Step 1: Download PSA labels using pds-sync-api
    echo "=== [$(date)] Step 1: Downloading PSA Labels ==="

    # Activate conda environment if specified (already validated)
    if [ -n "$CONDA_ENV" ]; then
        local conda_sh_path=$(_find_conda_sh)
        # Path is guaranteed to exist by validation, but check defensively
        if [ -n "$conda_sh_path" ]; then
            echo "Sourcing conda from: $conda_sh_path"
            source "$conda_sh_path"
            echo "Activating conda environment: $CONDA_ENV"
            conda activate "$CONDA_ENV"
        else
            echo "ERROR: conda.sh not found (should have been caught by validation)" >&2
            exit 1
        fi
    fi

    # Log Python details
    echo "Using Python: $(which python)"
    python --version

    # Run pds-sync-api
    cd "$EN_OPS_UTILS_HOME"
    python src/pds/en_ops_utils/portal/pds_sync_api.py -p "$PSA_SYNC_DATA_DIR" -e "$PSA_SYNC_EXCLUDES"
    echo "=== [$(date)] Step 1 completed successfully ==="
}

step_2_harvest() {
# Step 2: Generate Solr documents with harvest-solr, validate output
    echo "=== [$(date)] Step 2: Generating Solr Docs with Harvest ==="

    # Setup JAVA_HOME if specified (otherwise uses system java from PATH)
    if [ -n "$JAVA_HOME" ]; then
        export PATH="$JAVA_HOME/bin:$PATH"
    fi

    # Log Java details for diagnostic tracking (already validated in main validation)
    echo "Using Java: $(which java)"
    java -version

    HARVEST_SOLR_CONFIG="$HARVEST_SOLR_CONF_HOME/$HARVEST_CONFIG_FILE"

    # Set JVM options to allocate 2GB or 8GB of max heap memory
    export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:--Xms2g -Xmx8g}"

    # If JVM OOM (Out of Memory) still triggers at Harvest's teardown, we need to capture
    # the exit code without the script failing immediately (set -e would exit)
    set +e
    "$HARVEST_SOLR_HOME/bin/harvest-solr" -c "$HARVEST_SOLR_CONFIG" -o "$PDS4_SOLR_DOC_HOME"
    local HARVEST_EXIT=$?
    set -e

    # --- Validate Summary Output ---
    # Use helper function to parse harvest metrics
    read -r LABELS_REGISTERED DOCS_CREATED < <(parse_harvest_summary "$LOG_FILE")

    echo "Validation Metrics -> Labels Registered: $LABELS_REGISTERED | Solr Docs Created: $DOCS_CREATED"

    # Verify:
    # 1. At least one label was processed (> 0)
    # 2. Registered labels equal created Solr docs
    if [ "$LABELS_REGISTERED" -gt 0 ] && [ "$LABELS_REGISTERED" -eq "$DOCS_CREATED" ]; then
        echo "=== [$(date)] Step 2 completed successfully ($LABELS_REGISTERED labels = $DOCS_CREATED docs) ==="
    else
        echo "=== [$(date)] ERROR: Harvest validation failed! (Registered: $LABELS_REGISTERED, Created: $DOCS_CREATED) ===" >&2
        exit $(( HARVEST_EXIT != 0 ? HARVEST_EXIT : 1 ))
    fi
}

step_3_load() {
# Step 3: Load Solr documents into registry using registry-mgr-solr
    echo "=== [$(date)] Step 3: Loading Solr Docs into Registry ==="
    "$REGISTRY_MGR_SOLR_HOME/bin/registry-mgr-solr" "$PDS4_SOLR_DOC_HOME/solr-docs"
    echo "=== [$(date)] Step 3 completed successfully ==="
}

# --- Main Execution ---
# Start writing to the log file (always happens)
start_log

# Execute or skip steps in order (1, 2, 3)
if step_is_enabled "$STEP_DOWNLOAD"; then
    step_1_download
else
    echo "=== [$(date)] Step 1: Downloading PSA Labels (USER SKIPPED) ==="
fi

if step_is_enabled "$STEP_HARVEST"; then
    step_2_harvest
else
    echo "=== [$(date)] Step 2: Generating Solr Docs with Harvest (USER SKIPPED) ==="
fi

if step_is_enabled "$STEP_LOAD"; then
    step_3_load
else
    echo "=== [$(date)] Step 3: Loading Solr Docs into Registry (USER SKIPPED) ==="
fi

echo "=== [$(date)] All requested steps completed successfully ==="
