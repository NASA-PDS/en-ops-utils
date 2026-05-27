#!/usr/bin/env python3
"""
Tests for the check_version_id_filename_match script.
"""

import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "bin" / "context"))

from check_version_id_filename_match import (
    check_version_id_filename_match,
    extract_version_from_filename,
    extract_version_id_from_xml,
    find_context_product_files,
)


def create_context_xml(file_path: Path, version_id: str) -> None:
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Product_Context xmlns="http://pds.nasa.gov/pds4/pds/v1">
    <Identification_Area>
        <logical_identifier>urn:nasa:pds:context:investigation:mission.test</logical_identifier>
        <version_id>{version_id}</version_id>
        <title>Test Product</title>
        <Modification_History>
            <Modification_Detail>
                <modification_date>2024-01-01</modification_date>
                <version_id>1.0</version_id>
                <description>Initial creation</description>
            </Modification_Detail>
        </Modification_History>
    </Identification_Area>
</Product_Context>"""
    file_path.write_text(xml_content)


# --- find_context_product_files ---

def test_find_context_product_files_excludes_collections():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "mission.test_1.0.xml").touch()
        (p / "collection_instrument_v1.0.xml").touch()
        (p / "bundle_context.xml").touch()
        (p / "notes.txt").touch()

        files = find_context_product_files(tmp)
        names = [f.name for f in files]

        assert "mission.test_1.0.xml" in names
        assert "collection_instrument_v1.0.xml" not in names
        assert "bundle_context.xml" not in names
        assert "notes.txt" not in names


def test_find_context_product_files_recursive():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        subdir = p / "instrument"
        subdir.mkdir()
        (p / "mission.test_1.0.xml").touch()
        (subdir / "instrument.test_1.0.xml").touch()

        files = find_context_product_files(tmp)
        assert len(files) == 2


# --- extract_version_from_filename ---

def test_extract_version_simple():
    assert extract_version_from_filename(Path("mission.magellan_2.1.xml")) == "2.1"


def test_extract_version_underscore_in_name():
    assert extract_version_from_filename(Path("mission.apollo_17_2.2.xml")) == "2.2"


def test_extract_version_single_digit():
    assert extract_version_from_filename(Path("instrument.msl.apxs_1.0.xml")) == "1.0"


def test_extract_version_no_version_suffix():
    assert extract_version_from_filename(Path("bundle_context.xml")) is None


def test_extract_version_collection_style():
    # Collection files use v-prefix; our regex won't match — returns None
    assert extract_version_from_filename(Path("collection_instrument_v2.1.xml")) is None


# --- extract_version_id_from_xml ---

def test_extract_version_id_from_xml_correct():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "mission.test_2.1.xml"
        create_context_xml(f, "2.1")
        assert extract_version_id_from_xml(f) == "2.1"


def test_extract_version_id_targets_identification_area_not_modification_history():
    """version_id inside Modification_History should not be returned."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "mission.test_3.0.xml"
        # Identification_Area version_id is 3.0; Modification_History has 1.0 and 2.0
        create_context_xml(f, "3.0")
        assert extract_version_id_from_xml(f) == "3.0"


def test_extract_version_id_missing_raises():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "test.xml"
        f.write_text("""<?xml version="1.0"?>
<Product_Context xmlns="http://pds.nasa.gov/pds4/pds/v1">
    <Identification_Area>
        <logical_identifier>urn:test</logical_identifier>
    </Identification_Area>
</Product_Context>""")
        with pytest.raises(ValueError, match="No version_id"):
            extract_version_id_from_xml(f)


def test_extract_version_id_parse_error_raises():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "bad.xml"
        f.write_text("this is not xml <<<")
        with pytest.raises(ET.ParseError):
            extract_version_id_from_xml(f)


# --- check_version_id_filename_match ---

def test_all_match_returns_no_mismatches():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        create_context_xml(p / "mission.test_1.0.xml", "1.0")
        create_context_xml(p / "mission.other_2.3.xml", "2.3")

        has_mismatches, mismatches = check_version_id_filename_match(tmp)

        assert not has_mismatches
        assert mismatches == []


def test_mismatch_detected():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        create_context_xml(p / "mission.apollo_17_2.2.xml", "2.0")

        has_mismatches, mismatches = check_version_id_filename_match(tmp)

        assert has_mismatches
        assert len(mismatches) == 1
        file_path, filename_ver, xml_ver = mismatches[0]
        assert file_path.name == "mission.apollo_17_2.2.xml"
        assert filename_ver == "2.2"
        assert xml_ver == "2.0"


def test_mixed_valid_and_invalid():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        create_context_xml(p / "mission.ok_1.0.xml", "1.0")
        create_context_xml(p / "mission.bad_1.1.xml", "1.0")

        has_mismatches, mismatches = check_version_id_filename_match(tmp)

        assert has_mismatches
        assert len(mismatches) == 1
        assert mismatches[0][0].name == "mission.bad_1.1.xml"


def test_collection_files_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        # A collection file with a mismatched internal version_id should not trigger a failure
        create_context_xml(p / "collection_instrument_v1.0.xml", "9.9")

        has_mismatches, _ = check_version_id_filename_match(tmp)
        assert not has_mismatches


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
