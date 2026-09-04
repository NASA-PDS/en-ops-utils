# Data Release Calendar (DRC) Management Tool

Operational script for updating the [PDS Data Release Calendar](https://pds.nasa.gov/datasearch/subscription-service/data-release-calendar.shtml) webpage and associated files.

**Single-operator tool** — This README provides everything needed for seamless operator handoff.

---

## Quick Start

```bash
# 1. Set required environment variable
export DRC_REPO_PATH="/path/to/NASA-PDS/portal-legacy"

# 2. Activate virtual environment (if using packaged install)
source .venv/bin/activate

# 3. Common operations
python scripts/drc/drc.py --create-excel              # Create/open today's Excel
python scripts/drc/drc.py --update-files              # Update HTML/JSON after Excel edits
```

---

## Table of Contents

- [Environment Setup](#environment-setup)
- [Workflows](#workflows)
  - [Monthly Update (Most Common)](#monthly-update-most-common)
  - [Creating Multiple Versions Same Day](#creating-multiple-versions-same-day)
  - [New Year Initialization](#new-year-initialization)
- [Command Reference](#command-reference)
- [Files Modified](#files-modified)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)

---

## Environment Setup

### Required Environment Variable

```bash
export DRC_REPO_PATH="/path/to/NASA-PDS/portal-legacy"
```

**Important:** This must point to your local clone of the `portal-legacy` repository where the calendar files live.

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) to persist:
```bash
echo 'export DRC_REPO_PATH="/path/to/portal-legacy"' >> ~/.zshrc
```

### Verify Setup

```bash
# Should show the path without error
python scripts/drc/drc.py --help
```

If you see `ERROR: Repository path not found`, the environment variable is not set correctly.

---

## Workflows

### Monthly Update (Most Common)

**Use case:** Update the calendar with new data release information.

```bash
# Step 1: Create/open Excel for today's date
python scripts/drc/drc.py --create-excel

# This will:
# - Find the most recent Excel file (up to today)
# - Copy it to create today's version (auto-incrementing if needed)
# - Open the Excel file in your default application
# - Open changelog.txt for you to document changes

# Step 2: Edit the Excel file
# - Update data release information in the appropriate year's worksheet
# - Save and close Excel

# Step 3: Update HTML and JSON files
python scripts/drc/drc.py --update-files

# This will:
# - Read the Excel you just edited
# - Generate updated JSON (data-release-calendar-YYYY.txt)
# - Update HTML with new Excel filename and "Last updated" date
```

**Result:** The webpage is updated with current data.

### Creating Multiple Versions Same Day

If you need to make corrections or updates on the same day:

```bash
# Explicitly specify version number
python scripts/drc/drc.py --create-excel --excel-version 2

# Interactive prompt lets you choose:
# - Use existing version (make changes to current file)
# - Increment version (create new version)

# Then update files as usual
python scripts/drc/drc.py --update-files
```

**Version numbering:** Files follow format `PDS_Data_Release_Calendar_YYYYMMDD_vN.xlsx`
- Same date, higher version = newer revision
- Script always finds the latest version for a given date

### New Year Initialization

**Use case:** Set up files for a new calendar year (e.g., 2027).

**Do this once in early December of the previous year.**

#### Part 1: Initialize Regular Files

```bash
# Creates new HTML and JSON for the year
python scripts/drc/drc.py --initialize-new --year 2027

# This will:
# - Copy most recent year's HTML → data-release-calendar-2027.shtml
# - Replace year references (except ROSES links)
# - Add ROSES placeholder for new year
# - Generate initial JSON for the year
```

**Manual step required:** Open the new HTML file and remove the previous year's ROSES link (keeps both years otherwise).

#### Part 2: Finalize Support Files

```bash
# Updates JavaScript and redirect HTML
python scripts/drc/drc.py --finish-new --year 2027

# This will:
# - Update js/drc.js end_year variable
# - Update data-release-calendar.shtml redirect to point to 2027
```

**Result:** The website now shows 2027 as the current year.

---

## Command Reference

### Create Excel

```bash
python scripts/drc/drc.py --create-excel [--excel-version VERSION]
```

**Options:**
- `--excel-version VERSION` — Specify version number (e.g., `2` for v2). Triggers interactive prompt if file exists.

**What it does:**
1. Finds most recent Excel file (up to today's date)
2. Determines target filename: `PDS_Data_Release_Calendar_YYYYMMDD_vN.xlsx`
3. Copies latest → target (if target doesn't exist)
4. Opens target in default application
5. Opens changelog.txt

### Update Files

```bash
python scripts/drc/drc.py --update-files
```

**What it does:**
1. Reads most recent Excel file
2. Generates JSON: `data-release-calendar-YYYY.txt`
3. Updates HTML: `data-release-calendar-YYYY.shtml`
   - Excel download link
   - "Last updated on [date]" text

### Initialize New Year

```bash
python scripts/drc/drc.py --initialize-new --year YYYY
```

**What it does:**
1. Copies latest HTML → `data-release-calendar-YYYY.shtml`
2. Replaces year references (preserves ROSES links)
3. Adds ROSES placeholder for new year
4. Generates initial JSON for new year

**Requirements:**
- Year must be after most recent HTML year
- Manual cleanup of old ROSES link required after

### Finalize New Year

```bash
python scripts/drc/drc.py --finish-new --year YYYY
```

**What it does:**
1. Updates `js/drc.js` with new `end_year`
2. Updates `data-release-calendar.shtml` redirect to new year

**Requirements:**
- Run after `--initialize-new`
- Only affects JavaScript and redirect

### Debug Mode

```bash
python scripts/drc/drc.py --debug [other options]
```

Enables verbose logging showing:
- Command-line arguments
- File paths being processed
- Excel row/column processing details

---

## Files Modified

All paths relative to `$DRC_REPO_PATH`:

### Excel Files
```
datasearch/subscription-service/PDS_Data_Release_Calendar_YYYYMMDD_vN.xlsx
```
- Spreadsheet with data release information
- Worksheets named by year (e.g., "2026", "2027")
- Columns: Primary Target, Mission, Instrument, Release #, Interval, Est Date, Actual Date, Link

### JSON Files
```
datasearch/subscription-service/data-release-calendar-YYYY.txt
```
- JSON representation of Excel data for the year
- Used by webpage JavaScript for interactive calendar

### HTML Files
```
datasearch/subscription-service/data-release-calendar-YYYY.shtml
datasearch/subscription-service/data-release-calendar.shtml (redirect)
```
- Year-specific calendar pages
- Redirect page that points to current year

### JavaScript
```
js/drc.js
```
- Calendar functionality
- Contains `end_year` variable for year range

### Changelog
```
datasearch/subscription-service/changelog.txt
```
- Manual change log (opened automatically with `--create-excel`)
- Document what you changed in each update

---

## Architecture

### Class Structure

```
DRCExcelFile (dataclass)
├── date: str           # YYYYMMDD
├── version: int        # Version number
├── path: Path          # Full file path
├── filename            # Property: generated filename
├── get_filename_pattern()    # Regex for parsing
├── get_filename_glob()       # Pattern for file search
├── get_html_link_pattern()   # Pattern for HTML updates
├── get_html_link()           # Generate HTML link
├── is_same_date()            # Compare dates
└── validate()                # Validate metadata

DRCService (business logic)
├── find_latest_excel()       # Find most recent file ≤ today
├── determine_target_excel()  # Decide which file to use/create
└── create_or_open_excel()    # Create or open Excel file
```

### Exception Hierarchy

```
DRCError (base)
├── ExcelFileNotFoundError
├── InvalidWorksheetError
├── InvalidYearError
├── HTMLFileNotFoundError
├── InvalidHTMLFilenameError
├── YearOrderError
└── MissingDateCellError
```

All exceptions provide detailed error messages with context.

### Design Principles

1. **Encapsulation** — `DRCExcelFile` owns all filename logic
2. **Code Reuse** — `update_file_with_regex()` eliminates duplication
3. **Proper Error Handling** — Custom exceptions, not `sys.exit()`
4. **Testability** — `DRCService` separates business logic from I/O

---

## Troubleshooting

### Error: Repository path not found

```
ERROR: Repository path not found: /path/to/default. Set DRC_REPO_PATH environment variable.
```

**Solution:** Set the environment variable to your `portal-legacy` clone:
```bash
export DRC_REPO_PATH="/Users/yourname/repos/portal-legacy"
```

### Error: No existing Excel files found

```
ExcelFileNotFoundError: No existing Excel files found up to today. Cannot proceed.
```

**Causes:**
- First time running (no Excel files exist)
- All existing Excel files are dated in the future

**Solution:** Create an initial Excel file manually or copy one from another location.

### Error: Worksheet "YYYY" not found

```
InvalidWorksheetError: Worksheet "2027" not found in PDS_Data_Release_Calendar_20261215_v1.xlsx.
Available worksheets: 2024, 2025, 2026
```

**Solution:** The Excel file doesn't have a worksheet for the requested year. Either:
- Use `--initialize-new` to create files for the new year
- Manually add the worksheet to the Excel file

### Error: Cell value is blank for DATE

```
MissingDateCellError: Cell value is blank for DATE in row 15 of PDS_Data_Release_Calendar_20261215_v1.xlsx.
Column F must contain a date.
```

**Solution:** Required date columns (F and G) cannot be empty. Fill in missing dates in the Excel file.

### Error: Requested year must be after most recent year

```
YearOrderError: Requested year 2026 must be after most recent year 2026.
```

**Solution:** When using `--initialize-new`, the year must be after the current year. If initializing 2027, ensure you're doing it when 2026 files already exist.

### Interactive Prompt: Version Already Exists

```
INFO: Excel for 20261215 v1 already exists. Proceed WITHOUT incrementing the version? (y/n)
```

**Response:**
- `y` — Use existing file (make changes to current version)
- `n` — Create new version (e.g., v2)

### Debug Output

Run with `--debug` to see detailed processing:
```bash
python scripts/drc/drc.py --debug --create-excel
```

Shows:
- Paths being searched
- Files found
- Excel rows/columns being processed
- Pattern matching details

---

## Best Practices

### 1. Document Changes

The script opens `changelog.txt` automatically. Always document:
- What changed (new missions, updated dates, corrections)
- Why it changed
- Date of update

### 2. Version Control

Commit changes to `portal-legacy` with descriptive messages:
```bash
cd $DRC_REPO_PATH
git add datasearch/subscription-service/
git commit -m "Update DRC: Added Mars 2020 Q3 release dates"
```

### 3. Verify Before Publishing

After running `--update-files`:
1. Check the HTML page locally or in staging
2. Verify JSON is valid (check the .txt file)
3. Confirm Excel link works
4. Check "Last updated" date

### 4. Backup Before New Year

Before running `--initialize-new`:
```bash
cd $DRC_REPO_PATH
git branch backup-2026-final
git push origin backup-2026-final
```

### 5. Test Changes

If unsure about an operation:
```bash
# Create a test branch
cd $DRC_REPO_PATH
git checkout -b test-drc-update

# Run script
python scripts/drc/drc.py [commands]

# Review changes
git diff

# If good, merge; if not, discard
git checkout main
git branch -D test-drc-update
```

---

## Migration Notes (for Future Refactoring)

This script is currently standalone in `scripts/drc/`. Per `CLAUDE.md`, the eventual goal is to migrate operational scripts to the packaged `pds.en_ops_utils` structure.

**Current structure:**
```
scripts/drc/drc.py              # Standalone script
```

**Future structure (when migrated):**
```
src/pds/en_ops_utils/drc/       # Package
├── __init__.py
├── cli.py                       # Command-line interface
├── service.py                   # DRCService class
├── models.py                    # DRCExcelFile dataclass
└── exceptions.py                # Custom exceptions

setup.cfg                        # Entry point: drc = pds.en_ops_utils.drc.cli:main
```

**Benefits of migration:**
- Proper package with `pip install`
- Easier testing (`pytest tests/pds/en_ops_utils/drc/`)
- Better dependency management
- Installed as console script: `drc --create-excel`

**Current script already structured for easy migration** — classes and functions are organized to move cleanly into a package.

---

## Support

**For questions or issues:**

1. Check [Troubleshooting](#troubleshooting) section above
2. Review error messages (now detailed with context)
3. Run with `--debug` for verbose output

**For bugs or feature requests:**
- File issue: https://github.com/NASA-PDS/en-ops-utils/issues
- Include `--debug` output if reporting a bug

---

## Version History

**v2.0** (2026-08-19) — Major refactoring
- Added `DRCExcelFile` dataclass for better encapsulation
- Added `DRCService` class for business logic separation
- Replaced `sys.exit()` with custom exception hierarchy
- Eliminated code duplication with helper functions
- Improved error messages with context
- Added comprehensive docstrings

**v1.0** (2023-2026) — Original `drc.py`
- Used locally by single operator for 3+ years
- Proven stable for production use
- Adapted for public repo integration
