#!/usr/bin/env python3
"""
Tests for the check_deprecated_lids script.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "bin" / "context"))

from check_deprecated_lids import (
    check_deprecated_lids,
    load_deprecated_lids,
    query_api,
)


def write_csv(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n")


# --- load_deprecated_lids ---

def test_load_skips_comments_and_header():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "lids.csv"
        write_csv(f, [
            "# comment line",
            "# another comment",
            "deprecatedLID,dateOfReplacement,replacementLID",
            "urn:nasa:pds:context:instrument:foo.bar,2021-01-01,urn:nasa:pds:context:instrument:bar.foo",
            "urn:nasa:pds:context:instrument:baz.qux,2022-06-01,urn:nasa:pds:context:instrument:qux.baz",
        ])
        lids = load_deprecated_lids(f)
        assert lids == [
            "urn:nasa:pds:context:instrument:foo.bar",
            "urn:nasa:pds:context:instrument:baz.qux",
        ]


def test_load_skips_blank_lines():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "lids.csv"
        write_csv(f, [
            "deprecatedLID,dateOfReplacement,replacementLID",
            "",
            "urn:nasa:pds:context:instrument:foo.bar,2021-01-01,urn:nasa:pds:context:instrument:bar.foo",
            "",
        ])
        lids = load_deprecated_lids(f)
        assert lids == ["urn:nasa:pds:context:instrument:foo.bar"]


def test_load_empty_file_returns_empty_list():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "lids.csv"
        write_csv(f, ["# just comments", "deprecatedLID,dateOfReplacement,replacementLID"])
        assert load_deprecated_lids(f) == []


# --- query_api ---

def test_query_api_returns_404():
    mock_response = MagicMock()
    mock_response.status_code = 404
    with patch("check_deprecated_lids.requests.Session.get", return_value=mock_response):
        session = requests.Session()
        status, error = query_api("urn:nasa:pds:context:instrument:foo.bar", session)
        assert status == 404
        assert error == ""


def test_query_api_returns_200():
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("check_deprecated_lids.requests.Session.get", return_value=mock_response):
        session = requests.Session()
        status, error = query_api("urn:nasa:pds:context:instrument:still.here", session)
        assert status == 200
        assert error == ""


def test_query_api_timeout():
    with patch("check_deprecated_lids.requests.Session.get", side_effect=requests.exceptions.Timeout()):
        session = requests.Session()
        status, error = query_api("urn:nasa:pds:context:instrument:foo.bar", session)
        assert status == -1
        assert "timed out" in error


def test_query_api_connection_error():
    with patch("check_deprecated_lids.requests.Session.get", side_effect=requests.exceptions.ConnectionError("refused")):
        session = requests.Session()
        status, error = query_api("urn:nasa:pds:context:instrument:foo.bar", session)
        assert status == -1
        assert "connection error" in error


# --- check_deprecated_lids ---

def _make_csv(tmp: str, lids: list[str]) -> Path:
    f = Path(tmp) / "lids.csv"
    rows = ["deprecatedLID,dateOfReplacement,replacementLID"]
    for lid in lids:
        rows.append(f"{lid},2021-01-01,urn:nasa:pds:context:instrument:replacement")
    write_csv(f, rows)
    return f


def test_all_404_no_failures():
    with tempfile.TemporaryDirectory() as tmp:
        f = _make_csv(tmp, [
            "urn:nasa:pds:context:instrument:foo.bar",
            "urn:nasa:pds:context:instrument:baz.qux",
        ])
        with patch("check_deprecated_lids.query_api", return_value=(404, "")):
            has_failures, failures = check_deprecated_lids(f)
        assert not has_failures
        assert failures == []


def test_non_404_detected_as_failure():
    with tempfile.TemporaryDirectory() as tmp:
        f = _make_csv(tmp, ["urn:nasa:pds:context:instrument:still.here"])
        with patch("check_deprecated_lids.query_api", return_value=(200, "")):
            has_failures, failures = check_deprecated_lids(f)
        assert has_failures
        assert len(failures) == 1
        lid, status, error = failures[0]
        assert lid == "urn:nasa:pds:context:instrument:still.here"
        assert status == 200
        assert error == ""


def test_network_error_recorded_as_failure():
    with tempfile.TemporaryDirectory() as tmp:
        f = _make_csv(tmp, ["urn:nasa:pds:context:instrument:foo.bar"])
        with patch("check_deprecated_lids.query_api", return_value=(-1, "connection error: refused")):
            has_failures, failures = check_deprecated_lids(f)
        assert has_failures
        assert len(failures) == 1
        _, status, error = failures[0]
        assert status == -1
        assert "connection error" in error


def test_mixed_results():
    with tempfile.TemporaryDirectory() as tmp:
        f = _make_csv(tmp, [
            "urn:nasa:pds:context:instrument:gone.one",
            "urn:nasa:pds:context:instrument:still.here",
            "urn:nasa:pds:context:instrument:gone.two",
        ])
        responses = [(404, ""), (200, ""), (404, "")]
        with patch("check_deprecated_lids.query_api", side_effect=responses):
            has_failures, failures = check_deprecated_lids(f)
        assert has_failures
        assert len(failures) == 1
        assert failures[0][0] == "urn:nasa:pds:context:instrument:still.here"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
