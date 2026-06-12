# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Operational scripts and utilities for the [PDS Engineering Node (EN)](https://nasa-pds.github.io/). Scripts automate tasks across two primary GitHub organizations: `NASA-PDS` (main PDS repos) and `pds-data-dictionaries` (Discipline LDD repos).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"          # installs packaged code + dev tools
pip install -r requirements.txt  # additional deps for legacy scripts
```

Required environment variables (set before running most scripts):
- `GITHUB_TOKEN` — GitHub personal access token with repo access
- `PDSEN_OPS_TOKEN` — Used by shell scripts targeting LDD repos
- `EMAIL_PASSWORD` — For NSSDCA status email notifications (pds-operator@jpl.nasa.gov)

## Commands

```bash
# Run all tests
pytest --verbose tests/ test/

# Run tox (full matrix + lint)
tox

# Run a single test file
pytest test/context/test_check_duplicate_identifiers.py -v

# Format packaged code
black src/

# Lint packaged code
flake8 src/

# Type-check packaged code
mypy src/
```

## Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/ldds/ldd-corral.py` | Generates the PDS4 data dictionaries web page and stages all Discipline LDD releases; outputs to `/data/tmp/ldd-release/` |
| `scripts/ldds/update-ldd-actions.py` | Propagates GitHub Actions CI/CD workflow files from `ldd-template` to all Discipline LDD repos in `pds-data-dictionaries` org |
| `scripts/ldds/prep_for_ldd_release.sh` | Creates release branches in all Discipline LDD repos for a given PDS4 IM version |
| `scripts/repos/repo-corral.py` | Bulk-updates repos in the `NASA-PDS` org (e.g., propagating template changes) |
| `scripts/repos/update_templates.sh` / `update_action.sh` | Shell helpers for repo template propagation |
| `scripts/pds-stats.py` | Fetches GitHub release download metrics for PDS software tools |
| `scripts/context/check_duplicate_identifiers.py` | Scans a directory of PDS4 context XML files for duplicate `logical_identifier` values |
| `scripts/portal/pds-sync-api.py` | Thin wrapper — logic lives in `src/pds/en_ops_utils/portal/pds_sync_api.py`; after install use the `pds-sync-api` console script |
| `scripts/sitemap/ds-view.py` | Sitemap/data set view utilities |
| `scripts/solr/deprecated_solr_registry_pds3_export.py` | Deprecated Solr export for PDS3 registry |

## LDD Configuration

`conf/ldds/config.yml` — Controls which Discipline LDDs are included in a release. Each entry maps a GitHub repo name (e.g., `ldd-img`) to an optional `name` override and `description` for the generated web page. Repos not listed here but present in the `pds-data-dictionaries` org are still included unless they appear in each script's `SKIP_REPOS` list.

## Architecture

The repo has a dual structure that will converge as scripts are migrated one by one:

**Packaged code** (`src/pds/en_ops_utils/`) — scripts that have been converted to a proper `pds.en_ops_utils` Python package. Install with `pip install -e ".[dev]"`. Entry points are declared in `setup.cfg` under `[options.entry_points]`. Tests live under `tests/pds/en_ops_utils/` mirroring the package layout.

**Legacy scripts** (`scripts/`) — standalone CLI tools not yet packaged. Each imports directly from third-party packages (`github3`, `lxml`, `PyGithub`, `pystache`, `pds.ldd_manager`). Install deps with `pip install -r requirements.txt`. Tests for these live under `test/` and use `sys.path` manipulation to import directly from `scripts/`.

The `ldd-corral.py` script is the most complex legacy script: it uses `github3` to enumerate repos, `lxml` to parse IngestLDD XML, `pystache` templates to render the output HTML, and `lasso` to clone/checkout branches.

**Packaging files**: `setup.cfg` (metadata + deps + entry points), `pyproject.toml` (build system + black config), `tox.ini` (test matrix + lint env), `MANIFEST.in` (package data).
