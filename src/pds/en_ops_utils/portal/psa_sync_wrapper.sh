#!/bin/bash
set -euo pipefail

# --- Constants ---
readonly STEP_DOWNLOAD=1
readonly STEP_HARVEST=2
readonly STEP_LOAD=3

# --- Helper Functions ---
# Check if a step is in the STEPS_TO_RUN array
step_is_enabled() {
    local check_step=$1
    for step in "${STEPS_TO_RUN[@]}"; do
        if [ "$step" = "$check_step" ]; then
            return 0
        fi
    done
    return 1
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
    --dry-run           Validate configuration and show what would run, but don't execute
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

Default behavior:
    - All 3 steps run if none specified
    - Email notification is always sent (use -n to suppress)

EOF
    exit 1
}

# --- Parse Config File (if provided) ---
# Process -c/--config flag first (before environment validation)
TEMP_ARGS=("$@")
for i in "${!TEMP_ARGS[@]}"; do
    if [ "${TEMP_ARGS[$i]}" = "-c" ] || [ "${TEMP_ARGS[$i]}" = "--config" ]; then
        # Get the next argument (config file path)
        NEXT_IDX=$((i + 1))
        if [ $NEXT_IDX -lt ${#TEMP_ARGS[@]} ]; then
            CONFIG_FILE="${TEMP_ARGS[$NEXT_IDX]}"
            if [ ! -f "$CONFIG_FILE" ]; then
                echo "Error: Config file not found: $CONFIG_FILE" >&2
                exit 1
            fi
            echo "Loading configuration from: $CONFIG_FILE"
            # shellcheck disable=SC1090
            source "$CONFIG_FILE"
        else
            echo "Error: -c/--config requires a file path argument" >&2
            exit 1
        fi
        break
    fi
done

# --- Configuration & Setup ---
# Validate required environment variables
REQUIRED_VARS=(
    "LOG_DIR"
    "PSA_SYNC_DATA_DIR"
    "EN_OPS_UTILS_HOME"
    "HARVEST_SOLR_HOME"
    "HARVEST_SOLR_CONF_HOME"
    "PDS4_SOLR_DOC_HOME"
    "REGISTRY_MGR_SOLR_HOME"
    "EMAIL_RECIPIENTS"
)

MISSING_VARS=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "Error: Missing required environment variables:" >&2
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var" >&2
    done
    echo "" >&2
    echo "Run '$0 --help' for more information." >&2
    exit 1
fi

# --- Validate Environment Configuration ---
echo "Validating environment configuration..."

# Validate directory paths exist
for dir_var in LOG_DIR PSA_SYNC_DATA_DIR EN_OPS_UTILS_HOME HARVEST_SOLR_CONF_HOME PDS4_SOLR_DOC_HOME; do
    dir_path="${!dir_var}"
    if [[ ! -d "$dir_path" ]]; then
        echo "Error: Directory does not exist: $dir_var=$dir_path" >&2
        exit 1
    fi
done

# Validate executable paths exist
HARVEST_SOLR_BIN="$HARVEST_SOLR_HOME/bin/harvest-solr"
REGISTRY_MGR_BIN="$REGISTRY_MGR_SOLR_HOME/bin/registry-mgr-solr"

if [[ ! -x "$HARVEST_SOLR_BIN" ]]; then
    echo "Error: harvest-solr not found or not executable" >&2
    echo "Expected: $HARVEST_SOLR_BIN" >&2
    exit 1
fi

if [[ ! -x "$REGISTRY_MGR_BIN" ]]; then
    echo "Error: registry-mgr-solr not found or not executable" >&2
    echo "Expected: $REGISTRY_MGR_BIN" >&2
    exit 1
fi

# Validate email format (basic check)
if [[ ! "$EMAIL_RECIPIENTS" =~ @ ]] || [[ ! "$EMAIL_RECIPIENTS" =~ \. ]]; then
    echo "Warning: EMAIL_RECIPIENTS may be invalid: $EMAIL_RECIPIENTS" >&2
    echo "Expected format: email@domain.com or email1@domain.com,email2@domain.com" >&2
fi

echo "✓ Environment configuration validated successfully"

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

# Setup log file
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/psa_sync_$TIMESTAMP.log"

# Redirect stdout & stderr to the log file
exec > >(tee -a "$LOG_FILE") 2>&1

# --- Parse Arguments ---
NO_EMAIL=false
DRY_RUN=false
STEPS_TO_RUN=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--config)
            # Already processed above, skip both flag and value
            shift
            shift
            ;;
        -n|--no-email)
            NO_EMAIL=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        --download-labels)
            STEPS_TO_RUN+=("$STEP_DOWNLOAD")
            shift
            ;;
        --create-docs)
            STEPS_TO_RUN+=("$STEP_HARVEST")
            shift
            ;;
        --load)
            STEPS_TO_RUN+=("$STEP_LOAD")
            shift
            ;;
        *)
            echo "Error: Unknown argument '$1'" >&2
            usage
            ;;
    esac
done

# If no steps specified, default to all three
if [ ${#STEPS_TO_RUN[@]} -eq 0 ]; then
    STEPS_TO_RUN=("$STEP_DOWNLOAD" "$STEP_HARVEST" "$STEP_LOAD")
    echo "=== [$(date)] No steps specified, defaulting to all steps ==="
fi

# Sort steps in ascending order and remove duplicates
mapfile -t STEPS_TO_RUN < <(printf '%s\n' "${STEPS_TO_RUN[@]}" | sort -nu)

# Map step numbers to names for display
STEP_NAMES=()
for step in "${STEPS_TO_RUN[@]}"; do
    case $step in
        "$STEP_DOWNLOAD") STEP_NAMES+=("download-labels") ;;
        "$STEP_HARVEST") STEP_NAMES+=("create-docs") ;;
        "$STEP_LOAD") STEP_NAMES+=("load") ;;
    esac
done

echo "=== [$(date)] Steps to run: ${STEP_NAMES[*]} ==="

# Determine if email should be sent (default: always send, unless dry-run)
SEND_EMAIL=true
if [ "$DRY_RUN" = true ]; then
    SEND_EMAIL=false
    echo "Email notification: DISABLED (dry-run mode)"
elif [ "$NO_EMAIL" = true ]; then
    SEND_EMAIL=false
    echo "Email notification: DISABLED (suppressed with -n flag)"
else
    echo "Email notification: ENABLED (default)"
fi

# Dry-run mode - show configuration and validate dependencies
if [ "$DRY_RUN" = true ]; then
    VALIDATION_FAILED=false

    echo ""
    echo "=== DRY-RUN MODE - Configuration Summary ==="
    echo "Steps to execute: ${STEP_NAMES[*]}"
    echo "Log file would be: $LOG_FILE"
    echo "Email recipients: $EMAIL_RECIPIENTS"
    echo "Hostname label: $HOSTNAME_LABEL"
    echo ""
    echo "Environment paths:"
    echo "  EN_OPS_UTILS_HOME: $EN_OPS_UTILS_HOME"
    echo "  PSA_SYNC_DATA_DIR: $PSA_SYNC_DATA_DIR"
    echo "  HARVEST_SOLR_HOME: $HARVEST_SOLR_HOME"
    echo "  HARVEST_SOLR_BIN: $HARVEST_SOLR_BIN"
    echo "  PDS4_SOLR_DOC_HOME: $PDS4_SOLR_DOC_HOME"
    echo "  REGISTRY_MGR_BIN: $REGISTRY_MGR_BIN"
    echo ""
    echo "Step-specific dependencies:"

    # Check step 1 dependencies (download)
    if step_is_enabled "$STEP_DOWNLOAD"; then
        echo "  Step 1 (download-labels):"
        if command -v python &> /dev/null; then
            echo "    ✓ Python: $(python --version 2>&1)"
        else
            echo "    ✗ Python: NOT FOUND (required for step 1)"
            VALIDATION_FAILED=true
        fi
        if [ -n "$CONDA_ENV" ]; then
            echo "    ℹ Conda environment configured: $CONDA_ENV"
        fi
    fi

    # Check step 2 dependencies (harvest)
    if step_is_enabled "$STEP_HARVEST"; then
        echo "  Step 2 (create-docs):"
        if command -v java &> /dev/null; then
            echo "    ✓ Java: $(java -version 2>&1 | head -n 1)"
        else
            echo "    ✗ Java: NOT FOUND (required for step 2)"
            VALIDATION_FAILED=true
        fi
    fi

    # Step 3 has no special dependencies
    if step_is_enabled "$STEP_LOAD"; then
        echo "  Step 3 (load):"
        echo "    ℹ Uses registry-mgr-solr (already validated)"
    fi

    echo ""
    if [ "$VALIDATION_FAILED" = true ]; then
        echo "✗ Dry-run validation failed - resolve issues before running"
        exit 1
    else
        echo "✓ Dry-run validation complete - configuration is ready"
        echo "Run without --dry-run to execute"
        exit 0
    fi
fi

# --- Email Notification Function ---
send_notification() {
    local exit_code=$?
    local status_subject="[PSA Label Sync] Ingestion Succeeded on ${HOSTNAME_LABEL} (Steps: ${STEP_NAMES[*]})"

    if [ $exit_code -ne 0 ]; then
        status_subject="[PSA Label Sync] FAILED on ${HOSTNAME_LABEL} (Exit Code: $exit_code, Steps: ${STEP_NAMES[*]})"
    fi

    # Check if step 2 (harvest/create-docs) was run
    local step_2_ran=false
    for step in "${STEPS_TO_RUN[@]}"; do
        if [ "$step" = "$STEP_HARVEST" ]; then
            step_2_ran=true
            break
        fi
    done

    # Build email body
    local email_body="PSA Label Sync Completed.

Hostname: ${HOSTNAME_LABEL}
Steps Executed: ${STEP_NAMES[*]}
Job Status: $( [ $exit_code -eq 0 ] && echo "SUCCESS" || echo "FAILED (Exit Code: $exit_code)" )
Log File: $LOG_FILE
"

    # Add harvest summary only if step 2 was run
    if [ "$step_2_ran" = true ]; then
        SUMMARY_TEXT=$(grep -A 22 "Summary :" "$LOG_FILE" || echo "No summary block generated.")
        ERRORS_TEXT=$(grep ERROR "$LOG_FILE" | grep -v "line 1: Content is not allowed in prolog" | head -n 20 || echo "No non-ignorable errors found.")

        email_body="$email_body
--- HARVEST SUMMARY ---
$SUMMARY_TEXT

--- RELEVANT LOG ERRORS (First 20) ---
$ERRORS_TEXT
"
    fi

    # Send summary email
    mail -s "$status_subject" "$EMAIL_RECIPIENTS" <<EOF
$email_body
EOF
}

# Register the trap only if email should be sent
if [ "$SEND_EMAIL" = true ]; then
    trap send_notification EXIT
fi

# --- Environment Setup Function ---
setup_environment() {
    echo "=== [$(date)] Setting up environment ==="

    # Log key environment paths
    echo "EN_OPS_UTILS_HOME: $EN_OPS_UTILS_HOME"
    echo "PSA_SYNC_DATA_DIR: $PSA_SYNC_DATA_DIR"
    echo "LOG_DIR: $LOG_DIR"
}

# --- Step 1: Download PSA Labels ---
step_1_download() {
    echo "=== [$(date)] Step 1: Downloading PSA Labels ==="

    # Activate conda environment if specified (otherwise uses system python from PATH)
    if [ -n "$CONDA_ENV" ]; then
        echo "Activating conda environment: $CONDA_ENV"
        if [ -n "$CONDA_HOME" ]; then
            source "$CONDA_HOME/etc/profile.d/conda.sh"
        else
            # Try common conda installation paths
            if [ -f "$HOME/.conda/etc/profile.d/conda.sh" ]; then
                source "$HOME/.conda/etc/profile.d/conda.sh"
            elif [ -f "/opt/conda/etc/profile.d/conda.sh" ]; then
                source "/opt/conda/etc/profile.d/conda.sh"
            else
                echo "Warning: conda.sh not found, attempting direct conda activate" >&2
            fi
        fi

        if ! conda activate "$CONDA_ENV"; then
            echo "Error: Failed to activate conda environment: $CONDA_ENV" >&2
            exit 1
        fi
    else
        echo "Using system python from PATH"
    fi

    # Validate Python is available
    if ! command -v python &> /dev/null; then
        echo "Error: Python is required for step 1 but not found in PATH" >&2
        exit 1
    fi

    echo "Python: $(which python)"
    python --version

    # Run pds-sync-api
    cd "$EN_OPS_UTILS_HOME"
    python src/pds/en_ops_utils/portal/pds_sync_api.py -p "$PSA_SYNC_DATA_DIR" -e "$PSA_SYNC_EXCLUDES"
    echo "=== [$(date)] Step 1 completed successfully ==="
}

# --- Step 2: Run Harvest ---
step_2_harvest() {
    echo "=== [$(date)] Step 2: Generating Solr Docs with Harvest ==="

    # Setup JAVA_HOME if specified (otherwise uses system java from PATH)
    if [ -n "$JAVA_HOME" ]; then
        export JAVA_HOME
        export PATH="$JAVA_HOME/bin:$PATH"
        echo "Using JAVA_HOME: $JAVA_HOME"
    else
        echo "Using system java from PATH"
    fi

    # Validate Java is available (required for harvest)
    if ! command -v java &> /dev/null; then
        echo "Error: Java is required for step 2 but not found in PATH" >&2
        echo "Set JAVA_HOME or ensure java is in your PATH" >&2
        exit 1
    fi

    # Log Java details for diagnostic tracking
    echo "Java: $(which java)"
    java -version

    HARVEST_SOLR_CONFIG="$HARVEST_SOLR_CONF_HOME/$HARVEST_CONFIG_FILE"

    # Set JVM options to allocate 2GB or 8GB of max heap memory
    export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:--Xms2g -Xmx8g}"

    # If JVM OOM (Out of Memory) still triggers at Harvest's teardown
    set +e
    "$HARVEST_SOLR_HOME/bin/harvest-solr" -c "$HARVEST_SOLR_CONFIG" -o "$PDS4_SOLR_DOC_HOME"
    HARVEST_EXIT=$?
    set -e

    # --- Validate Summary Output ---
    # Parse counts from the Harvest summary block in the log
    LABELS_REGISTERED=$(awk '/Product Labels:/{flag=1; next} flag && /Successfully registered/{print $1; exit}' "$LOG_FILE")
    DOCS_CREATED=$(awk '/Registry Search Solr Documents:/{flag=1; next} flag && /Successfully created/{print $1; exit}' "$LOG_FILE")

    # Default empty values to 0 if parsing fails
    LABELS_REGISTERED=${LABELS_REGISTERED:-0}
    DOCS_CREATED=${DOCS_CREATED:-0}

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

# --- Step 3: Load into Registry ---
step_3_load() {
    echo "=== [$(date)] Step 3: Loading Solr Docs into Registry ==="
    "$REGISTRY_MGR_SOLR_HOME/bin/registry-mgr-solr" "$PDS4_SOLR_DOC_HOME/solr-docs"
    echo "=== [$(date)] Step 3 completed successfully ==="
}

# --- Main Execution ---
# Setup environment (always required)
setup_environment

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
