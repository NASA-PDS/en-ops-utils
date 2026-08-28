# Portal Tools

Tools for syncing PSA (Planetary Science Archive) labels and managing portal data ingestion.

## Tools

### pds-sync-api

Downloads ESA PSA product XML files from the PDS Search API.

**Installation:**
```bash
pip install -e .  # From repository root
```

**Usage:**
```bash
pds-sync-api --download-path /path/to/labels/
```

**Options:**
```
-p, --download-path PATH    Path to download XML files (required)
-n, --node-name NAME        Node name to query (default: psa)
-c, --config FILE           Harvest config output path (default: harvest.cfg)
-e, --exclude-patterns STR  Exclusion patterns (e.g., nasa/pds)
-f, --force                 Force re-download (skip cached files)
-v, --verbose               Enable debug logging
```

---

## psa_sync_wrapper.sh

Wrapper script that automates the complete PSA label sync workflow.

**Requirements:** Bash 4.0+ (for associative arrays)

### What It Does

Orchestrates three steps with validation, logging, and notifications:

1. **Download** - Uses `pds-sync-api` to download PSA labels from PDS Search API
2. **Harvest** - Generates Solr documents from labels using harvest-solr
3. **Load** - Loads Solr documents into registry using registry-mgr-solr

### Features

- Fail-fast validation before execution
- Run all steps or select individual steps
- Timestamped logs (console + file)
- Email notifications with harvest summary
- Success markers for multi-machine workflows
- Optimized for automation (cron-ready)

---

## Quick Start

### 1. Create Configuration File

```bash
# Copy template (can use local name)
cp psa_sync_wrapper.env.example dev.env

# Edit with your paths
nano dev.env

# Secure it
chmod 600 dev.env
```

**Security:**
- `.env` files are protected by `.gitignore` - safe to store locally
- Always set restrictive permissions: `chmod 600 *.env`

### 2. Run the Script

```bash
# Run all three steps
./psa_sync_wrapper.sh -c my-config.env

# Run only specific steps
./psa_sync_wrapper.sh -c my-config.env --download-labels
./psa_sync_wrapper.sh -c my-config.env --create-docs --load
```

---

## Configuration

### Required Variables

| Variable | Description |
|----------|-------------|
| `LOG_DIR` | Directory for log files |
| `PSA_SYNC_DATA_DIR` | Directory for PSA label data |
| `EN_OPS_UTILS_HOME` | Path to en-ops-utils repository |
| `HARVEST_SOLR_HOME` | Path to harvest-solr installation |
| `HARVEST_SOLR_CONF_HOME` | Harvest config directory |
| `PDS4_SOLR_DOC_HOME` | Solr document output directory |
| `REGISTRY_MGR_SOLR_HOME` | Path to registry-manager-solr |
| `EMAIL_RECIPIENTS` | Email addresses (comma-separated) |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOSTNAME_LABEL` | `$(hostname)` | Label for email subject |
| `CONDA_ENV` | None | Conda environment name |
| `CONDA_HOME` | Auto-detected | Conda installation path |
| `JAVA_HOME` | None | Java installation path |
| `HARVEST_CONFIG_FILE` | `harvest-policy-ipda.xml` | Harvest policy file |
| `PSA_SYNC_EXCLUDES` | `nasa/pds` | Exclusion pattern for pds-sync-api |
| `JAVA_TOOL_OPTIONS` | `-Xms2g -Xmx8g` | JVM memory options |
| `SUCCESS_MARKER_FILE` | None | Success marker path for multi-machine coordination |

---

## Command-Line Options

```bash
./psa_sync_wrapper.sh [OPTIONS] [STEPS]

STEPS (optional, defaults to all):
    --download-labels   Download PSA Labels (step 1)
    --create-docs       Run Harvest (step 2)
    --load              Load into Registry (step 3)

OPTIONS:
    -c, --config FILE   Load config from file (recommended)
    -n, --no-email      Suppress email notification
    -h, --help          Show help message
```

**Note:** Steps always execute in order (1→2→3) regardless of input order.

---

## Usage Examples

```bash
# Run all three steps (default)
./psa_sync_wrapper.sh -c my-config.env

# Run only download step
./psa_sync_wrapper.sh -c my-config.env --download-labels

# Run download without email (testing)
./psa_sync_wrapper.sh -c my-config.env -n --download-labels

# Run harvest and load steps
./psa_sync_wrapper.sh -c my-config.env --create-docs --load

# Source config manually (alternative to -c flag)
. my-config.env && ./psa_sync_wrapper.sh
```

---

## Validation

The script validates configuration **before execution**:

### Step 1 (download-labels)
- Directories exist: EN_OPS_UTILS_HOME, PSA_SYNC_DATA_DIR
- Python script exists: pds_sync_api.py
- Python/conda available and configured

### Step 2 (create-docs)
- Directories exist: HARVEST_SOLR_CONF_HOME, PDS4_SOLR_DOC_HOME
- harvest-solr executable exists
- Harvest config file exists
- Java available (JAVA_HOME or system)

### Step 3 (load)
- Directory exists: PDS4_SOLR_DOC_HOME
- registry-mgr-solr executable exists

### Email (if enabled)
- EMAIL_RECIPIENTS has valid format
- mail command available

**On validation failure:** Script exits with code 1 and clear error message.

---

## Email Notifications

Email sent by default after execution (use `-n` to suppress).

### Email Contents
- Hostname and timestamp
- Steps executed
- Success/failure status
- Harvest summary (labels processed, docs created)
- Error log excerpts (first 20 errors)
- Log file location

### Testing Email
```bash
# Test mail command
echo "Test" | mail -s "Test Subject" "$EMAIL_RECIPIENTS"

# Install mail utility if missing
sudo apt-get install mailutils  # Debian/Ubuntu
sudo yum install mailx          # CentOS/RHEL
```

---

## Logging

Logs written to: `$LOG_DIR/psa_sync_YYYYMMDD_HHMMSS.log`

**Features:**
- Output to both console and file (via `tee`)
- Restrictive permissions (chmod 600)
- Timestamped messages
- Skipped steps marked with "(USER SKIPPED)"

**Example log:**
```
===========================================
=== [2025-01-15 14:23:45] Configuration Summary ===
Log file:           /var/log/psa-sync/psa_sync_20250115_142345.log
Hostname:           production-server
Running 3 steps: download-labels create-docs load
Email notification: Enabled
===========================================
✓ Configuration validated for steps: download-labels create-docs load
=== [2025-01-15 14:23:46] Step 1: Downloading PSA Labels ===
...
```

---

## Automation with Cron

```cron
# Run daily at 2 AM
0 2 * * * /path/to/psa_sync_wrapper.sh -c /path/to/prod.env

# Run weekly on Monday at 3 AM
0 3 * * 1 /path/to/psa_sync_wrapper.sh -c /path/to/prod.env
```

**Best Practices:**
- Use absolute paths
- Test manually before scheduling
- Set up log rotation:
  ```bash
  # /etc/logrotate.d/psa-sync
  /var/log/psa-sync/*.log {
      daily
      rotate 30
      compress
      missingok
  }
  ```

---

## Multi-Machine Workflows

**Use Case:** Development machine runs full pipeline (steps 1-3), production machine loads to production registry (step 3) after development completes.

### Success Marker + Cron Pattern

**Benefits:**
- **Secure**: No SSH keys, no network access, production controls execution
- **Lightweight**: Cron does scheduling, exits immediately if no work
- **Simple**: Standard tools, easy to debug
- **Efficient**: Only runs when needed, self-cleaning

### Directory Structure

Mirrored on both machines:
```
portal/
  ├── psa_sync_wrapper.sh       # Wrapper script
  ├── dev.env                    # Development config (.gitignore protected)
  ├── prod.env                   # Production config (.gitignore protected)
  ├── check_and_load.sh          # Production checker (prod only)
  └── check_and_load.env         # Checker config (prod only, .gitignore protected)
```

Shared filesystem:
```
/shared/filesystem/.psa_sync_ready   # Marker: dev writes, prod reads
```

### Setup

**1. Development Machine:**

Create `dev.env` from template:
```bash
cp psa_sync_wrapper.env.example dev.env
chmod 600 dev.env
```

Edit `dev.env`:
```bash
# ... standard configuration ...
SUCCESS_MARKER_FILE="/shared/filesystem/.psa_sync_ready"
```

Run normally:
```bash
./psa_sync_wrapper.sh -c dev.env  # Creates marker on success
```

**2. Production Machine:**

Create configuration files:
```bash
cp dev.env prod.env
cp check_and_load.env.example check_and_load.env
chmod 600 prod.env check_and_load.env
```

Edit `prod.env` (based off `dev.env`):
```bash
# edit HOSTNAME_LABEL
# edit other values if needed
```

Edit `check_and_load.env`:
```bash
MARKER_FILE="/shared/filesystem/.psa_sync_ready"
WRAPPER_SCRIPT="./psa_sync_wrapper.sh"  # Relative path (both in same directory)
WRAPPER_CONFIG="./prod.env"              # Relative path
MAX_AGE_HOURS=24
```

Add to crontab (use absolute paths in cron):
```cron
# Check every 4 hours
0 */4 * * * cd /full/path/to/portal && ./check_and_load.sh -c check_and_load.env >> /var/log/psa-sync/check.log 2>&1
```

### How It Works

1. Development runs full pipeline, creates marker on success
2. Production cron checks for marker every 4 hours
3. If marker exists and fresh, runs step 3 (load)
4. Removes marker after successful load

---

## Troubleshooting

### Bash Version Issues

**"declare: -A: invalid option"**

**Cause:** Bash version too old (< 4.0)

**Solution:**
```bash
# Check version
bash --version

# macOS: Install newer bash via Homebrew
brew install bash

# Update shebang or run explicitly
/usr/local/bin/bash ./psa_sync_wrapper.sh -c dev.env
```

### Configuration Issues

**"Missing required environment variables"**
```bash
# Solution: Use -c flag or source config
./psa_sync_wrapper.sh -c my-config.env
```

**"Config file not found"**
```bash
# Solution: Verify path
ls -l /path/to/config.env
```

### Python/Conda Issues

**"Conda environment not found"**
```bash
# List environments
conda env list

# Verify name matches
CONDA_ENV="myenv"  # Must match exactly
```

**"Python required but not found"**
```bash
# Check Python
which python
python --version

# Or use conda
CONDA_ENV="myenv"
```

### Java Issues

**"Java required but not found"**
```bash
# Option 1: Set JAVA_HOME
JAVA_HOME="/usr/lib/jvm/java-17-openjdk"

# Option 2: Verify system Java
which java
java -version
```

### Harvest Issues

**"Harvest validation failed (labels ≠ docs)"**
```bash
# Check logs for errors
grep ERROR /var/log/psa-sync/psa_sync_*.log

# Increase Java heap memory
JAVA_TOOL_OPTIONS="-Xms4g -Xmx16g"
```

### Email Issues

**"mail command not found"**
```bash
# Install mail utility
sudo apt-get install mailutils  # Debian/Ubuntu
sudo yum install mailx          # CentOS/RHEL

# Or disable email
./psa_sync_wrapper.sh -n
```

---

## Deployment Checklist

### Configuration
- [ ] Copy `psa_sync_wrapper.env.example` to secure location
- [ ] Customize all required variables
- [ ] Use absolute paths for all directories
- [ ] Set permissions: `chmod 600 config.env`

### Validation
- [ ] Verify Java: `java -version`
- [ ] Verify Python: `python --version`
- [ ] Test email: `echo "Test" | mail -s "Test" "$EMAIL_RECIPIENTS"`
- [ ] Verify all directory paths exist

### Testing
- [ ] Test single step: `./psa_sync_wrapper.sh -c config.env --download-labels`
- [ ] Verify logs written to `$LOG_DIR`
- [ ] Run other steps: `./psa_sync_wrapper.sh -c config.env --create-docs --load`
- [ ] Review log file for errors

### Production
- [ ] Test manual run before cron
- [ ] Monitor first few cron runs
- [ ] Set up log rotation

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `pds_sync_api.py` | Python script for downloading PSA labels |
| `psa_sync_wrapper.sh` | Bash wrapper for complete workflow |
| `psa_sync_wrapper.env.example` | Template for wrapper configuration |
| `check_and_load.sh` | Production checker for multi-machine coordination |
| `check_and_load.env.example` | Template for checker configuration |
| `README.md` | This documentation |

---

## See Also

- [Main README](../../../../README.md) - Repository setup and development
- [CLAUDE.md](../../../../CLAUDE.md) - Claude Code guidance
- [Harvest and Registry](https://github.com/NASA-PDS/registry-mgr-solr) - harvest-solr and legacy-registry documentation
