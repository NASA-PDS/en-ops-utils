# encoding: utf-8
"""Sync ESA PSA products to Search API by downloading their XML label files."""
import argparse
import hashlib
import ipaddress
import logging
import os
import secrets
import socket
import time
import urllib.parse
from http import HTTPStatus
from typing import Generator
from typing import List
from typing import Optional
from typing import Tuple

import requests
from lxml import etree


PDS_XSD_URL = "https://github.com/NASA-PDS/harvest/blob/main/src/main/resources/conf/configuration.xsd"
PROD_SEARCH_API_URL = "https://pds.mcp.nasa.gov/api/search/1/products"
XML_SCHEMA_INSTANCE_URI = "http://www.w3.org/2001/XMLSchema-instance"
NS_MAP = {"xsi": XML_SCHEMA_INSTANCE_URI}

_logger = logging.getLogger(__name__)
_search_key = "ops:Harvest_Info.ops:harvest_date_time"
_query_page_size = 50
_psa_query = (
    '((product_class eq "Product_Context" or  product_class eq "Product_Bundle" or '
    'product_class eq "Product_Collection") and ops:Harvest_Info.ops:node_name like "PSA")'
)
_bufsiz = 512
_max_retries = 3
_retry_delay = 2  # seconds
_max_backoff_delay = 60  # seconds - cap for exponential backoff
_rng = secrets.SystemRandom()  # Cryptographically secure RNG for jitter


def _validate_ip_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Validate that an IP address is safe for external requests.

    Args:
        ip: The IP address to validate

    Raises:
        ValueError: If the IP address is not safe for requests
    """
    if ip.is_private:
        raise ValueError(f"Cannot make requests to private IP address: {ip}")

    if ip.is_loopback:
        raise ValueError(f"Cannot make requests to loopback address: {ip}")

    if ip.is_link_local:
        raise ValueError(f"Cannot make requests to link-local address: {ip}")

    if ip.is_multicast or ip.is_reserved:
        raise ValueError(f"Cannot make requests to reserved IP address: {ip}")


def _validate_url(url: str) -> None:
    """Validate URL to prevent SSRF attacks.

    Ensures the URL uses http/https scheme and doesn't target internal/private networks,
    localhost, or cloud metadata services.

    Args:
        url: The URL to validate

    Raises:
        ValueError: If the URL is not safe for network requests
    """
    parsed = urllib.parse.urlparse(url)

    # Only allow http/https schemes
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}': only http/https are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")

    # Block localhost variations
    localhost_names = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    if hostname.lower() in localhost_names:
        raise ValueError(f"Cannot make requests to localhost: {hostname}")

    # Resolve hostname and check IP address
    try:
        # Get all IP addresses for the hostname
        addr_info = socket.getaddrinfo(hostname, None)
        for addr in addr_info:
            ip_str = addr[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
                _validate_ip_address(ip)
            except ValueError as e:
                # ipaddress.ip_address() raised ValueError for invalid IP
                raise ValueError(f"Invalid IP address for hostname {hostname}: {e}") from e

    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname {hostname}: {e}") from e


def _get_lidvid(product: dict) -> str:
    """Get the LIDVID from a ``product``."""
    try:
        return product["properties"]["lidvid"]
    except KeyError:
        return product["id"]


def _is_retryable_error(exception: requests.exceptions.RequestException) -> bool:
    """Check if an HTTP exception should be retried.

    Args:
        exception: The exception to check

    Returns:
        True if the error is transient and should be retried, False otherwise
    """
    if not isinstance(exception, requests.exceptions.HTTPError):
        return True  # Retry network errors, timeouts, etc.

    if exception.response is None:
        return True

    status = exception.response.status_code
    # Retry 5xx errors and 429 (rate limit), but not other 4xx (client errors)
    return status >= 500 or status == HTTPStatus.TOO_MANY_REQUESTS


def _handle_retry_delay(delay: float, operation: str, attempt: int, reason: str) -> float:
    """Sleep with jittered exponential backoff and log retry attempt.

    Args:
        delay: Current delay in seconds
        operation: Description of operation for logging
        attempt: Current attempt number
        reason: Reason for retry (for logging)

    Returns:
        Updated delay for next retry
    """
    jittered_delay = delay * (0.5 + 0.5 * _rng.random())
    _logger.warning(
        "%s %s, retrying in %.2fs (attempt %d/%d)",
        reason, operation, jittered_delay, attempt, _max_retries
    )
    time.sleep(jittered_delay)
    return min(delay * 2, _max_backoff_delay)


def _make_request_with_retry(url: str, params: dict, operation: str) -> requests.Response:
    """Make HTTP GET request with exponential backoff retry logic.

    Args:
        url: The URL to request
        params: Query parameters
        operation: Description of operation for logging (e.g., "querying products")

    Returns:
        Successful response object

    Raises:
        requests.exceptions.RequestException: On failure after all retries
    """
    delay = _retry_delay
    for attempt in range(1, _max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                if attempt < _max_retries:
                    delay = _handle_retry_delay(delay, operation, attempt, "Rate limited (429)")
                    continue
                response.raise_for_status()  # Will raise HTTPError on last attempt
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if not _is_retryable_error(e):
                raise  # Don't retry non-transient errors

            if attempt < _max_retries:
                delay = _handle_retry_delay(delay, operation, attempt, f"Network error: {e}")
                continue
            raise
    # Should never reach here due to raise in loop, but for type safety
    raise RuntimeError(f"Retry loop exhausted for {operation}")


def _get_esa_psa_products(url: str) -> Generator[dict, None, None]:
    """Query the ESA PSA ("easy peasy") products from the registry.

    Implements exponential backoff with jitter for rate limiting (429) responses.

    Args:
        url: PDS Search API base URL (validated for SSRF protection)
    """
    _validate_url(url)
    params: dict = {"sort": _search_key, "limit": _query_page_size, "q": _psa_query}
    _logger.info("Generating ESA-PSA products from %s", url)
    while True:
        _logger.debug("Making request to %s with params %r", url, params)

        response = _make_request_with_retry(url, params, "querying products")
        matches = response.json()["data"]
        num_matches = len(matches)

        for item in matches:
            yield item

        if num_matches < _query_page_size:
            break

        params["search-after"] = matches[-1]["properties"][_search_key]


def _write_harvest_config(download_path: str, config: str) -> None:
    """Create the harvest config file."""
    root = etree.Element(
        "harvest",
        nsmap=NS_MAP,
        attrib={f"{{{XML_SCHEMA_INSTANCE_URI}}}schemaLocation": PDS_XSD_URL},
    )
    download_path = os.path.abspath(download_path)
    etree.SubElement(root, "registry", auth="/path/to/auth/file").text = "app://localhost.xml"
    load = etree.SubElement(root, "load")
    dirs = etree.SubElement(load, "directories")
    etree.SubElement(dirs, "path").text = download_path
    file_info = etree.SubElement(root, "fileInfo", processDataFiles="true", storeLabels="true")
    attrs = {"replacePrefix": download_path, "with": "https://url/to/archive"}
    etree.SubElement(file_info, "fileRef", attrib=attrs)
    etree.SubElement(root, "autoGenFields")
    _logger.info("Writing harvest XML config to %s", config)
    etree.ElementTree(root).write(config, pretty_print=True, xml_declaration=True, encoding="UTF-8")


def _check_registry_response(response: requests.Response, lidvid: str) -> Optional[bool]:
    """Interpret registry HEAD response to determine if LIDVID exists.

    Args:
        response: HTTP response from registry HEAD request
        lidvid: The LIDVID being checked (for error messages)

    Returns:
        True if exists, False if not found, None if should retry

    Raises:
        ValueError: For unexpected status codes or rate limit exhaustion
    """
    if response.status_code == HTTPStatus.OK:
        return True
    elif response.status_code == HTTPStatus.NOT_FOUND:
        return False
    elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        return None  # Signal that retry is needed
    else:
        raise ValueError(
            f"Unexpected {response.status_code} while checking for existence of {lidvid}"
        )


def _exists_in_registry(lidvid: str, url: str) -> bool:
    """Tell (true or false) if the given ``lidvid`` exists in the registry at ``url``.

    Implements exponential backoff with jitter for rate limiting (429) responses.

    Args:
        lidvid: The LIDVID to check
        url: PDS Search API base URL (validated for SSRF protection)
    """
    _validate_url(url)
    _logger.debug("Checking if lidvid %s is already in the registry", lidvid)

    check_url = f"{url}/{urllib.parse.quote(lidvid, safe='')}"
    delay = _retry_delay

    for attempt in range(1, _max_retries + 1):
        try:
            response = requests.head(check_url, timeout=30)
            result = _check_registry_response(response, lidvid)

            if result is not None:
                return result

            # result is None means we got a 429 and should retry
            if attempt < _max_retries:
                delay = _handle_retry_delay(delay, f"checking {lidvid}", attempt, "Rate limited (429)")
                continue
            else:
                raise ValueError(
                    f"Rate limited (429) while checking existence of {lidvid} "
                    f"after {_max_retries} attempts"
                )

        except requests.exceptions.RequestException as e:
            if attempt < _max_retries:
                delay = _handle_retry_delay(delay, f"checking {lidvid}", attempt, f"Network error: {e}")
                continue
            else:
                raise ValueError(
                    f"Network error checking existence of {lidvid} after {_max_retries} attempts"
                ) from e

    # Should never reach here
    raise RuntimeError(f"Retry loop exhausted while checking {lidvid}")


def _already_downloaded(label_file: str, md5: str) -> bool:
    """Tell if we've already downloaded ``label_file`` with the expected ``md5``."""
    _logger.debug("Checking if label file %s is already intact", label_file)
    if os.path.isfile(label_file):
        digest = hashlib.md5(usedforsecurity=False)
        with open(label_file, "rb") as io:
            while buf := io.read(_bufsiz):
                digest.update(buf)
        return digest.hexdigest() == md5
    return False


def _download_file(file_url: str, download_path: str, file_type: str = "file") -> Tuple[bool, Optional[str]]:
    """Download a file from ``file_url`` to ``download_path`` with retry logic.

    Args:
        file_url: The URL to download from.
        download_path: The base directory to download to.
        file_type: Description of file type for logging (e.g., 'label', 'inventory').

    Returns:
        A tuple of (success, error_msg). error_msg is None on success.
    """
    local_file = os.path.join(download_path, urllib.parse.urlparse(file_url).path[1:])
    last_error = None
    for attempt in range(1, _max_retries + 1):
        try:
            _logger.info("Downloading %s: %s", file_type, file_url)
            _logger.debug("  Attempt %d/%d", attempt, _max_retries)
            response = requests.get(file_url)
            if response.status_code != HTTPStatus.OK:
                last_error = f"Unexpected status {response.status_code}"
                _logger.warning("%s while trying to download %s", last_error, file_url)
                if attempt < _max_retries:
                    time.sleep(_retry_delay)
                continue
            os.makedirs(os.path.dirname(local_file), exist_ok=True)
            with open(local_file, "wb") as io:
                for buf in response.iter_content(chunk_size=_bufsiz):
                    io.write(buf)
            _logger.info("Successfully downloaded %s", file_type)
            return (True, None)
        except requests.exceptions.RequestException as e:
            last_error = f"Network error: {e}"
            _logger.warning("%s while downloading %s", last_error, file_url)
            if attempt < _max_retries:
                time.sleep(_retry_delay)
    _logger.error("Failed to download %s after %d attempts: %s", file_url, _max_retries, last_error)
    return (False, last_error)


def _should_exclude_url(url: str, exclude_patterns: List[str]) -> bool:
    """Check if URL path matches any exclude patterns.

    Performs a simple substring search - if any pattern appears anywhere in the URL path,
    the file is excluded. Patterns are NOT regex or globs, just literal strings.

    Args:
        url: Full URL to check (e.g., 'https://example.com/archive/nasa/pds/data/file.xml')
        exclude_patterns: List of literal string patterns to search for in the path

    Returns:
        True if the URL should be excluded, False otherwise

    Example:
        >>> _should_exclude_url('https://ex.com/archive/nasa/pds/data.xml', ['nasa/pds'])
        True  # 'nasa/pds' found in path '/archive/nasa/pds/data.xml'
    """
    if not exclude_patterns:
        return False
    url_path = urllib.parse.urlparse(url).path
    for pattern in exclude_patterns:
        if pattern in url_path:
            _logger.debug("Excluding URL %s (matches pattern: %s)", url, pattern)
            return True
    return False


def _download_product_collection_inventory(
    props: dict, download_path: str, force: bool, exclude_patterns: List[str]
) -> Tuple[bool, Optional[str]]:
    """Download inventory file for Product_Collection products.

    Args:
        props: Product properties dictionary
        download_path: Directory to save downloaded files
        force: If True, skip cached-file checks
        exclude_patterns: List of URL path patterns to exclude

    Returns:
        A tuple of (success, error_msg). error_msg is None on success.
    """
    data_file_refs = props.get("ops:Data_File_Info.ops:file_ref", [])
    if not data_file_refs:
        return (True, None)

    inventory_url = data_file_refs[0]

    # Check if inventory URL should be excluded
    if _should_exclude_url(inventory_url, exclude_patterns):
        _logger.info("Skipping inventory (excluded by pattern): %s", inventory_url)
        return (True, None)

    inventory_file = os.path.join(download_path, urllib.parse.urlparse(inventory_url).path[1:])

    # Check if already downloaded
    if "ops:Data_File_Info.ops:md5_checksum" in props:
        inventory_md5 = props["ops:Data_File_Info.ops:md5_checksum"][0]
        if not force and _already_downloaded(inventory_file, inventory_md5):
            _logger.info("Skipping inventory (already downloaded and intact): %s", inventory_file)
            return (True, None)

    _logger.info("Product_Collection: also downloading inventory: %s", inventory_url)
    inv_success, inv_error = _download_file(inventory_url, download_path, "inventory")
    if not inv_success:
        return (False, f"Label downloaded but inventory failed: {inv_error}")

    return (True, None)


def _download(product: dict, download_path: str, force: bool = False, exclude_patterns: Optional[List[str]] = None) -> Tuple[bool, Optional[str]]:
    """Download the XML label (and inventory, for Product_Collection) for ``product``.

    Skips labels already downloaded with a matching MD5 unless ``force`` is True.
    Skips files whose URLs match any of the ``exclude_patterns``.

    Returns:
        A tuple of (success, error_msg). error_msg is None on success.
    """
    if exclude_patterns is None:
        exclude_patterns = []

    props = product["properties"]
    label_url = props["ops:Label_File_Info.ops:file_ref"][0]

    # Check if label URL should be excluded
    if _should_exclude_url(label_url, exclude_patterns):
        _logger.info("Skipping label (excluded by pattern): %s", label_url)
        return (True, None)

    md5 = props["ops:Label_File_Info.ops:md5_checksum"][0]
    label_file = os.path.join(download_path, urllib.parse.urlparse(label_url).path[1:])

    if not force and _already_downloaded(label_file, md5):
        _logger.info("Skipping (already downloaded and intact): %s", label_file)
        return (True, None)

    success, error_msg = _download_file(label_url, download_path, "label")
    if not success:
        return (success, error_msg)

    # Handle Product_Collection inventory download
    product_class = props.get("product_class", [None])[0] if "product_class" in props else None
    if product_class == "Product_Collection":
        return _download_product_collection_inventory(props, download_path, force, exclude_patterns)

    return (True, None)


def _download_products(download_path: str, url: str, force: bool = False, exclude_patterns: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """Query the API at ``url`` and download matching XML labels to ``download_path``.

    Implements the algorithm from NASA-PDS/registry-legacy-solr#135:
    check registry → check local MD5 → download.

    Args:
        download_path: Directory to save downloaded files.
        url: PDS Search API URL.
        force: If True, skip cached-file checks and re-download everything.
        exclude_patterns: List of URL path patterns to exclude from download.

    Returns:
        A list of (label_url, error_msg) tuples for any failed downloads.
    """
    if exclude_patterns is None:
        exclude_patterns = []

    if exclude_patterns:
        _logger.info("Excluding URLs matching patterns: %s", ", ".join(exclude_patterns))

    _logger.info("Downloading products from %s to %s", url, download_path)
    failed: List[Tuple[str, str]] = []
    for product in _get_esa_psa_products(url):
        lidvid = _get_lidvid(product)
        if not force and _exists_in_registry(lidvid, url):
            continue
        success, error_msg = _download(product, download_path, force, exclude_patterns)
        if not success:
            label_url = product["properties"]["ops:Label_File_Info.ops:file_ref"][0]
            failed.append((label_url, error_msg or "unknown error"))
    return failed


def easy_peasy(node_name: str, download_path: str, url: str, config: str, force: bool = False, exclude_patterns: Optional[List[str]] = None) -> None:
    """Download ESA-PSA ("easy peasy") product files and write a harvest config file.

    Args:
        node_name: Name of the node (currently unused).
        download_path: Directory to save downloaded files.
        url: PDS Search API URL.
        config: Path to write harvest configuration file.
        force: If True, skip cached-file checks and re-download everything.
        exclude_patterns: List of URL path patterns to exclude from download.
    """
    os.makedirs(download_path, exist_ok=True)
    _write_harvest_config(download_path, config)
    failed = _download_products(download_path, url, force, exclude_patterns)

    sep = "=" * 80
    if failed:
        _logger.error("%s", sep)
        _logger.error("DOWNLOAD SUMMARY: %d label(s) failed after %d retries", len(failed), _max_retries)
        for label_url, error_msg in failed:
            _logger.error("  - %s: %s", label_url, error_msg)
        _logger.error("%s", sep)
    else:
        _logger.info("%s", sep)
        _logger.info("DOWNLOAD SUMMARY: All labels downloaded successfully!")
        _logger.info("%s", sep)


def main() -> None:
    """Entry point for the pds-sync-api command."""
    parser = argparse.ArgumentParser(
        description="Download ESA PSA product XML files from the PDS Search API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Exclude files with 'nasa/pds' anywhere in the URL path
  # (e.g., https://example.com/archive/nasa/pds/data/file.xml)
  %(prog)s --exclude-patterns nasa/pds

  # Exclude multiple patterns (any match excludes the file)
  %(prog)s --exclude-patterns nasa/pds some/other/path

  # Force re-download with exclusions
  %(prog)s --force --exclude-patterns nasa/pds

Note: Patterns are literal strings (not regex or globs) searched as substrings
      anywhere in the URL path component.
        """
    )
    parser.add_argument("-n", "--node-name", default="psa", help="Name of the node (default: %(default)s)")
    parser.add_argument(
        "-p", "--download-path", default="download", help="Where to write downloaded XML files (default: %(default)s)"
    )
    parser.add_argument(
        "-u", "--url", default=PROD_SEARCH_API_URL, help="PDS product search API URL (default: %(default)s)"
    )
    parser.add_argument("-c", "--config", default="harvest.cfg", help="Harvest XML config output path (default: %(default)s)")
    parser.add_argument("-f", "--force", action="store_true", help="Force download, skipping all cached-file checks")
    parser.add_argument(
        "-e", "--exclude-patterns", nargs="+", metavar="PATTERN",
        help="Exclude files if any pattern appears anywhere in the URL path (simple substring match, "
             "not regex or glob). Example: 'nasa/pds' will exclude any URL containing that string in its path."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG-level logging")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    # The PDS API is finicky about trailing slashes
    url = args.url.rstrip("/")

    # Validate URL before making any requests (SSRF protection)
    try:
        _validate_url(url)
    except ValueError as e:
        _logger.exception("Invalid URL: %s", e)
        parser.exit(1, f"Error: {e}\n")

    easy_peasy(args.node_name, args.download_path, url, args.config, args.force, args.exclude_patterns)


if __name__ == "__main__":
    main()
