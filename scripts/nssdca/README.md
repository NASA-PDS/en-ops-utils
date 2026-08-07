# NSSDCA Interface Scripts

Scripts for processing and managing NSSDCA (NASA Space Science Data Coordinated Archive) deep archive deliveries.

## Overview

The PDS Engineering Node delivers validated PDS4 data products to NSSDCA for long-term preservation. These scripts automate:
- Processing AIP (Archival Information Package) and SIP (Submission Information Package) deliveries
- Generating PDS4 collection inventories
- Monitoring NSSDCA ingestion status

All files are housed at https://pds.nasa.gov/data/pds4/manifests/.

## Workflow

### Standard Delivery Processing

#### NSSDCA Packages

1. **Node creates ticket** and provides Validate report and delivery package containing the AIP/SIP files (e.g., https://github.com/NASA-PDS/operations/issues/1377)
2. **EN Operator verifies** the node-provided Validate report. If requirements are met...
3. **EN Operator uploads the package** to `$NSSDCA_DELIVERIES_PATH/<ticket_number>/` on a machine that has write permissions to https://pds.nasa.gov/data/pds4/manifests/.
4. **Operator runs nssdca.py:** `% python3 nssdca.py <ticket_number>`
5. **Script (nssdca.py)** posts successfully validated packages to https://pds.nasa.gov/data/pds4/manifests/{YYYY} and generates a GitHub comment with logical identifiers (LIDs) of the delivered packages
6. **Operator copies comment** to GitHub issue to notify node
7. **NSSDCA picks up** the packages and begins archiving process

#### PDS4 Collection Inventories

**Weekly cron job (aip-count.py)** checks count of AIPs and, if count changed, generates updated PDS4 Collection inventories and posts them to https://pds.nasa.gov/data/pds4/manifests/inventory/


## Scripts Overview

### nssdca.py
**Purpose:** Process NSSDCA package(s) from a GitHub ticket (a ticket may contain one or more packages from a node).

```bash
# Standard: validate and post packages
python3 nssdca.py <ticket_number> -P

# Validate only (dry run before posting)
python3 nssdca.py <ticket_number> -v

# Debug mode (keeps backups, verbose output)
python3 nssdca.py <ticket_number> -P -D

# Force post without validation (emergency only)
python3 nssdca.py <ticket_number> -P -f
```

**Validates AIP/SIP packages and posts to** https://pds.nasa.gov/data/pds4/manifests/{YYYY}/

**Success output:**
- Packages posted to manifests directory
- GitHub comment with LIDs (copy to ticket)

**Error output:**
- Validate reports: `<label>-validate.txt` in ticket directory

<details>
<summary><i>Technical details (optional reference)</i></summary>

**Security features:** Path traversal prevention, zip bomb protection (max depth 3), safe file operations.

**Available options:**
- `-P, --Post` - Post validated sets for NSSDCA
- `-f, --force` - Use with -P to post without validation
- `-v, --validate` - Validate sets only
- `-l, --lid` - Extract logical identifiers
- `-m, --manifest-url` - Extract year from manifest URLs
- `-d, --date` - Update last modified dates
- `-p, --permissions` - Set file permissions to 664
- `-D, --Debug` - Enable debug mode (keeps backups, verbose output)

</details>

---

### aip-count.py
**Purpose:** Count AIPs and regenerate PDS4 Collection inventories when count changes. Runs automatically via weekly cron.

**Monitoring:** Check `/path/to/aip-count.log` for cron execution output.

<details>
<summary><i>Technical details (optional reference)</i></summary>

**Process flow:**
1. Counts all AIP XML files in https://pds.nasa.gov/data/pds4/manifests/
2. Compares with previous count from `aip-count.txt`
3. If changed → calls `makeCollection.py` → posts regenerated PDS4 Collection inventories to https://pds.nasa.gov/data/pds4/manifests/inventory/
4. Logs: `<timestamp> <count> [# v<version>]` to `aip-count.txt`
5. Cleans up old versions (keeps 2 most recent in local `inventory/` directory)

**Log file example** (`aip-count.txt`):
```
# Format: <timestamp> <count> [# v<version>]
20260806020001 1069  # v57.0
20260813020001 1069  # count unchanged, no action
20260820020001 1075  # v58.0
```

**Manual run (if needed):**
```bash
cd $NSSDCA_SCRIPTS_PATH
python3 aip-count.py
```

</details>

---

### inventory/makeCollection.py
**Purpose:** Generate versioned PDS4 Collection inventories (XML and CSV) from AIP files. Called automatically by `aip-count.py`.

**Output:** `Collection_product_aip_v*.xml/csv` and `Collection_product_sip_deep_archive_v*.xml/csv`

<details>
<summary><i>Technical details (optional reference)</i></summary>

**Process flow:**
1. Takes directory path as argument (provided by `aip-count.py`)
2. Recursively scans for PDS4 product labels
3. Groups products into PDS4 Collections (based on LID structure)
4. Handles duplicate LIDVIDs (keeps newest by filename version or mtime)
5. Compares with previous PDS4 Collection inventory → tracks added/dropped products
6. Generates PDS4-compliant Collection XML and CSV files
7. Uses SHA-256 checksums (FIPS-compliant)
8. Auto-increments version if content changed

**Manual run (rare):**
```bash
cd $NSSDCA_SCRIPTS_PATH/inventory/
python3 makeCollection.py $PDS4_MANIFESTS_PATH
```
</details>

---

---

## Setup (For New Operators)

<details>
<summary><b>Initial installation</b> <i>(one-time setup)</i></summary>

### Verify PDS Validate Tool
This should be the [latest version](https://github.com/NASA-PDS/validate/releases/latest) of Validate
```bash
validate -V
```

### Setup Repository and Virtual Environment

#### Clone Repository and Create Virtual Environment
For when the repository and virtual environment don't already exist in the workspace
```bash
cd /path/to/workspace
git clone https://github.com/NASA-PDS/en-ops-utils.git
cd en-ops-utils
conda create --name pdsen-ops
conda activate pdsen-ops
```

#### Update Repository and Activate Virtual Environment
For when the repository and virtual environment already exist in the workspace
```bash
cd /path/to/workspace
cd en-ops-utils
git pull origin HEAD
conda activate pdsen-ops
```

### Install Dependencies
Assuming you've setup the repository and virtual environment
```bash
pip install --editable ".[scripts]"       # Installs legacy script dependencies
```

### Environment Configuration
Add to `~/.bash_profile` (or `~/.bashrc` or `~/.zshrc`):
```bash
export PDS4_MANIFESTS_PATH=/path/to/manifests/                              # Maps to https://pds.nasa.gov/data/pds4/manifests/
export NSSDCA_SCRIPTS_PATH=/path/to/workspace/en-ops-utils/scripts/nssdca/ # This repo's nssdca directory
export NSSDCA_DELIVERIES_PATH=/path/to/deliveries/                          # Temporary working directory (not public)
```

Then run: `source ~/.bash_profile`

### Directory Setup
`PDS4_MANIFESTS_PATH` should already exist (the directory that maps to https://pds.nasa.gov/data/pds4/manifests/). `NSSDCA_SCRIPTS_PATH/inventory` should already exist from the repo
```bash
mkdir -p $NSSDCA_DELIVERIES_PATH
```

### Initialize Log
```bash
cd $NSSDCA_SCRIPTS_PATH
# Use 0 for the count to force initial inventory generation
echo "$(date +%Y%m%d%H%M%S) 0   # v0 - baseline" > $NSSDCA_SCRIPTS_PATH/aip-count.txt
```

### Setup Weekly Cron
```bash
# Create wrapper script
cat > /path/to/run-aip-count.sh << 'EOF'
#!/bin/bash
export PDS4_MANIFESTS_PATH=/path/to/manifests/
export NSSDCA_SCRIPTS_PATH=/path/to/workspace/en-ops-utils/scripts/nssdca/
export NSSDCA_DELIVERIES_PATH=/path/to/deliveries/
cd $NSSDCA_SCRIPTS_PATH
python3 aip-count.py
EOF
chmod +x /path/to/run-aip-count.sh

# Add to crontab (runs Monday 2 AM)
crontab -e
# Add: 0 2 * * 1 /path/to/run-aip-count.sh >> /path/to/aip-count.log 2>&1
```

**Monitor:** Check `/path/to/aip-count.log` weekly

</details>

## Troubleshooting

<details>
<summary><b>Common Issues</b> <i>(expand if you encounter errors)</i></summary>

### nssdca.py Errors

**"No such directory"**
- **Fix:** Create `$NSSDCA_DELIVERIES_PATH/<ticket_number>` directory first

**"Validation error(s)"**
- **Fix:** Check `<label>-validate.txt` in ticket directory, determine if EN bug or if node needs to correct package, and proceed accordingly

**"Path traversal detected"**
- **Fix:** Ticket directory name has invalid characters (use numeric IDs only)

### aip-count.py Issues

**Collections not regenerating**
- **Fix:** Reset baseline in `aip-count.txt`:
  ```bash
  echo "$(date +%Y%m%d%H%M%S) 0  # reset" > $NSSDCA_SCRIPTS_PATH/aip-count.txt
  ```

**"No collection files found to move"**
- **Check:** Review previous `makeCollection.py` output in cron log to determine why files weren't generated in local inventory directory

</details>

## References

- [NSSDCA Interface Process](https://pds-engineering.jpl.nasa.gov/content/nssdca_interface_process)
- [PDS Validate Tool](https://github.com/NASA-PDS/validate/releases/latest)
- [PDS4 Standards](https://pds.nasa.gov/datastandards/)

## Support

For issues or questions:
- GitHub Issues: https://github.com/NASA-PDS/en-ops-utils/issues
- PDS EN Operations: pds-operator@jpl.nasa.gov
