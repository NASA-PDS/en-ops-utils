# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Operational scripts and utilities for the [PDS Engineering Node (EN)](https://nasa-pds.github.io/). Scripts automate tasks across two primary GitHub organizations: `NASA-PDS` (main PDS repos) and `pds-data-dictionaries` (Discipline LDD repos).

## Setup

```bash
python3 -m venv $HOME/.virtualenvs/pdsen-ops
source $HOME/.virtualenvs/pdsen-ops/bin/activate
pip3 install --requirement requirements.txt
```

Required environment variables (set before running most scripts):
- `GITHUB_TOKEN` — GitHub personal access token with repo access
- `PDSEN_OPS_TOKEN` — Used by shell scripts targeting LDD repos
- `EMAIL_PASSWORD` — For NSSDCA status email notifications (pds-operator@jpl.nasa.gov)

## Commands

```bash
# Run tests
pytest test/ -v

# Run a single test file
pytest test/context/test_check_duplicate_identifiers.py -v

# Format code
black bin/

# Lint
flake8 bin/

# Type checking
mypy bin/context/check_duplicate_identifiers.py
```

## Key Scripts

| Script | Purpose |
|--------|---------|
| `bin/ldds/ldd-corral.py` | Generates the PDS4 data dictionaries web page and stages all Discipline LDD releases; outputs to `/data/tmp/ldd-release/` |
| `bin/ldds/update-ldd-actions.py` | Propagates GitHub Actions CI/CD workflow files from `ldd-template` to all Discipline LDD repos in `pds-data-dictionaries` org |
| `bin/ldds/prep_for_ldd_release.sh` | Creates release branches in all Discipline LDD repos for a given PDS4 IM version |
| `bin/repos/repo-corral.py` | Bulk-updates repos in the `NASA-PDS` org (e.g., propagating template changes) |
| `bin/repos/update_templates.sh` / `update_action.sh` | Shell helpers for repo template propagation |
| `bin/pds-stats.py` | Fetches GitHub release download metrics for PDS software tools |
| `bin/context/check_duplicate_identifiers.py` | Scans a directory of PDS4 context XML files for duplicate `logical_identifier` values |
| `bin/portal/pds-sync-api.py` | Downloads ESA PSA product XML files from the PDS search API for harvest |
| `bin/sitemap/ds-view.py` | Sitemap/data set view utilities |
| `bin/solr/deprecated_solr_registry_pds3_export.py` | Deprecated Solr export for PDS3 registry |

## LDD Configuration

`conf/ldds/config.yml` — Controls which Discipline LDDs are included in a release. Each entry maps a GitHub repo name (e.g., `ldd-img`) to an optional `name` override and `description` for the generated web page. Repos not listed here but present in the `pds-data-dictionaries` org are still included unless they appear in each script's `SKIP_REPOS` list.

## Architecture

Scripts are standalone CLI tools with no shared internal library — each imports directly from third-party packages (`github3`, `lxml`, `PyGithub`, `pystache`, `pds.ldd_manager`). The `ldd-corral.py` script is the most complex: it uses `github3` to enumerate repos, `lxml` to parse IngestLDD XML, `pystache` templates to render the output HTML, and `lasso` to clone/checkout branches.

Tests live under `test/` and mirror the `bin/` structure. The test for `check_duplicate_identifiers.py` imports directly from `bin/context/` by manipulating `sys.path`.
