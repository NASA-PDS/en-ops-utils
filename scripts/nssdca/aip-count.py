#!/usr/bin/env python3
"""
NSSDCA AIP Count Monitoring Script

Monitors the count of AIP files in the manifests directory and triggers
collection regeneration when changes are detected.

Usage:
    python3 aip-count.py

Environment Variables:
    PDS4_MANIFESTS_PATH    - Manifests directory (default: /path/to/pds4/manifests/)
    NSSDCA_SCRIPTS_PATH    - Scripts directory (default: /path/to/nssdca-scripts/)
"""

import datetime
import glob
import os
import subprocess

# Configurable paths via environment variables
manifests_path = os.environ.get('PDS4_MANIFESTS_PATH', '/path/to/pds4/manifests/')
script_path = os.environ.get('NSSDCA_SCRIPTS_PATH', '/path/to/nssdca-scripts/')
inventory_dir = 'inventory/'

# Ensure trailing slash
if not manifests_path.endswith('/'):
    manifests_path += '/'
if not script_path.endswith('/'):
    script_path += '/'

current_count = 0


def compare_counts():
    os.chdir(manifests_path)
    main_count = len(glob.glob('*aip*xml'))
    sub_count = len(glob.glob('*/*aip*xml'))
    global current_count
    current_count = main_count + sub_count

    sp = subprocess.run(['tail', '-1', script_path + 'aip-count.txt'], stdout=subprocess.PIPE)
    prev_count = sp.stdout.decode('utf-8').split()[1]

    print('aip-count.py: prev_count: ', prev_count)
    print('aip-count.py: current_count: ', current_count)

    if int(prev_count) != current_count:
        print('aip-count.py: running `makeCollection.py`')
        run_collection_script()
    else:
        print('aip-count.py: count is same; no need to run `makeCollection.py`')
        log_latest(False)


def run_collection_script():
    os.chdir(script_path + inventory_dir)
    subprocess.run(['python3', 'makeCollection.py', manifests_path])
    move_latest()


def move_latest():
    # Find the highest version number from existing collection files
    aip_files = glob.glob('Collection_product_aip_v*.xml')
    sip_files = glob.glob('Collection_product_sip_deep_archive_v*.xml')

    versions = []
    for f in aip_files + sip_files:
        try:
            # Extract version (e.g., "Collection_product_aip_v57.0.xml" -> "57.0")
            v_part = f.split('_v')[1]  # "57.0.xml"
            v_str = v_part.rsplit('.xml', 1)[0]  # "57.0"
            # Convert to float for comparison, then back to string to preserve format
            versions.append((float(v_str), v_str))
        except (IndexError, ValueError):
            continue

    if not versions:
        print('aip-count.py: ERROR - No collection files found to move')
        return

    # Get the version string with highest numeric value
    version = max(versions, key=lambda x: x[0])[1]

    files_to_move = glob.glob(f'*v{version}.*')
    if files_to_move:
        print(f'aip-count.py: moving Collection_product_*v{version}* files to manifests/ and manifests/inventory/ directories')
        subprocess.run(['rsync', '-av'] + files_to_move + [manifests_path])
        subprocess.run(['rsync', '-av'] + files_to_move + [manifests_path + inventory_dir])
    else:
        print(f'aip-count.py: WARNING - No v{version} files found to move')

    # Calculate previous version (57.0 -> 56.0)
    prev_version = str(int(float(version)) - 1) + ".0"
    remove_previous(prev_version)
    log_latest(version)
    cleanup_old_versions()


def remove_previous(version):
    """Remove previous version from manifests directory."""
    os.chdir(manifests_path)
    files_to_remove = glob.glob('Collection_product_*v' + version + '*')
    if files_to_remove:
        print(f'aip-count.py: removing previous version v{version} from manifests/')
        subprocess.run(['rm'] + files_to_remove)
    else:
        print(f'aip-count.py: no v{version} files found to remove (already cleaned up)')


def cleanup_old_versions():
    """Keep only the 2 most recent versions in inventory directory."""
    os.chdir(script_path + inventory_dir)

    # Process each collection type separately
    for base_name in ['Collection_product_aip', 'Collection_product_sip_deep_archive']:
        xml_files = sorted(glob.glob(f'{base_name}_v*.xml'))
        csv_files = sorted(glob.glob(f'{base_name}_v*.csv'))

        # Extract versions and sort numerically
        def get_version(filename):
            try:
                v_part = filename.split('_v')[1]
                v_str = v_part.rsplit('.', 1)[0]  # Remove extension
                return float(v_str)
            except (IndexError, ValueError):
                return 0

        xml_files.sort(key=get_version)
        csv_files.sort(key=get_version)

        # Keep only the 2 most recent versions - each version has 2 CSV and 2 XML
        old_xmls = xml_files[:-2] if len(xml_files) > 2 else []
        old_csvs = csv_files[:-2] if len(csv_files) > 2 else []

        files_to_remove = old_xmls + old_csvs
        if files_to_remove:
            print(f'aip-count.py: cleaning up old {base_name} versions from inventory/')
            for f in files_to_remove:
                print(f'  removing: {f}')
                os.remove(f)


def log_latest(version):
    with open(script_path + 'aip-count.txt', 'a') as fo:
        fo.write('\n')
        if type(version) == bool:
            fo.write('{:%Y%m%d%H%M%S}'.format(datetime.datetime.now()) + ' ' + str(current_count))
        else:
            fo.write('{:%Y%m%d%H%M%S}'.format(datetime.datetime.now()) + ' ' + str(current_count) + '\t# v' + version)


compare_counts()
