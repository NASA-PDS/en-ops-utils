# encoding: utf-8
"""Tests for pds.en_ops_utils.portal.pds_sync_api."""
import hashlib
import ipaddress
import os
import tempfile
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest
import requests
from lxml import etree
from pds.en_ops_utils.portal.pds_sync_api import _already_downloaded
from pds.en_ops_utils.portal.pds_sync_api import _check_registry_response
from pds.en_ops_utils.portal.pds_sync_api import _get_lidvid
from pds.en_ops_utils.portal.pds_sync_api import _is_retryable_error
from pds.en_ops_utils.portal.pds_sync_api import _should_exclude_url
from pds.en_ops_utils.portal.pds_sync_api import _validate_ip_address
from pds.en_ops_utils.portal.pds_sync_api import _validate_url
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
        _write_harvest_config(tmp, config_path)

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
        _write_harvest_config(tmp, config_path)

        tree = etree.parse(config_path)
        assert tree.getroot().find("registry") is not None


def test_write_harvest_config_nested_download_path():
    """Download path is resolved to an absolute path in the config."""
    with tempfile.TemporaryDirectory() as tmp:
        download_path = os.path.join(tmp, "subdir")
        os.makedirs(download_path)
        config_path = os.path.join(tmp, "harvest.cfg")
        _write_harvest_config(download_path, config_path)

        tree = etree.parse(config_path)
        path_text = tree.getroot().find("load/directories/path").text
        assert path_text == os.path.abspath(download_path)


# ---------------------------------------------------------------------------
# _validate_ip_address
# ---------------------------------------------------------------------------

def test_validate_ip_address_accepts_global():
    """Global/public IP addresses are allowed."""
    # Public IPs should not raise
    _validate_ip_address(ipaddress.ip_address("8.8.8.8"))
    _validate_ip_address(ipaddress.ip_address("1.1.1.1"))
    _validate_ip_address(ipaddress.ip_address("2001:4860:4860::8888"))


def test_validate_ip_address_rejects_private():
    """Private IP addresses are rejected."""
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("192.168.1.1"))
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("10.0.0.1"))
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("172.16.0.1"))


def test_validate_ip_address_rejects_loopback():
    """Loopback addresses are rejected."""
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("127.0.0.1"))
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("::1"))


def test_validate_ip_address_rejects_link_local():
    """Link-local addresses (including AWS metadata) are rejected."""
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("169.254.169.254"))
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("fe80::1"))


def test_validate_ip_address_rejects_unspecified():
    """Unspecified addresses (0.0.0.0 and ::) are rejected."""
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("0.0.0.0"))
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("::"))


def test_validate_ip_address_rejects_cgnat():
    """CGNAT range (100.64.0.0/10) is rejected."""
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("100.64.0.1"))
    with pytest.raises(ValueError, match="non-global IP address"):
        _validate_ip_address(ipaddress.ip_address("100.127.255.254"))


def test_validate_ip_address_rejects_multicast():
    """Multicast addresses are rejected."""
    with pytest.raises(ValueError, match="multicast IP address"):
        _validate_ip_address(ipaddress.ip_address("224.0.0.1"))
    with pytest.raises(ValueError, match="multicast IP address"):
        _validate_ip_address(ipaddress.ip_address("ff02::1"))


# ---------------------------------------------------------------------------
# _validate_url
# ---------------------------------------------------------------------------

def test_validate_url_accepts_https():
    """HTTPS URLs with global hostnames are accepted."""
    with patch("pds.en_ops_utils.portal.pds_sync_api.socket.getaddrinfo",
               return_value=[((2, 1, 6, "", ("8.8.8.8", 443)))]):
        _validate_url("https://example.com/api")


def test_validate_url_accepts_http():
    """HTTP URLs with global hostnames are accepted."""
    with patch("pds.en_ops_utils.portal.pds_sync_api.socket.getaddrinfo",
               return_value=[((2, 1, 6, "", ("1.1.1.1", 80)))]):
        _validate_url("http://example.com/api")


def test_validate_url_rejects_invalid_scheme():
    """Non-http/https schemes are rejected."""
    with pytest.raises(ValueError, match="Invalid URL scheme"):
        _validate_url("ftp://example.com")
    with pytest.raises(ValueError, match="Invalid URL scheme"):
        _validate_url("file:///etc/passwd")


def test_validate_url_rejects_missing_hostname():
    """URLs without hostnames are rejected."""
    with pytest.raises(ValueError, match="must include a hostname"):
        _validate_url("http://")


def test_validate_url_rejects_embedded_credentials():
    """URLs with embedded credentials are rejected."""
    with pytest.raises(ValueError, match="must not contain embedded credentials"):
        _validate_url("http://foo:bar@example.com")  # pragma: allowlist secret
    with pytest.raises(ValueError, match="must not contain embedded credentials"):
        _validate_url("https://alice:bob@api.com/endpoint")  # pragma: allowlist secret


def test_validate_url_rejects_query_parameters():
    """URLs with query parameters are rejected."""
    with pytest.raises(ValueError, match="must not contain query parameters"):
        _validate_url("https://api.com/endpoint?param=value")
    with pytest.raises(ValueError, match="must not contain query parameters"):
        _validate_url("http://example.com/?filter=test")


def test_validate_url_rejects_fragments():
    """URLs with fragments are rejected."""
    with pytest.raises(ValueError, match="must not contain fragment"):
        _validate_url("https://example.com/page#section")


def test_validate_url_rejects_localhost():
    """Localhost variations are rejected."""
    with pytest.raises(ValueError, match="Cannot make requests to localhost"):
        _validate_url("http://localhost/api")
    with pytest.raises(ValueError, match="Cannot make requests to localhost"):
        _validate_url("http://127.0.0.1/api")


def test_validate_url_rejects_private_ips():
    """URLs resolving to private IPs are rejected."""
    with patch("pds.en_ops_utils.portal.pds_sync_api.socket.getaddrinfo",
               return_value=[((2, 1, 6, "", ("192.168.1.1", 80)))]):
        with pytest.raises(ValueError, match="non-global IP address"):
            _validate_url("http://internal.corp/api")


def test_validate_url_rejects_aws_metadata():
    """URLs resolving to AWS metadata service are rejected."""
    with patch("pds.en_ops_utils.portal.pds_sync_api.socket.getaddrinfo",
               return_value=[((2, 1, 6, "", ("169.254.169.254", 80)))]):
        with pytest.raises(ValueError, match="non-global IP address"):
            _validate_url("http://metadata.service/")


def test_validate_url_rejects_dns_failure():
    """URLs that cannot be resolved are rejected."""
    import socket
    with patch("pds.en_ops_utils.portal.pds_sync_api.socket.getaddrinfo",
               side_effect=socket.gaierror("Name or service not known")):
        with pytest.raises(ValueError, match="Cannot resolve hostname"):
            _validate_url("http://nonexistent.invalid/")


def test_validate_url_rejects_username_only():
    """URLs with username but no password are rejected."""
    with pytest.raises(ValueError, match="must not contain embedded credentials"):
        _validate_url("http://foo@example.com/api")  # pragma: allowlist secret


def test_validate_url_accepts_paths():
    """URLs with paths are accepted."""
    with patch("pds.en_ops_utils.portal.pds_sync_api.socket.getaddrinfo",
               return_value=[((2, 1, 6, "", ("8.8.8.8", 443)))]):
        _validate_url("https://api.example.com/v1/products/search")


def test_validate_url_accepts_ports():
    """URLs with explicit port numbers are accepted."""
    with patch("pds.en_ops_utils.portal.pds_sync_api.socket.getaddrinfo",
               return_value=[((2, 1, 6, "", ("8.8.8.8", 8080)))]):
        _validate_url("https://api.example.com:8080/endpoint")


# ---------------------------------------------------------------------------
# _should_exclude_url
# ---------------------------------------------------------------------------

def test_should_exclude_url_no_patterns():
    """Empty pattern list excludes nothing."""
    assert _should_exclude_url("https://example.com/path/to/file.xml", []) is False


def test_should_exclude_url_matches_substring():
    """Pattern matches if it appears anywhere in URL path."""
    url = "https://example.com/archive/nasa/pds/data/file.xml"
    assert _should_exclude_url(url, ["nasa/pds"]) is True


def test_should_exclude_url_no_match():
    """Returns False when no pattern matches."""
    url = "https://example.com/archive/esa/psa/data/file.xml"
    assert _should_exclude_url(url, ["nasa/pds"]) is False


def test_should_exclude_url_multiple_patterns():
    """Matches if any pattern in the list matches."""
    url = "https://example.com/archive/test/data/file.xml"
    assert _should_exclude_url(url, ["nasa", "test", "other"]) is True


def test_should_exclude_url_case_sensitive():
    """Pattern matching is case-sensitive."""
    url = "https://example.com/archive/NASA/data/file.xml"
    assert _should_exclude_url(url, ["nasa"]) is False
    assert _should_exclude_url(url, ["NASA"]) is True


# ---------------------------------------------------------------------------
# _is_retryable_error
# ---------------------------------------------------------------------------

def test_is_retryable_error_network_errors():
    """Network errors (timeouts, connection errors) are retryable."""
    assert _is_retryable_error(requests.exceptions.Timeout()) is True
    assert _is_retryable_error(requests.exceptions.ConnectionError()) is True


def test_is_retryable_error_5xx():
    """5xx server errors are retryable."""
    response_500 = Mock()
    response_500.status_code = 500
    assert _is_retryable_error(requests.exceptions.HTTPError(response=response_500)) is True

    response_503 = Mock()
    response_503.status_code = 503
    assert _is_retryable_error(requests.exceptions.HTTPError(response=response_503)) is True


def test_is_retryable_error_http_error_no_response():
    """HTTPError without response object is retryable (network issue)."""
    error = requests.exceptions.HTTPError()
    assert _is_retryable_error(error) is True


def test_is_retryable_error_429():
    """429 rate limit errors are retryable."""
    response = Mock()
    response.status_code = 429
    error = requests.exceptions.HTTPError(response=response)
    assert _is_retryable_error(error) is True


def test_is_retryable_error_4xx_not_retryable():
    """4xx client errors (except 429) are not retryable."""
    response_400 = Mock()
    response_400.status_code = 400
    assert _is_retryable_error(requests.exceptions.HTTPError(response=response_400)) is False

    response_404 = Mock()
    response_404.status_code = 404
    assert _is_retryable_error(requests.exceptions.HTTPError(response=response_404)) is False


# ---------------------------------------------------------------------------
# _check_registry_response
# ---------------------------------------------------------------------------

def test_check_registry_response_200_returns_true():
    """200 OK indicates resource exists."""
    response = Mock()
    response.status_code = HTTPStatus.OK
    assert _check_registry_response(response, "urn:test") is True


def test_check_registry_response_404_returns_false():
    """404 NOT_FOUND indicates resource does not exist."""
    response = Mock()
    response.status_code = HTTPStatus.NOT_FOUND
    assert _check_registry_response(response, "urn:test") is False


def test_check_registry_response_429_returns_none():
    """429 TOO_MANY_REQUESTS signals retry needed."""
    response = Mock()
    response.status_code = HTTPStatus.TOO_MANY_REQUESTS
    assert _check_registry_response(response, "urn:test") is None


def test_check_registry_response_5xx_returns_none():
    """5xx server errors signal retry needed."""
    response_500 = Mock()
    response_500.status_code = 500
    assert _check_registry_response(response_500, "urn:test") is None

    response_503 = Mock()
    response_503.status_code = 503
    assert _check_registry_response(response_503, "urn:test") is None


def test_check_registry_response_other_4xx_raises():
    """Other 4xx errors (not 404, 429) raise ValueError."""
    response = Mock()
    response.status_code = 403
    with pytest.raises(ValueError, match="Unexpected 403"):
        _check_registry_response(response, "urn:test")
