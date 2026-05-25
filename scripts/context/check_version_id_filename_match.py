#!/usr/bin/env python3
"""
Script to verify that the version_id in each PDS4 context product XML label
matches the version suffix of its filename.

For example:
    Valid:   version_id = 2.1, filename = mission.magellan_2.1.xml
    Invalid: version_id = 2.0, filename = mission.magellan_2.1.xml

Usage:
    python check_version_id_filename_match.py [directory_path]

    If no directory is specified, defaults to "../../data/pds4/context-pds4"

Returns:
    0 if all version_ids match their filenames, 1 if mismatches are found
"""

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple


COLLECTION_PREFIX = "collection_"
BUNDLE_PREFIX = "bundle_"


def find_context_product_files(directory: str) -> List[Path]:
    """
    Recursively find all PDS4 context product XML files, excluding collection
    and bundle label files.
    """
    xml_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".xml") and not file.startswith(COLLECTION_PREFIX) and not file.startswith(BUNDLE_PREFIX):
                xml_files.append(Path(root) / file)
    return xml_files


def extract_version_from_filename(file_path: Path) -> Optional[str]:
    """
    Extract the version string from a context product filename.

    The version is the segment after the last underscore and before '.xml'.
    For example: mission.apollo_17_2.2.xml -> '2.2'

    Returns None if the filename does not match the expected pattern.
    """
    stem = file_path.stem  # filename without .xml
    # Version is everything after the last underscore; must look like N.N
    match = re.search(r"_(\d+\.\d+)$", stem)
    if match:
        return match.group(1)
    return None


def extract_version_id_from_xml(file_path: Path) -> str:
    """
    Extract the version_id from the Identification_Area of a PDS4 XML label.

    Raises:
        ValueError: If version_id is not found or is empty
        ET.ParseError: If XML parsing fails
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        namespace = {"pds": "http://pds.nasa.gov/pds4/pds/v1"}

        id_area = root.find(".//pds:Identification_Area", namespace)
        if id_area is None:
            id_area = root.find(".//Identification_Area")

        if id_area is None:
            raise ValueError(f"No Identification_Area found in {file_path}")

        version_elem = id_area.find("pds:version_id", namespace)
        if version_elem is None:
            version_elem = id_area.find("version_id")

        if version_elem is None:
            raise ValueError(f"No version_id found in Identification_Area of {file_path}")

        version_id = version_elem.text.strip()
        if not version_id:
            raise ValueError(f"Empty version_id in {file_path}")

        return version_id

    except ET.ParseError as e:
        raise ET.ParseError(f"Failed to parse XML file {file_path}: {e}")


def check_version_id_filename_match(
    directory: str, verbose: bool = False
) -> Tuple[bool, List[Tuple[Path, str, str]]]:
    """
    Check that version_id in each XML label matches the filename version suffix.

    Returns:
        Tuple of (has_mismatches, mismatches) where mismatches is a list of
        (file_path, filename_version, xml_version_id) tuples
    """
    xml_files = find_context_product_files(directory)
    mismatches = []
    skipped = 0

    print(f"Scanning {len(xml_files)} context product XML files in {directory}...")

    for file_path in xml_files:
        filename_version = extract_version_from_filename(file_path)

        if filename_version is None:
            if verbose:
                print(f"  Skipping (no version in filename): {file_path.name}")
            skipped += 1
            continue

        try:
            xml_version = extract_version_id_from_xml(file_path)
        except (ValueError, ET.ParseError) as e:
            print(f"Warning: {e}")
            skipped += 1
            continue

        if verbose:
            print(f"  {file_path.name}: filename={filename_version}, version_id={xml_version}")

        if filename_version != xml_version:
            mismatches.append((file_path, filename_version, xml_version))

    if skipped and verbose:
        print(f"  Skipped {skipped} files (no version in filename or parse error)")

    return len(mismatches) > 0, mismatches


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that version_id in PDS4 context product XML labels matches the filename version suffix."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=str(Path(__file__).parent.parent.parent / "data" / "pds4" / "context-pds4"),
        help="Directory to scan for context product XML files (default: ../../data/pds4/context-pds4)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    if not os.path.exists(args.directory):
        print(f"Error: Directory '{args.directory}' not found.")
        return 1

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a directory.")
        return 1

    try:
        has_mismatches, mismatches = check_version_id_filename_match(args.directory, args.verbose)

        if has_mismatches:
            print("\n❌ VERSION_ID / FILENAME MISMATCHES FOUND:")
            print("=" * 60)
            for file_path, filename_version, xml_version in mismatches:
                print(f"\n  File:              {file_path.name}")
                print(f"  Filename version:  {filename_version}")
                print(f"  XML version_id:    {xml_version}")
            print(f"\nTotal mismatches: {len(mismatches)}")
            return 1
        else:
            print(f"\n✅ All version_ids match their filenames!")
            return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
