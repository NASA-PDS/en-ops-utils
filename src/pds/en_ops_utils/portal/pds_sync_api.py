# encoding: utf-8
"""Sync ESA PSA products to Search API by downloading their XML label files."""
import argparse
import hashlib
import logging
import os
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


def _get_lidvid(product: dict) -> str:
    """Get the LIDVID from a ``product``."""
    try:
        return product["properties"]["lidvid"]
    except KeyError:
        return product["id"]


def _get_esa_psa_products(url: str) -> Generator[dict, None, None]:
    """Query the ESA PSA ("easy peasy") products from the registry."""
    params: dict = {"sort": _search_key, "limit": _query_page_size, "q": _psa_query}
    _logger.info("Generating ESA-PSA products from %s", url)
    while True:
        _logger.debug("Making request to %s with params %r", url, params)
        r = requests.get(url, params=params)
        r.raise_for_status()
        matches = r.json()["data"]
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


def _exists_in_registry(lidvid: str, url: str) -> bool:
    """Tell (true or false) if the given ``lidvid`` exists in the registry at ``url``."""
    _logger.debug("Checking if lidvid %s is already in the registry", lidvid)
    response = requests.head(f"{url}{lidvid}")
    if response.status_code == HTTPStatus.OK:
        return True
    elif response.status_code == HTTPStatus.NOT_FOUND:
        return False
    else:
        raise ValueError(f"Unexpected {response.status_code} while checking for existence of {lidvid}")


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


def _download(product: dict, download_path: str, force: bool = False) -> Tuple[bool, Optional[str]]:
    """Download the XML label (and inventory, for Product_Collection) for ``product``.

    Skips labels already downloaded with a matching MD5 unless ``force`` is True.

    Returns:
        A tuple of (success, error_msg). error_msg is None on success.
    """
    props = product["properties"]
    label_url = props["ops:Label_File_Info.ops:file_ref"][0]
    md5 = props["ops:Label_File_Info.ops:md5_checksum"][0]
    label_file = os.path.join(download_path, urllib.parse.urlparse(label_url).path[1:])

    if not force and _already_downloaded(label_file, md5):
        _logger.info("Skipping (already downloaded and intact): %s", label_file)
        return (True, None)

    success, error_msg = _download_file(label_url, download_path, "label")
    if not success:
        return (success, error_msg)

    product_class = props.get("product_class", [None])[0] if "product_class" in props else None
    if product_class == "Product_Collection" and "ops:Data_File_Info.ops:file_ref" in props:
        data_file_refs = props["ops:Data_File_Info.ops:file_ref"]
        if data_file_refs:
            inventory_url = data_file_refs[0]
            inventory_file = os.path.join(download_path, urllib.parse.urlparse(inventory_url).path[1:])
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


def _download_products(download_path: str, url: str, force: bool = False) -> List[Tuple[str, str]]:
    """Query the API at ``url`` and download matching XML labels to ``download_path``.

    Implements the algorithm from NASA-PDS/registry-legacy-solr#135:
    check registry → check local MD5 → download.

    Returns:
        A list of (label_url, error_msg) tuples for any failed downloads.
    """
    _logger.info("Downloading products from %s to %s", url, download_path)
    failed: List[Tuple[str, str]] = []
    for product in _get_esa_psa_products(url):
        lidvid = _get_lidvid(product)
        if not force and _exists_in_registry(lidvid, url):
            continue
        success, error_msg = _download(product, download_path, force)
        if not success:
            label_url = product["properties"]["ops:Label_File_Info.ops:file_ref"][0]
            failed.append((label_url, error_msg or "unknown error"))
    return failed


def easy_peasy(node_name: str, download_path: str, url: str, config: str, force: bool = False) -> None:
    """Download ESA-PSA ("easy peasy") product files and write a harvest config file."""
    os.makedirs(download_path, exist_ok=True)
    _write_harvest_config(download_path, config)
    failed = _download_products(download_path, url, force)

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
    parser = argparse.ArgumentParser(description="Download ESA PSA product XML files from the PDS Search API")
    parser.add_argument("-n", "--node-name", default="psa", help="Name of the node (default: %(default)s)")
    parser.add_argument(
        "-p", "--download-path", default="download", help="Where to write downloaded XML files (default: %(default)s)"
    )
    parser.add_argument(
        "-u", "--url", default=PROD_SEARCH_API_URL, help="PDS product search API URL (default: %(default)s)"
    )
    parser.add_argument("-c", "--config", default="harvest.cfg", help="Harvest XML config output path (default: %(default)s)")
    parser.add_argument("-f", "--force", action="store_true", help="Force download, skipping all cached-file checks")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG-level logging")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    # The PDS API is finicky about trailing slashes
    url = args.url.rstrip("/")
    easy_peasy(args.node_name, args.download_path, url, args.config, args.force)


if __name__ == "__main__":
    main()
