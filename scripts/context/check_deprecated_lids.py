#!/usr/bin/env python3
"""
Script to verify that deprecated PDS4 context product LIDs have been removed
from the PDS Search API.

For each LID in the first column of the deprecated LIDs CSV, queries:
    GET https://pds.mcp.nasa.gov/api/search/1/products/{lid}

A 404 response means the LID was correctly removed. Any other response
(e.g. 200) means the LID is still present in the API and is a failure.

CSV format:
    # comment lines are ignored
    deprecatedLID,dateOfReplacement,replacementLID
    urn:nasa:pds:context:instrument:cida.con,2021-02-24,...

Usage:
    python check_deprecated_lids.py [csv_file_path]

    If no path is specified, defaults to
    "../../data/pds4/context-pds4/miscellaneous/lids_deprecated.csv"

Returns:
    0 if all deprecated LIDs return 404, 1 if any are still present in the API
"""

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import List, Tuple

import requests

API_BASE_URL = "https://pds.mcp.nasa.gov/api/search/1/products"
DEFAULT_CSV = (
    Path(__file__).parent.parent.parent
    / "data" / "pds4" / "context-pds4" / "miscellaneous" / "lids_deprecated.csv"
)
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.1  # seconds between requests


def load_deprecated_lids(csv_path: Path) -> List[str]:
    """
    Parse the deprecated LIDs CSV and return a list of deprecated LIDs.

    Skips comment lines (starting with '#') and the header row.
    """
    lids = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            row = next(csv.reader([stripped]))
            if row[0].lower() == "deprecatedlid":
                continue
            if row[0].startswith("urn:"):
                lids.append(row[0].strip())
    return lids


def query_api(lid: str, session: requests.Session) -> Tuple[int, str]:
    """
    Query the PDS Search API for a single LID.

    Returns:
        Tuple of (http_status_code, error_message).
        status_code is -1 and error_message is set on network errors.
    """
    url = f"{API_BASE_URL}/{lid}"
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        return response.status_code, ""
    except requests.exceptions.Timeout:
        return -1, f"request timed out after {REQUEST_TIMEOUT}s"
    except requests.exceptions.ConnectionError as e:
        return -1, f"connection error: {e}"
    except requests.exceptions.RequestException as e:
        return -1, f"request error: {e}"


def check_deprecated_lids(
    csv_path: Path, verbose: bool = False
) -> Tuple[bool, List[Tuple[str, int, str]]]:
    """
    Check that all deprecated LIDs return 404 from the PDS Search API.

    Returns:
        Tuple of (has_failures, failures) where failures is a list of
        (lid, status_code, error_message) for non-404 or network-error results
    """
    lids = load_deprecated_lids(csv_path)
    failures = []

    print(f"Checking {len(lids)} deprecated LIDs against {API_BASE_URL}...")

    with requests.Session() as session:
        for i, lid in enumerate(lids, 1):
            status_code, error = query_api(lid, session)

            if error:
                print(f"  Warning [{i}/{len(lids)}]: {lid} — {error}")
                failures.append((lid, status_code, error))
            elif status_code == 404:
                if verbose:
                    print(f"  ✅ [{i}/{len(lids)}] {lid} → 404")
            else:
                print(f"  ❌ [{i}/{len(lids)}] {lid} → {status_code} (expected 404)")
                failures.append((lid, status_code, ""))

            if i < len(lids):
                time.sleep(REQUEST_DELAY)

    return len(failures) > 0, failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify deprecated PDS4 context LIDs have been removed from the PDS Search API."
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=str(DEFAULT_CSV),
        help="Path to the deprecated LIDs CSV file (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show all LIDs checked, not just failures",
    )

    args = parser.parse_args()
    csv_path = Path(args.csv_file)

    if not csv_path.exists():
        print(f"Error: File '{csv_path}' not found.")
        return 1

    if not csv_path.is_file():
        print(f"Error: '{csv_path}' is not a file.")
        return 1

    try:
        has_failures, failures = check_deprecated_lids(csv_path, args.verbose)

        if has_failures:
            print("\n❌ DEPRECATED LIDS STILL PRESENT IN API:")
            print("=" * 60)
            for lid, status_code, error in failures:
                print(f"\n  LID:    {lid}")
                if error:
                    print(f"  Error:  {error}")
                else:
                    print(f"  Status: {status_code} (expected 404)")
            print(f"\nTotal failures: {len(failures)}")
            return 1

        lids = load_deprecated_lids(csv_path)
        print(f"\n✅ All {len(lids)} deprecated LIDs correctly return 404!")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
