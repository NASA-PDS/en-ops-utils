# Portal Tools

Tools for syncing PSA (Planetary Science Archive) labels and managing portal data ingestion.

## Tools in this Directory

### pds-sync-api

Downloads ESA PSA product XML files from the PDS search API and generates a harvest configuration file.

**Installation:**

```bash
# Install from repository root
pip install -e .
```

**Usage:**

```bash
# As console script (after pip install)
pds-sync-api --download-path download/

# Or run directly
python pds_sync_api.py --download-path download/
```

**Options:**

```
--node-name, -n       Node name to query (default: psa)
--download-path, -p   Path to download XML files
--config, -c          Harvest config output path (default: harvest.cfg)
--exclude, -e         Exclusion pattern (e.g., nasa/pds)
```

### psa_sync_wrapper.sh

Automated wrapper script for the complete PSA label sync workflow. Orchestrates three steps:

1. **Download PSA Labels** - Uses `pds-sync-api` to download labels
2. **Create Solr Docs** - Runs Harvest to generate Solr documents
3. **Load into Registry** - Loads Solr documents into the registry

Designed for cron automation with comprehensive logging and email notifications.

---

## Wrapper Script Documentation

### Quick Start

#### Option 1: Using Config File (Recommended for Cron)

```bash
# 1. Copy and customize the example config
cp psa_sync_wrapper.env.example /path/to/secure/my-config.env
# Edit my-config.env with your paths and settings

# 2. Run with config file
./psa_sync_wrapper.sh --config /path/to/secure/my-config.env
```

#### Option 2: Source Environment Variables

```bash
# 1. Source your configuration
. /path/to/secure/my-config.env

# 2. Run the script
./psa_sync_wrapper.sh
```

**Important:** Do NOT commit configuration files to the repository. Store them in a secure location outside the repo.

### Configuration Best Practices

Follow these practices to prevent common mistakes and ensure reliable operation:

#### 1. Use Absolute Paths
Relative paths can cause unexpected behavior depending on working directory.

```bash
# Good
LOG_DIR="/var/log/psa-sync"

# Avoid - depends on where script is run from
LOG_DIR="./logs"
```

#### 2. Validate Configuration Before Production
Use dry-run mode to validate your configuration without executing:

```bash
# Test configuration
./psa_sync_wrapper.sh -c my-config.env --dry-run

# If validation passes, test with single step
./psa_sync_wrapper.sh -c my-config.env --download-labels
```

#### 3. Set Restrictive Permissions
Prevent accidental overwrites and protect configuration:

```bash
chmod 600 my-config.env  # Only owner can read/write
```

#### 4. Store Configs Outside Repository
Avoid accidental commits to version control:

```bash
# Store in system config directory
/etc/psa-sync/production.env

# Or in user directory
~/.config/psa-sync/config.env
```

#### 5. Verify Email Recipients
Check for typos in email addresses:

```bash
# Test email delivery works
echo "Test message" | mail -s "Test" "$EMAIL_RECIPIENTS"
```

#### 6. Verify Directory Paths
Ensure all required directories exist before running:

```bash
# Check directories exist
for dir in "$LOG_DIR" "$PSA_SYNC_DATA_DIR" "$EN_OPS_UTILS_HOME"; do
    [ -d "$dir" ] || echo "Error: Directory missing: $dir"
done
```

#### 7. Test Environment Setup
Verify all dependencies are available:

```bash
# Check Java
java -version

# Check Python
python --version

# Check conda (if using)
conda env list | grep my-env
```

### Usage Examples

```bash
# Validate configuration (dry-run mode)
./psa_sync_wrapper.sh -c my-config.env --dry-run

# Run all three steps (default, email notification sent)
./psa_sync_wrapper.sh -c my-config.env

# Run only the download step (email notification sent)
./psa_sync_wrapper.sh -c my-config.env --download-labels

# Run download only WITHOUT email (for testing)
./psa_sync_wrapper.sh -c my-config.env -n --download-labels

# Run harvest and load steps (auto-sorted to correct order: create docs → load)
./psa_sync_wrapper.sh -c my-config.env --load --create-docs

# Get help
./psa_sync_wrapper.sh --help
```

### Command-Line Options

| Option | Description |
|--------|-------------|
| `-c, --config FILE` | Load environment variables from config file |
| `--download-labels` | Execute step 1: Download PSA labels |
| `--create-docs` | Execute step 2: Run Harvest to create Solr docs |
| `--load` | Execute step 3: Load Solr docs into registry |
| `-n, --no-email` | Suppress email notification (default: always sent) |
| `--dry-run` | Validate configuration and show what would run without executing |
| `-h, --help` | Show help message |

**Note:** If no steps are specified, all three steps run by default.

### Configuration

#### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `LOG_DIR` | Directory for log files |
| `PSA_SYNC_DATA_DIR` | Directory for PSA label data |
| `EN_OPS_UTILS_HOME` | Path to en-ops-utils repository |
| `HARVEST_SOLR_HOME` | Path to harvest-solr installation |
| `HARVEST_SOLR_CONF_HOME` | Path to harvest config directory |
| `PDS4_SOLR_DOC_HOME` | Path for Solr document output |
| `REGISTRY_MGR_SOLR_HOME` | Path to registry-manager-solr installation |
| `EMAIL_RECIPIENTS` | Email addresses for notifications |

#### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOSTNAME_LABEL` | `$(hostname)` | Hostname label for email subject |
| `CONDA_ENV` | None | Conda environment name (uses system python if not set) |
| `CONDA_HOME` | Auto-detected | Conda installation path (tries standard locations) |
| `JAVA_HOME` | System java | Java installation path (uses system java if not set) |
| `HARVEST_CONFIG_FILE` | `harvest-policy-ipda.xml` | Harvest policy file name |
| `PSA_SYNC_EXCLUDES` | `nasa/pds` | Exclusion pattern for pds-sync-api |
| `JAVA_TOOL_OPTIONS` | `-Xms2g -Xmx8g` | JVM memory options |

### Email Notifications

Email notifications are **always sent by default** for any step combination (success or failure).

This ensures you're always notified when automated jobs complete, regardless of which steps are executed.

**To suppress email notifications** (e.g., during testing):
```bash
./psa_sync_wrapper.sh -n --download-labels
```

The email includes:
- Which steps were executed
- Success/failure status
- Harvest summary (if step 2 ran)
- Error messages
- Log file location

### Logging

All output is logged to timestamped files in `$LOG_DIR`:
- Format: `psa_sync_YYYYMMDD_HHMMSS.log`
- Output is both displayed to console and written to log file
- Skipped steps are logged with "(USER SKIPPED)" markers

### Automation with Cron

The wrapper script is designed for cron automation. You can configure it to run at scheduled intervals.

#### Option 1: Using --config Flag (Recommended)

```cron
# Run daily at 2 AM
0 2 * * * /path/to/psa_sync_wrapper.sh -c /path/to/secure/my-config.env
```

#### Option 2: Source Environment First

```cron
# Run daily at 2 AM
0 2 * * * . /path/to/secure/my-config.env && /path/to/psa_sync_wrapper.sh
```

### Deployment Checklist

#### Configuration
- [ ] Copy and customize `psa_sync_wrapper.env.example`
- [ ] Store configuration file in secure location (NOT in repo)
- [ ] Set restrictive permissions: `chmod 600 my-config.env`
- [ ] Use absolute paths for all directories in config
- [ ] Verify all required environment variables are set

#### Validation
- [ ] **Run dry-run mode:** `./psa_sync_wrapper.sh -c my-config.env --dry-run`
- [ ] Verify Java is available: `java -version`
- [ ] Verify Python is available: `python --version`
- [ ] Test email delivery: `echo "Test" | mail -s "Test" "$EMAIL_RECIPIENTS"`
- [ ] If using conda, verify environment exists: `conda env list`

#### Testing
- [ ] **Test with single step first:** `./psa_sync_wrapper.sh -c my-config.env --download-labels`
- [ ] Verify logs are written to `$LOG_DIR`
- [ ] Verify email notification received
- [ ] Run all three steps: `./psa_sync_wrapper.sh -c my-config.env`

#### Production Deployment
- [ ] Test with manual run before scheduling cron
- [ ] Monitor first few cron runs
- [ ] Set up log rotation if needed

### Troubleshooting

#### "Missing required environment variables"
**Cause:** Required environment variables not set.

**Solution:**
- Use `-c` flag: `./psa_sync_wrapper.sh -c my-config.env`
- Or source config: `source my-config.env && ./psa_sync_wrapper.sh`

#### "Config file not found"
**Cause:** Invalid path provided to `-c` flag.

**Solution:** Verify the config file path is correct and accessible.

#### Conda activation fails
**Cause:** `CONDA_ENV` points to invalid environment.

**Solution:**
- Verify conda environment exists: `conda env list`
- Or unset `CONDA_ENV` to skip conda activation

#### Java not found
**Cause:** Java not in PATH and `JAVA_HOME` not set.

**Solution:**
- Set `JAVA_HOME` in config file to Java installation path
- Or ensure `java` is in your system PATH

#### Step 2 validation fails (labels ≠ docs)
**Cause:** Harvest failed to process some labels.

**Solution:**
- Check harvest logs for errors
- Verify harvest config file is correct
- Ensure sufficient Java heap memory (`JAVA_TOOL_OPTIONS`)

### Step Execution Logic

- Steps execute in ascending order (1 → 2 → 3) regardless of input order
- Each step must succeed before the next begins
- Step 2 includes validation: registered labels must equal created Solr docs
- Skipped steps are logged but don't affect execution
- Use individual steps for debugging or partial updates

### Development & Maintenance

#### Code Quality
The wrapper script follows shell scripting best practices:
- Uses `set -euo pipefail` for fail-fast behavior
- Constants for magic numbers
- Comprehensive input validation
- Clear error messages

#### Running Shellcheck
Before committing changes to the wrapper script, run shellcheck:

```bash
shellcheck psa_sync_wrapper.sh
```

Address all warnings and errors. The script should pass shellcheck with no issues.

#### Testing Changes
1. Test with dry-run mode: `./psa_sync_wrapper.sh -c test.env --dry-run`
2. Test individual steps before running full pipeline
3. Verify email notifications work as expected
4. Test error handling by providing invalid configurations

---

## File Reference

| File | Purpose |
|------|---------|
| `pds_sync_api.py` | Python module for downloading PSA labels |
| `psa_sync_wrapper.sh` | Bash wrapper for complete sync workflow |
| `psa_sync_wrapper.env.example` | Template configuration file |
| `README.md` | This file |

## See Also

- [Main repository README](../../../../README.md) - Setup and development instructions
- [CLAUDE.md](../../../../CLAUDE.md) - Claude Code guidance for this repository
