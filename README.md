# NASA PDS Engineering Node Operations

This repository houses the automation and helper scripts for Operations tasks.

---

## Automation Scripts

This repo also contains operational scripts used by the EN team to fulfill the above requests. See [CLAUDE.md](CLAUDE.md) for developer setup instructions.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate

# Install options (choose based on what you need):
pip install -e .                  # packaged code only (pds-sync-api)
pip install -e ".[dev]"           # + development tools (pytest, black, flake8, etc.)
pip install -e ".[scripts]"       # + legacy script dependencies (github3.py, pystache, etc.)
pip install -r requirements.txt   # equivalent to -e ".[scripts]"
pip install -e ".[dev,scripts]"   # everything (recommended for contributors)

# Install pre-commit hooks (recommended):
pre-commit install
pre-commit install --hook-type pre-push
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
| `scripts/ldds/list_open_release_prs.py` | Lists open PRs created by `prep_for_ldd_release.sh` for a given PDS4 release version |
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

### list_open_release_prs.py

Lists all open pull requests created by `prep_for_ldd_release.sh` for a given PDS4 release version. Useful for tracking LDD release progress and quickly accessing PRs that need review.

```bash
# List all open PRs for a release (detailed format with review status)
scripts/ldds/list_open_release_prs.py 1.26.0.0 --token $GITHUB_TOKEN

# Summary table format
scripts/ldds/list_open_release_prs.py 1.26.0.0 --format summary --token $GITHUB_TOKEN

# Simple format with URLs and repo names for easy copy/paste
scripts/ldds/list_open_release_prs.py 1.26.0.0 --format simple --token $GITHUB_TOKEN

# Check a specific repo only
scripts/ldds/list_open_release_prs.py 1.26.0.0 --repo ldd-img --token $GITHUB_TOKEN
```

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

### Secret Detection

This repo uses [`detect-secrets`](https://github.com/Yelp/detect-secrets) to prevent credentials from being committed. The pre-commit hook runs automatically after `pre-commit install` (see Setup above).

**Per-repo exclusions** live in [`.detect-secrets-ignore`](.detect-secrets-ignore) — one regex per line, `#` for comments. Add paths or filename patterns there when a file legitimately contains placeholder/example values that trigger false positives.

**Workflow:**

```bash
# Re-scan after adding new files or updating .detect-secrets-ignore
scripts/detect_secrets_baseline.sh scan

# Interactively audit flagged secrets (mark each as real or false positive)
scripts/detect_secrets_baseline.sh audit

# Manual check (same as the pre-commit hook)
scripts/detect_secrets_baseline.sh
```
