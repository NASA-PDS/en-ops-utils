# NASA PDS Engineering Node Operations

This repository houses the automation and helper scripts for Operations tasks.

---

## Automation Scripts

This repo also contains operational scripts used by the EN team to fulfill the above requests. See [CLAUDE.md](CLAUDE.md) for developer setup instructions.

### Setup

```bash
python3 -m venv $HOME/.virtualenvs/pdsen-ops
source $HOME/.virtualenvs/pdsen-ops/bin/activate
pip3 install --requirement requirements.txt
```

Required environment variables:
- `GITHUB_TOKEN` — GitHub personal access token with repo access
- `PDSEN_OPS_TOKEN` — Used by shell scripts targeting LDD repos
- `EMAIL_PASSWORD` — For NSSDCA status email notifications (pds-operator@jpl.nasa.gov)

### Key Scripts

| Script | Purpose |
|--------|---------|
| `bin/ldds/ldd-corral.py` | Generates the [PDS4 data dictionaries web page](https://pds.nasa.gov/datastandards/dictionaries/index.shtml) and stages all Discipline LDD releases |
| `bin/ldds/update-ldd-actions.py` | Propagates GitHub Actions workflows from `ldd-template` to all Discipline LDD repos |
| `bin/ldds/prep_for_ldd_release.sh` | Creates release branches in all Discipline LDD repos for a given PDS4 IM version |
| `bin/repos/repo-corral.py` | Bulk-updates repos in the `NASA-PDS` org (e.g., propagating template changes) |
| `bin/pds-stats.py` | Fetches GitHub release download metrics for PDS software tools |
| `bin/context/check_duplicate_identifiers.py` | Scans a directory of PDS4 context XML files for duplicate `logical_identifier` values |
| `bin/portal/pds-sync-api.py` | Downloads ESA PSA product XML files from the PDS search API for harvest |

### ldd-corral.py

Autonomously generates the PDS4 data dictionaries web page for each PDS4 Build, and downloads and stages all Discipline LDDs from their GitHub repos.

**Configuration** — `conf/ldds/config.yml` maps GitHub repo names to display name/description overrides for the generated web page.

```bash
source $HOME/.virtualenvs/pdsen-ops/bin/activate
ldd-corral.py --pds4_version 1.15.0.0 --token $GITHUB_TOKEN
```

Default outputs: web page at `/tmp/ldd-release/dd-summary.html`, LDD files under `/tmp/ldd-release/pds4/`.

### pds-stats.py

```bash
bin/pds-stats.py --github_repos validate mi-label transform --token $GITHUB_TOKEN
```

### pds-sync-api.py

Downloads ESA PSA product XML files from the PDS search API and generates a harvest config:

```bash
bin/portal/pds-sync-api.py --node-name psa --download-path download/
```

### NSSDCA Status Checker

Monitors PDS4 package status in NSSDCA, updates GitHub issues with status comments, sends failure notifications to pds-operator@jpl.nasa.gov, and closes issues when all packages are ingested. Reads/writes `nssdca_status.csv` with columns `github_issue_number`, `identifier`, `nssdca_status`.

### Context Duplicate Identifier Checker

Scans PDS4 context XML files for duplicate `logical_identifier` values:

```bash
python3 bin/context/check_duplicate_identifiers.py [path/to/xml/files] [--verbose]
```

Exit code `0` = no duplicates; `1` = duplicates found or error.

---

## Development

```bash
pytest test/ -v       # run tests
black bin/            # format
flake8 bin/           # lint
mypy bin/context/check_duplicate_identifiers.py  # type check
```
