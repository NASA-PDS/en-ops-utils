# Portal Tools - PSA Label Sync Pipeline

Automated pipeline for syncing ESA Planetary Science Archive (PSA) labels into the PDS Registry.

## Overview

Three-step workflow for weekly ingestion of PSA product labels:

1. **Download** - Fetch PSA labels via PDS Search API (`pds-sync-api`)
2. **Harvest** - Generate Solr documents from labels (`harvest-solr`)
3. **Load** - Ingest documents into Registry (`registry-mgr-solr`)

**Key Design:**
- Steps 1+2 run weekly on one machine via cron
- Step 3 runs hourly on multiple machines via cron (multi-machine coordination)
- Marker files coordinate execution across steps and machines
- Email notifications sent at each step
- Lock files prevent concurrent execution

Note: Step 3 (ingest documents into Registry with `wrapper_registry.sh`) happens automatically for every Harvest Solr job, even if not initiated by steps 1+2 (download and harvest with `psa_download_and_harvest.sh`).

## Scripts

### `pds_sync_api.py`

Downloads PSA product XML labels from PDS Search API.

**Installation:**
```bash
pip install --editable .  # Installs as 'pds-sync-api' command
```

**Usage:**
```bash
pds-sync-api -p /data/psa/labels -e nasa/pds
```

**Options:**
- `-p, --download-path` - Directory to download labels (required)
- `-e, --exclude-patterns` - Space-separated patterns to exclude (e.g., "nasa/pds esa/psa")

**Conda environment required** - see configuration section.

---

### `psa_download_and_harvest.sh`

Orchestrates steps 1+2: Downloads labels then runs Harvest to create Solr documents.

**Usage:**
```bash
./psa_download_and_harvest.sh -c psa_download.env
```

**Options:**
- `-c, --config FILE` - Load environment variables from config file (required)
- `-h, --help` - Show help message

**Behavior:**
- Activates conda environment and runs `pds-sync-api`
- On download success: sends email, runs `harvest-solr` to generate Solr docs
- On download failure: sends failure email, harvest doesn't run
- Harvest creates marker file on success (signals step 3 to run)
- Lock file prevents concurrent runs
- All output logged to timestamped file in `PSA_DOWNLOAD_LOG_DIR`

**Cron setup (weekly):**
```cron
@weekly . ~/.bash_profile && cd /path/to/portal/ && ./psa_download_and_harvest.sh -c psa_download.env
```

---

### `wrapper_registry.sh`

Loads Solr documents into Registry with multi-machine coordination.

**Usage:**
```bash
./wrapper_registry.sh
```

**Options:**
- `-h, --help` - Show help message

**Behavior:**
- Checks for Harvest success marker file
- If marker exists and this machine hasn't processed it yet, runs `registry-mgr-solr`
- Creates machine-specific success marker
- When both machines complete, cleans up all markers
- Sends email notification on completion
- Silent exit if no work to do (cron-friendly)

**Cron setup (hourly on both dev and prod machines):**
```cron
@hourly . ~/.bash_profile && /path/to/portal/wrapper_registry.sh
```

**Multi-machine coordination:**
1. Harvest (step 2) creates harvest marker: `.harvest_success`
2. Each machine runs hourly, checks for harvest marker
3. Machine processes work, creates machine-specific marker: `.registry_mgr_success_<hostname>`
4. When both machines have markers (count=2), last machine cleans up all markers
5. Cycle repeats on next harvest success

## Configuration

### Required Environment Variables

Create `psa_download.env` based on `psa_download.env.example`:

**Download-specific (psa_download_and_harvest.sh):**
```bash
# Data and logging
export PSA_SYNC_DATA_DIR="/data/psa/labels"
export PSA_DOWNLOAD_LOG_DIR="/logs/psa-download"

# Python environment
export PSA_SYNC_CONDA_ENV="conda-env"
export CONDA_HOME="/home/user/.conda"  # Optional, auto-detected if omitted

# Download options
export PSA_SYNC_EXCLUDES="nasa/pds"  # Optional, space-separated patterns

# Harvest configuration
export PSA_SYNC_HARVEST_SOLR_CONFIG_FILE="harvest-policy-ipda.xml"
export HARVEST_SOLR_HOME="/path/to/harvest-legacy"
export HARVEST_SOLR_CONF_HOME="/path/to/config"
export HARVEST_SOLR_LOG_FILE="/logs/harvest/harvest_$(date +%Y%m%d_%H%M%S).log"

# Output and coordination
export PDS4_SOLR_DOC_HOME="/data/solr-docs"
export HARVEST_SOLR_MARKER_FILE="/shared/.harvest_success"

# Email notifications
export LEGACY_REGISTRY_EMAIL_RECIPIENTS="ops@example.com"
export HOSTNAME_LABEL="dev-machine"
```

**Registry-specific (wrapper_registry.sh, set in .bash_profile):**
```bash
# Registry configuration
export REGISTRY_MGR_SOLR_HOME="/path/to/registry-manager-solr"
export REGISTRY_MGR_SOLR_LOG_FILE="/logs/registry/registry_$(date +%Y%m%d_%H%M%S).log"

# Coordination (shared across machines)
export HARVEST_SOLR_MARKER_FILE="/shared/.harvest_success"
export LEGACY_REGISTRY_MARKER_DIR="/shared/markers"

# Email and hostname (same as above)
export LEGACY_REGISTRY_EMAIL_RECIPIENTS="ops@example.com"
export HOSTNAME_LABEL="dev-machine"  # or "prod-machine"

# Already set from psa_download.env
export PDS4_SOLR_DOC_HOME="/data/solr-docs"
```

### Configuration Files

- `psa_download.env` - Configuration for download+harvest script
- `psa_download.env.example` - Template with documentation
- Store configs in the portal directory, reference via `-c` flag

## Workflow Diagram

```
Weekly (Cron: every week, dev machine only)
├─ psa_download_and_harvest.sh
   ├─ Step 1: Download labels (pds-sync-api)
   │  ├─ Success → email notification
   │  └─ Failure → email notification, exit
   ├─ Step 2: Harvest labels (harvest-solr)
   │  ├─ Success → email notification, create .harvest_success marker
   │  └─ Failure → email notification, no marker

Hourly (Cron: every hour, both machines)
├─ wrapper_registry.sh (dev machine)
│  ├─ Check .harvest_success marker exists?
│  ├─ Check .registry_mgr_success_dev exists? (skip if yes)
│  ├─ Step 3: Load into registry (registry-mgr-solr)
│  ├─ Create .registry_mgr_success_dev marker
│  └─ Email notification
│
├─ wrapper_registry.sh (prod machine)
   ├─ Check .harvest_success marker exists?
   ├─ Check .registry_mgr_success_prod exists? (skip if yes)
   ├─ Step 3: Load into registry (registry-mgr-solr)
   ├─ Create .registry_mgr_success_prod marker
   ├─ Count markers: if 2, cleanup all markers
   └─ Email notification
```

## Lock Files

**Purpose:** Prevent concurrent script execution.

**psa_download_and_harvest.sh:**
- Lock file: `$PSA_DOWNLOAD_LOG_DIR/psa_download.lock`
- Created at start, removed on exit (success or failure)
- If lock exists, script exits with error message

**harvest-solr:**
- Lock file: `$PDS4_SOLR_DOC_HOME/harvest-solr.lock`
- Created at start, removed on exit
- If lock exists, harvest exits with error message

## Email Notifications

**Download step (psa_download_and_harvest.sh):**
- Subject: `[PSA Download] Success/FAILED on <hostname>`
- Sent after download completes or fails
- Includes: exit code, data directory, timestamp, excludes

**Harvest step (harvest-solr):**
- Subject: `[Harvest Solr] Succeeded/FAILED on <hostname>`
- Sent after harvest completes or fails
- Includes: summary (labels/docs), log file location, errors

**Registry step (wrapper_registry.sh):**
- Subject: `[Registry Mgr Solr] Succeeded/FAILED on <hostname>`
- Sent after registry load completes or fails
- Includes: log file location, last 50 log lines

**Requirements:**
- `LEGACY_REGISTRY_EMAIL_RECIPIENTS` must be set
- `mail` command must be available (install `mailutils` or `mailx`)

## Marker Files

**Harvest success marker** (`HARVEST_SOLR_MARKER_FILE`):
- Created by harvest-solr on successful completion
- Contains: timestamp, datetime
- Signals wrapper_registry.sh to run
- Removed when both machines complete registry load

**Registry success markers** (per-machine):
- Created by wrapper_registry.sh on successful load
- Format: `.registry_mgr_success_<HOSTNAME_LABEL>`
- Contains: timestamp, datetime, hostname, log file path
- Removed when both machines complete (cleanup at count=2)

**Marker file location:**
- Must be on shared filesystem accessible to all machines
- Set via `HARVEST_SOLR_MARKER_FILE` and `LEGACY_REGISTRY_MARKER_DIR`

## Logging

**Download logs:**
- Location: `$PSA_DOWNLOAD_LOG_DIR/psa_download_<timestamp>.log`
- Contains: download progress, harvest output, timestamps
- Created by psa_download_and_harvest.sh via `exec` redirect

**Harvest logs:**
- Location: `$HARVEST_SOLR_LOG_FILE` (if set)
- Contains: harvest progress, summary, errors
- Created by harvest-solr internal logging

**Registry logs:**
- Location: `$REGISTRY_MGR_SOLR_LOG_FILE`
- Contains: registry load progress, success/failure status
- Created by wrapper_registry.sh via `exec` redirect

## Troubleshooting

### Download fails with "Permission denied"

**Check conda environment:**
```bash
conda env list | grep $PSA_SYNC_CONDA_ENV
```

**Verify pds-sync-api is installed:**
```bash
conda activate $PSA_SYNC_CONDA_ENV
which pds-sync-api
```

### Harvest exits with OutOfMemoryError

**Symptom:** Harvest completes successfully but crashes during teardown with Java heap space error.

**Solution:** Already handled - harvest checks log for "0          Failed to get created" pattern to determine success even with non-zero exit code.

**Increase heap (if needed):**
(Legacy attempt. Does not work)
```bash
export JAVA_TOOL_OPTIONS="-Xms4g -Xmx16g"  # Increase from 8g to 16g
```

### Registry not triggering after harvest completes

**Check harvest marker exists:**
```bash
ls -l "$HARVEST_SOLR_MARKER_FILE"
```

**Check registry markers:**
```bash
ls -la "$LEGACY_REGISTRY_MARKER_DIR"/.registry_mgr_success_*
```

If registry markers exist from previous run, remove them:
```bash
rm "$LEGACY_REGISTRY_MARKER_DIR"/.registry_mgr_success_*
```

**Test wrapper_registry manually:**
```bash
./wrapper_registry.sh
```

### No email notifications

**Check email configuration:**
```bash
echo $LEGACY_REGISTRY_EMAIL_RECIPIENTS
command -v mail
```

**Install mail command:**
```bash
sudo apt-get install mailutils  # Debian/Ubuntu
sudo yum install mailx          # RHEL/CentOS
```

### Lock file stuck (script won't run)

**Remove stale lock file:**
```bash
rm "$PSA_DOWNLOAD_LOG_DIR/psa_download.lock"
rm "$PDS4_SOLR_DOC_HOME/harvest-solr.lock"
```

**Verify no process is actually running:**
```bash
ps aux | grep -E "(pds-sync-api|harvest-solr)" | grep -v grep
```

### Multiple processes spawning from cron

**Check for duplicate cron entries:**
```bash
crontab -l | grep -E "(psa_download|wrapper_registry)"
```

**Check system-wide cron:**
```bash
sudo cat /etc/crontab
sudo ls /etc/cron.d/
```

**Verify lock files are working** - should prevent concurrent runs.

## Testing

### Test download step only:
```bash
# Activate conda
. "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$PSA_SYNC_CONDA_ENV"

# Run download
pds-sync-api -p "$PSA_SYNC_DATA_DIR" -e "$PSA_SYNC_EXCLUDES"
```

### Test full download+harvest:
```bash
./psa_download_and_harvest.sh -c psa_download.env
```

### Test registry load:
```bash
# Create test harvest marker
echo "timestamp=$(date +%s)" > "$HARVEST_SOLR_MARKER_FILE"

# Run registry wrapper
./wrapper_registry.sh
```

### Test marker cleanup:
```bash
# Create both registry markers manually
echo "timestamp=$(date +%s)" > "$LEGACY_REGISTRY_MARKER_DIR/.registry_mgr_success_dev"
echo "timestamp=$(date +%s)" > "$LEGACY_REGISTRY_MARKER_DIR/.registry_mgr_success_prod"

# Run wrapper - should trigger cleanup
./wrapper_registry.sh
```

## Maintenance

### Weekly monitoring:
- Check logs for errors in download/harvest/load
- Verify email notifications received
- Confirm markers are created and cleaned up

### Monthly maintenance:
- Review log disk usage in `PSA_DOWNLOAD_LOG_DIR` and `REGISTRY_MGR_SOLR_LOG_FILE` locations
- Clean up old logs if needed (consider log rotation)
- Verify cron jobs are running (`crontab -l`)

### Quarterly review:
- Validate environment variables are still correct
- Check Java heap settings adequate for harvest data volume
- Review email recipient list

## Development Notes

### Legacy system:
- This is a legacy pipeline scheduled for retirement
- No new features planned
- Focus: stability and maintenance
- OutOfMemoryError at harvest teardown is known issue, handled via log checking

### Multi-machine coordination:
- Hardcoded for exactly 2 machines (dev + prod)
- Cleanup triggers when marker count reaches 2
- To add more machines, update cleanup logic in wrapper_registry.sh

### Marker file race conditions:
- Possible if both machines complete simultaneously
- Mitigated by cron hourly schedule (spreads out execution)
- Both machines will eventually process work successfully
