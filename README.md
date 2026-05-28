# NASA PDS Engineering Node Operations

This repository is the central issue tracker for [PDS Engineering Node (EN)](https://nasa-pds.github.io/) operations. Discipline Nodes and data providers use it to request EN-managed actions across the PDS system — data releases, DOI management, LID/LDD requests, NSSDCA deliveries, and more. It also houses the automation scripts that fulfill many of these requests.

## Submitting a Request

Use the [GitHub Issues](https://github.com/NASA-PDS/operations/issues/new/choose) page to open a new request. Select the appropriate template:

| Template | Purpose |
|----------|---------|
| **[data-release] PDS Data Release** | Request a PDS4 bundle or PDS3 data set release |
| **[data-release] Lead Node Announcement** | Provide release announcement text for a data release |
| **[doi] Reserve a DOI** | Reserve a DOI while preparing PDS4 labels prior to release |
| **[doi] Update a DOI** | Update metadata for an existing DOI |
| **[lid-request] Reserve PDS4 LID** | Submit a proposed PDS4 Logical Identifier (LID) for approval |
| **[ldd-request] Initialize New PDS LDD** | Request creation of a new PDS4 Local Data Dictionary |
| **[ldd-request] PDS LDD Release** | Request an off-nominal LDD release |
| **[nssdca-delivery] PDS4 NSSDCA Delivery** | Submit PDS Deep Archive packages for delivery to NSSDCA |
| **[subscription-service] New Subscription Item** | Add a mission/instrument to the PDS subscription service |
| **[deploy-system-build]** | Trigger a PDS system build deployment |

For general questions or problems not covered by a template, email **pds-operator@jpl.nasa.gov**.

---

## Automation Scripts

This repo also contains operational scripts used by the EN team to fulfill the above requests. See [CLAUDE.md](CLAUDE.md) for developer setup instructions.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"          # packaged scripts (pds-sync-api, etc.)
pip install -r requirements.txt  # legacy scripts not yet packaged
```

Required environment variables:
- `GITHUB_TOKEN` — GitHub personal access token with repo access
- `PDSEN_OPS_TOKEN` — Used by shell scripts targeting LDD repos
- `EMAIL_PASSWORD` — For NSSDCA status email notifications (pds-operator@jpl.nasa.gov)

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/ldds/ldd-corral.py` | Generates the [PDS4 data dictionaries web page](https://pds.nasa.gov/datastandards/dictionaries/index.shtml) and stages all Discipline LDD releases |
| `scripts/ldds/update-ldd-actions.py` | Propagates GitHub Actions workflows from `ldd-template` to all Discipline LDD repos |
| `scripts/ldds/prep_for_ldd_release.sh` | Creates release branches in all Discipline LDD repos for a given PDS4 IM version |
| `scripts/repos/repo-corral.py` | Bulk-updates repos in the `NASA-PDS` org (e.g., propagating template changes) |
| `scripts/pds-stats.py` | Fetches GitHub release download metrics for PDS software tools |
| `scripts/context/check_duplicate_identifiers.py` | Scans a directory of PDS4 context XML files for duplicate `logical_identifier` values |
| `scripts/portal/pds-sync-api.py` | Downloads ESA PSA product XML files from the PDS search API for harvest |

### ldd-corral.py

Autonomously generates the PDS4 data dictionaries web page for each PDS4 Build, and downloads and stages all Discipline LDDs from their GitHub repos.

**Configuration** — `conf/ldds/config.yml` maps GitHub repo names to display name/description overrides for the generated web page.

```bash
source .venv/bin/activate
scripts/ldds/ldd-corral.py --pds4_version 1.15.0.0 --token $GITHUB_TOKEN
```

Default outputs: web page at `/tmp/ldd-release/dd-summary.html`, LDD files under `/tmp/ldd-release/pds4/`.

### pds-stats.py

```bash
scripts/pds-stats.py --github_repos validate mi-label transform --token $GITHUB_TOKEN
```

### pds-sync-api

Downloads ESA PSA product XML files from the PDS search API and generates a harvest config. Installed as a console script via `pip install -e .`:

```bash
pds-sync-api --node-name psa --download-path download/
# or run the script directly:
scripts/portal/pds-sync-api.py --node-name psa --download-path download/
```

### NSSDCA Status Checker

Monitors PDS4 package status in NSSDCA, updates GitHub issues with status comments, sends failure notifications to pds-operator@jpl.nasa.gov, and closes issues when all packages are ingested. Reads/writes `nssdca_status.csv` with columns `github_issue_number`, `identifier`, `nssdca_status`.

### Context Duplicate Identifier Checker

Scans PDS4 context XML files for duplicate `logical_identifier` values:

```bash
python3 scripts/context/check_duplicate_identifiers.py [path/to/xml/files] [--verbose]
```

Exit code `0` = no duplicates; `1` = duplicates found or error.

---

## Development

```bash
pytest tests/ test/ -v   # run all tests
tox                       # run full test matrix + lint
black src/                # format packaged code
flake8 src/               # lint packaged code
mypy src/                 # type-check packaged code
```
