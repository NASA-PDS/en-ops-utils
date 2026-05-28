# encoding: utf-8
"""Tests for pds.en_ops_utils.portal.pds_sync_api."""

import hashlib
import os
import tempfile

import pytest
from lxml import etree

from pds.en_ops_utils.portal.pds_sync_api import _already_downloaded
from pds.en_ops_utils.portal.pds_sync_api import _get_lidvid
from pds.en_ops_utils.portal.pds_sync_api import _write_harvest_config


# ---------------------------------------------------------------------------
# _get_lidvid
# ---------------------------------------------------------------------------

def test_get_lidvid_from_properties():
    """Prefer lidvid from properties dict when present."""
    product = {"properties": {"lidvid": "urn:nasa:pds:bundle::1.0"}, "id": "fallback"}
    assert _get_lidvid(product) == "urn:nasa:pds:bundle::1.0"


def test_get_lidvid_falls_back_to_id():
    """Fall back to top-level id when properties lacks lidvid."""
    product = {"properties": {}, "id": "urn:nasa:pds:bundle::1.0"}
    assert _get_lidvid(product) == "urn:nasa:pds:bundle::1.0"


# ---------------------------------------------------------------------------
# _already_downloaded
# ---------------------------------------------------------------------------

def test_already_downloaded_missing_file():
    """Return False when the file does not exist."""
    assert _already_downloaded("/nonexistent/path/label.xml", "abc123") is False


def test_already_downloaded_correct_md5():
    """Return True when the file exists and its MD5 matches."""
    content = b"<xml>test</xml>"
    digest = hashlib.md5(content, usedforsecurity=False).hexdigest()
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(content)
        path = f.name
    try:
        assert _already_downloaded(path, digest) is True
    finally:
        os.unlink(path)


def test_already_downloaded_wrong_md5():
    """Return False when the file exists but MD5 does not match."""
    content = b"<xml>test</xml>"
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(content)
        path = f.name
    try:
        assert _already_downloaded(path, "wrongchecksum") is False
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# _write_harvest_config
# ---------------------------------------------------------------------------

def test_write_harvest_config_creates_valid_xml():
    """Generated harvest config is valid XML with expected structure."""
    with tempfile.TemporaryDirectory() as tmp:
        config_path = os.path.join(tmp, "harvest.cfg")
        _write_harvest_config("psa", tmp, config_path)

        assert os.path.isfile(config_path)
        tree = etree.parse(config_path)
        root = tree.getroot()
        assert root.tag == "harvest"
        assert root.find("load/directories/path") is not None
        assert root.find("load/directories/path").text == os.path.abspath(tmp)


def test_write_harvest_config_contains_registry_element():
    """Generated harvest config includes a registry element."""
    with tempfile.TemporaryDirectory() as tmp:
        config_path = os.path.join(tmp, "harvest.cfg")
        _write_harvest_config("psa", tmp, config_path)

        tree = etree.parse(config_path)
        assert tree.getroot().find("registry") is not None


def test_write_harvest_config_nested_download_path():
    """Download path is resolved to an absolute path in the config."""
    with tempfile.TemporaryDirectory() as tmp:
        download_path = os.path.join(tmp, "subdir")
        os.makedirs(download_path)
        config_path = os.path.join(tmp, "harvest.cfg")
        _write_harvest_config("psa", download_path, config_path)

        tree = etree.parse(config_path)
        path_text = tree.getroot().find("load/directories/path").text
        assert path_text == os.path.abspath(download_path)
