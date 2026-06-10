#!/usr/bin/env python3
"""
Script to verify that deprecated PDS4 context product LIDs have been removed
from the PDS Search API and the PDS Solr registry.

For each LID in the first column of the deprecated LIDs CSV, queries:
    GET https://pds.mcp.nasa.gov/api/search/1/products/{lid}
    GET https://pds.nasa.gov/services/search/search?wt=json&q=*:*&fq=lid:"{lid}"&rows=0

A 404 REST API response and a Solr numFound of 0 mean the LID was correctly
removed. Any other result means the LID is still present and is a failure.

CSV format:
    # comment lines are ignored
    deprecatedLID,dateOfReplacement,replacementLID
    urn:nasa:pds:context:instrument:cida.con,2021-02-24,...

Usage:
    python check_deprecated_lids.py [csv_file_path]

    If no path is specified, defaults to
    "../../data/pds4/context-pds4/miscellaneous/lids_deprecated.csv"

Returns:
    0 if all deprecated LIDs are absent from both APIs, 1 if any are still present
"""

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import List, Tuple

import requests

API_BASE_URL = "https://pds.mcp.nasa.gov/api/search/1/products"
SOLR_SEARCH_URL = "https://pds.nasa.gov/services/search/search"
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


def query_solr(lid: str, session: requests.Session) -> Tuple[int, str]:
    """
    Query the PDS Solr registry for a single LID.

    Returns:
        Tuple of (num_found, error_message).
        num_found is -1 and error_message is set on network/parse errors.
    """
    params = {"wt": "json", "q": "*:*", "fq": f'lid:"{lid}"', "rows": 0}
    try:
        response = session.get(SOLR_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data["response"]["numFound"], ""
    except requests.exceptions.Timeout:
        return -1, f"request timed out after {REQUEST_TIMEOUT}s"
    except requests.exceptions.ConnectionError as e:
        return -1, f"connection error: {e}"
    except requests.exceptions.HTTPError as e:
        return -1, f"HTTP error: {e}"
    except ValueError as e:
        return -1, f"response parse error: {e}"
    except KeyError as e:
        return -1, f"unexpected response structure, missing key: {e}"
    except requests.exceptions.RequestException as e:
        return -1, f"request error: {e}"


def check_deprecated_lids(
    csv_path: Path, verbose: bool = False
) -> Tuple[bool, List[Tuple[str, int, str]], List[Tuple[str, int, str]]]:
    """
    Check that all deprecated LIDs return 404 from the PDS Search API and
    have numFound == 0 in the PDS Solr registry.

    Returns:
        Tuple of (has_failures, api_failures, solr_failures) where each
        failures list contains (lid, code_or_count, error_message).
    """
    lids = load_deprecated_lids(csv_path)
    api_failures: List[Tuple[str, int, str]] = []
    solr_failures: List[Tuple[str, int, str]] = []

    print(f"Checking {len(lids)} deprecated LIDs against REST API and Solr registry...")

    with requests.Session() as session:
        for i, lid in enumerate(lids, 1):
            status_code, api_error = query_api(lid, session)
            if api_error:
                print(f"  Warning [API {i}/{len(lids)}]: {lid} — {api_error}")
                api_failures.append((lid, status_code, api_error))
            elif status_code == 404:
                if verbose:
                    print(f"  ✅ [API {i}/{len(lids)}] {lid} → 404")
            else:
                print(f"  ❌ [API {i}/{len(lids)}] {lid} → {status_code} (expected 404)")
                api_failures.append((lid, status_code, ""))

            num_found, solr_error = query_solr(lid, session)
            if solr_error:
                print(f"  Warning [Solr {i}/{len(lids)}]: {lid} — {solr_error}")
                solr_failures.append((lid, num_found, solr_error))
            elif num_found == 0:
                if verbose:
                    print(f"  ✅ [Solr {i}/{len(lids)}] {lid} → 0 found")
            else:
                print(f"  ❌ [Solr {i}/{len(lids)}] {lid} → {num_found} document(s) found (expected 0)")
                solr_failures.append((lid, num_found, ""))

            if i < len(lids):
                time.sleep(REQUEST_DELAY)

    return len(api_failures) > 0 or len(solr_failures) > 0, api_failures, solr_failures


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
        has_failures, api_failures, solr_failures = check_deprecated_lids(csv_path, args.verbose)

        if api_failures:
            print("\n❌ DEPRECATED LIDS STILL PRESENT IN REST API:")
            print("=" * 60)
            for lid, status_code, error in api_failures:
                print(f"\n  LID:    {lid}")
                if error:
                    print(f"  Error:  {error}")
                else:
                    print(f"  Status: {status_code} (expected 404)")
            print(f"\nTotal REST API failures: {len(api_failures)}")

        if solr_failures:
            print("\n❌ DEPRECATED LIDS STILL PRESENT IN SOLR REGISTRY:")
            print("=" * 60)
            for lid, num_found, error in solr_failures:
                print(f"\n  LID:    {lid}")
                if error:
                    print(f"  Error:  {error}")
                else:
                    print(f"  Found:  {num_found} document(s) (expected 0)")
            print(f"\nTotal Solr failures: {len(solr_failures)}")

        if has_failures:
            return 1

        lids = load_deprecated_lids(csv_path)
        print(f"\n✅ All {len(lids)} deprecated LIDs are absent from both the REST API and Solr registry!")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
