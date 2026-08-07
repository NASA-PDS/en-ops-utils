#!/usr/bin/env python3
"""
NSSDCA AIP/SIP Delivery Processing Script

Process NSSDCA delivery sets: unpacks archives, validates labels,
extracts metadata, and posts to NSSDCA automator.

Usage:
    python3 nssdca.py <ticket_number> [options]

Options:
    -D, --Debug         Enable debug mode (keeps backups, verbose output)
    -P, --Post          Post validated sets to NSSDCA automator
    -f, --force         Use with -P to post without validation
    -v, --validate      Validate sets only
    -l, --lid           Extract logical identifiers
    -m, --manifest-url  Extract year from manifest URLs
    -d, --date          Update last modified dates
    -p, --permissions   Set file permissions to 664

Environment Variables:
    PDS4_MANIFESTS_PATH    - Manifests directory (default: /path/to/pds4/manifests/)
    NSSDCA_DELIVERIES_PATH - Base directory for deliveries (default: /path/to/nssdca/deliveries/)

Security:
    - Validates archive contents for path traversal
    - Limits archive nesting depth to prevent zip bombs
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

DEBUG = None
full_run = True
unpack_depth = 0
MAX_UNPACK_DEPTH = 3

# Configurable paths via environment variables
nssdca_path = os.environ.get('NSSDCA_DELIVERIES_PATH', '/path/to/nssdca/deliveries/)')
manifests_path = os.environ.get('PDS4_MANIFESTS_PATH', '/path/to/pds4/manifests/')

# Ensure trailing slash
if not nssdca_path.endswith('/'):
    nssdca_path += '/'
if not manifests_path.endswith('/'):
    manifests_path += '/'

# Global state - appropriate for single-execution script
labels = []
valid_labels = []
labels_and_years = []
labels_without_years = []
lids = []
rsynced = []
indent = '   '
separator_line = '*' * 100

broken_url = True  # https://nssdc.gsfc.nasa.gov/psi/ReportPDS4.jsp


def parse_arguments():
    parser = argparse.ArgumentParser()

    parser.add_argument('directory', help='directory name (aka the ticket number)', type=int)
    parser.add_argument('-D', '--Debug', help='use debug mode (this is NOT a dry run)', action='store_true')
    parser.add_argument('-P', '--Post', help='post AIP/SIP sets for NSSDCA automator', action='store_true')
    parser.add_argument('-f', '--force', help='used with -P flag to post without validating', action='store_true')
    parser.add_argument('-d', '--date', help='set "last modified date" to current date', action='store_true')
    parser.add_argument('-l', '--lid', help='search LID (logical identifier)', action='store_true')
    parser.add_argument('-m', '--manifest-url', help='search manifest URL for year', action='store_true')
    parser.add_argument('-p', '--permissions', help='set file permissions to 664', action='store_true')
    parser.add_argument('-v', '--validate', help='validate sets', action='store_true')

    return vars(parser.parse_args())


def print_section_text(text, end='\n'):
    print(separator_line)
    print(f'### {text}', end=end)


def run_command(cmd, capture_output=False, check=True):
    """Run subprocess command with basic error handling."""
    try:
        if capture_output:
            return subprocess.run(cmd, stdout=subprocess.PIPE, check=check, timeout=300)
        else:
            return subprocess.run(cmd, check=check, timeout=300)
    except subprocess.TimeoutExpired:
        print(f'{indent}WARNING: Command timed out: {cmd[0]}')
        if check:
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f'{indent}WARNING: Command failed with code {e.returncode}: {" ".join(cmd)}')
        if check:
            sys.exit(1)
    except FileNotFoundError:
        print(f'{indent}ERROR: Command not found: {cmd[0]}')
        sys.exit(1)


def cd_ticket_dir(ticket_dir):
    """Change to ticket directory with security validation."""
    ticket_dir_str = str(ticket_dir)

    # Prevent path traversal
    if '..' in ticket_dir_str or '/' in ticket_dir_str or '\\' in ticket_dir_str:
        sys.exit(f'Exiting: Invalid characters in ticket directory: {ticket_dir}')

    full_path = nssdca_path + ticket_dir_str

    # Verify the resolved path is actually within nssdca_path
    resolved_path = os.path.realpath(full_path)
    resolved_base = os.path.realpath(nssdca_path)
    if not resolved_path.startswith(resolved_base):
        sys.exit(f'Exiting: Path traversal detected: {ticket_dir}')

    if not os.path.exists(full_path):
        sys.exit(f'Exiting: Invalid argument: no such directory "{ticket_dir}" exists in {nssdca_path}')

    os.chdir(full_path)
    print(f'Running `python3 {" ".join(sys.argv)}` with DEBUG={DEBUG}')


def unpack_sets(ticket_dir):
    """
    Unpack archive files with security checks.

    NOTE a: this ignores any files that are not .zips or .gzs
    NOTE b: a zip or tarball may contain more than one set of AIP/SIPs
    NOTE c: a zip or tarball may contain zips or tarballs (e.g., CSS submissions)
    """
    global unpack_depth
    unpack_depth += 1

    if unpack_depth > MAX_UNPACK_DEPTH:
        sys.exit(f'{indent}Exiting: Maximum archive nesting depth ({MAX_UNPACK_DEPTH}) exceeded - possible zip bomb')

    print_section_text('Unpack sets')

    zips, tarballs = glob.glob('*.zip'), glob.glob('*.t*gz')
    if len(zips) == 0 and len(tarballs) == 0:
        xmls, tabs = glob.glob('*.xml'), glob.glob('*.tab*')
        if len(xmls) % 2 == 0 and len(tabs) % 3 == 0:
            print(indent, 'Set files already present. No need to unpack.')
        else:
            sys.exit(indent + 'Exiting: No zips or tarballs found in ' + nssdca_path + ticket_dir)
    else:
        run_command(['mkdir', '-p', 'output'], check=False)
        run_command(['rm', '-f', 'output/unpacked.txt'], check=False)
        with open('output/unpacked.txt', 'w') as writer:
            if len(zips) != 0:
                for zip_file in zips:
                    # Security check: validate archive contents before unpacking
                    try:
                        with zipfile.ZipFile(zip_file, 'r') as zf:
                            for name in zf.namelist():
                                if name.startswith('/') or '..' in name:
                                    sys.exit(f'{indent}Exiting: Unsafe file path in archive {zip_file}: {name}')
                    except zipfile.BadZipFile:
                        sys.exit(f'{indent}Exiting: Corrupted zip file: {zip_file}')

                    run_command(['unzip', zip_file], check=False)
                    writer.write(f'Unpacked: {zip_file}\n')
                    if not DEBUG:
                        run_command(['rm', zip_file], check=False)
                    else:
                        backup_file(ticket_dir + '-backup', zip_file)

            if len(tarballs) != 0:
                for tarball in tarballs:
                    # Security check: validate tarball contents before unpacking
                    try:
                        with tarfile.open(tarball, 'r:gz') as tf:
                            for member in tf.getmembers():
                                if member.name.startswith('/') or '..' in member.name:
                                    sys.exit(f'{indent}Exiting: Unsafe file path in archive {tarball}: {member.name}')
                    except tarfile.TarError:
                        sys.exit(f'{indent}Exiting: Corrupted tarball: {tarball}')

                    run_command(['tar', '-xzvf', tarball], check=False)
                    writer.write(f'Unpacked: {tarball}\n')
                    if not DEBUG:
                        run_command(['rm', tarball], check=False)
                    else:
                        backup_file(ticket_dir + '-backup', tarball)

            for (dirpath, dirnames, filenames) in os.walk('.'):
                # should be just the temporary 'output' directory and files in multiples of 5
                # if there is more than 1 directory, assume set files are housed in other folders
                # there could also be more compressed files, regardless of quantity
                if len(dirnames) > 1:
                    for dirname in dirnames:
                        if dirname != 'output':
                            # SECURITY FIX: Use shutil.move instead of os.system
                            dir_path = Path(dirname)
                            for item in dir_path.iterdir():
                                shutil.move(str(item), '.')
                            dir_path.rmdir()
                for filename in filenames:
                    if filename.endswith('.zip') or filename.endswith('.gz'):
                        unpack_sets(ticket_dir)
                        break
                break
        if DEBUG:
            print(indent, f'DEBUG:unpack_files(): keeping compressed file(s) in backup directory `{ticket_dir}-backup`')

    unpack_depth -= 1


def backup_file(backup_directory, filename):
    subprocess.run(['mkdir', '-p', '../' + backup_directory])
    subprocess.run(['mv', filename, '../' + backup_directory])


def get_labels():
    for aip in glob.iglob('*aip*'):
        label = aip[:aip.find('aip') - 1]
        if label not in labels:
            labels.append(label)
    labels.sort()

    if DEBUG:
        print_section_text('Get labels')
        print(indent, 'DEBUG:get_labels(): ' + str(len(labels)) + ' items in [labels]:')
        for label in labels:
            print(indent, indent, label)


def validate_sets():
    """Validate AIP/SIP sets using PDS validate tool."""
    print_section_text('Validate sets')

    run_command(['mkdir', '-p', 'output/validate-reports'], check=False)
    for label in labels:
        validate_report = 'output/validate-reports/' + label + '-validate.txt'
        run_command(['validate', '-t'] + glob.glob(label + '*.xml') + ['-r', validate_report], check=False)

        # Check validation report for errors
        sp = run_command(['grep', '-L', '0 error', validate_report], capture_output=True, check=False)

        # BUGFIX: Always populate valid_labels, regardless of full_run mode
        if sp.stdout == b'':
            # Validation passed
            valid_labels.append(label)
            # Only remove report if full_run and not DEBUG
            if full_run and not DEBUG:
                os.remove(validate_report)
            else:
                print(indent, f'Keeping validation report for {label}')
        else:
            # Validation failed - always move report for inspection
            run_command(['mv', validate_report, '.'], check=False)
            print(indent, f'Validation error(s): check {label}-validate.txt')

    valid_labels.sort()

    if DEBUG:
        print(indent, f'DEBUG:validate_files(): {len(valid_labels)} items in [valid_labels]:')
        for valid_label in valid_labels:
            print(indent, indent, valid_label)


def grep_lid():
    """Extract logical identifiers from SIP XML files using XML parsing."""
    print_section_text('Get logical identifiers (LIDs)')

    for label in labels:
        sip_files = glob.glob(label + '*sip*xml')
        if not sip_files:
            print(indent, f'WARNING: No SIP file found for label {label}')
            continue

        try:
            tree = ET.parse(sip_files[0])
            root = tree.getroot()
            # Find logical_identifier element (handles both namespaced and non-namespaced tags)
            lid_elem = None
            for elem in root.iter():
                if elem.tag == 'logical_identifier' or elem.tag.endswith('}logical_identifier'):
                    lid_elem = elem
                    break

            if lid_elem is not None and lid_elem.text:
                lid = lid_elem.text.strip()
                if lid and lid not in lids:
                    lids.append(lid)
            else:
                print(indent, f'WARNING: No logical_identifier found in {sip_files[0]}')
        except ET.ParseError as e:
            print(indent, f'WARNING: Could not parse {sip_files[0]}: {e}')
        except Exception as e:
            print(indent, f'WARNING: Error processing {sip_files[0]}: {e}')

    lids.sort()

    if DEBUG:
        print(indent, f'DEBUG:grep_lid(): {len(lids)} items in [lids]:')
        for lid in lids:
            print(indent, indent, lid)


def grep_manifest_url():
    print_section_text('Search manifest URLs for year')

    for label in labels:
        sp = subprocess.run(['grep', '<manifest_url>'] + glob.glob(label + '*sip*xml'), stdout=subprocess.PIPE)
        manifest_url_element = sp.stdout.decode('utf-8').strip()
        idx = manifest_url_element.index('manifests') + len('manifests/')
        poss = manifest_url_element[idx:idx + 4]
        if poss.isdigit():
            year = poss
        else:
            year = '-'
            labels_without_years.append(label)
        labels_and_years.append((label, year))

    if DEBUG:
        print(indent, 'DEBUG:grep_manifest_url(): ' + str(len(labels_and_years)) + ' items in [labels_and_years]:')
        for lay in labels_and_years:
            print(indent, indent, lay)
        print(indent, 'DEBUG:grep_manifest_url(): ' + str(len(labels_without_years)) + ' items in [labels_without_years]:')
        for lwy in labels_without_years:
            print(indent, indent, lwy)


def touch_sets():
    print_section_text('Set "last modified date" to current date and time')

    for label in labels:
        for label_file in glob.glob(label + '*'):
            os.utime(label_file)


def chmod_sets():
    print_section_text('Change file permissions to 664 (owner and group can read and write. others can read.)')

    for label in labels:
        for label_file in glob.glob(label + '*'):
            os.chmod(label_file, 0o664)


def rsync_sets(skip_validate):
    """Post validated AIP/SIP sets to NSSDCA manifests directory."""
    print_section_text('Post sets to appropriate `manifests` directory', '')

    if skip_validate:
        print(' WITHOUT validate')
        labels_to_post = labels
        no_labels_comment = 'No sets to post.'
    else:
        print(' WITH validate')
        labels_to_post = valid_labels
        no_labels_comment = 'No valid or validated sets to post.'

    if len(labels_to_post) == 0:
        print(indent, no_labels_comment)
        return

    # Safety check: ensure labels_and_years was populated
    if len(labels_and_years) == 0:
        print(indent, 'ERROR: Manifest year data not available. Cannot post.')
        sys.exit(1)

    # BUGFIX: Use --exclude=pattern format to avoid orphaned --exclude flags
    if DEBUG:
        rsync_command = ['rsync', '-av', '--remove-source-files',
                        '--exclude=*.zip', '--exclude=*.gz', '--exclude=*.tar.gz']
    else:
        rsync_command = ['rsync', '-aq', '--remove-source-files',
                        '--exclude=*.zip', '--exclude=*.gz', '--exclude=*.tar.gz']

    for ltp in labels_to_post:
        for lay in labels_and_years:
            if ltp == lay[0]:
                if lay[1] == '-':
                    run_command(rsync_command + glob.glob(ltp + '_*') + [manifests_path], check=False)
                else:
                    run_command(rsync_command + glob.glob(ltp + '_*') + [manifests_path + lay[1] + '/'], check=False)
                rsynced.append(lay)
                break


def get_zip_of_sets(ticket_dir):
    if os.path.isfile(nssdca_path + ticket_dir + '/output/unpacked.txt'):
        with open(nssdca_path + ticket_dir + '/output/unpacked.txt', 'r') as reader:
            idx_zip = len('Archive:  ')
            idx_label = len('  inflating: ')
            zip_set, zip = {}, ''
            for lwy in labels_without_years:
                for line in reader:
                    if line.startswith('Archive'):
                        zip = line[idx_zip:].strip()
                    else:
                        if 'aip' in line:
                            temp_label = line[idx_label:line.index('_aip')]
                            if lwy == temp_label:
                                if zip in zip_set:
                                    zip_set[zip].append(temp_label)
                                else:
                                    zip_set[zip] = [temp_label]
                                    break

        if DEBUG:
            print(indent, 'DEBUG:get_zip_of_sets(): ')
            for k, v in zip_set.items():
                print(k, v)

        return zip_set
    else:
        return False


def cleanup(args):
    print_section_text('Clean up files')

    ticket_dir = str(args['directory'])
    zip_set = False
    if len(labels_without_years) != 0:
        zip_set = get_zip_of_sets(ticket_dir)
    if not ((not full_run and args['validate']) or DEBUG):
        subprocess.run(['rm', '-rf', 'output'])

    if len(os.listdir(nssdca_path + ticket_dir)) == 0:
        os.chdir(nssdca_path)
        os.rmdir(ticket_dir)
        print(indent, 'Removed ticket directory')
    else:
        print(indent, 'Ticket directory still has files inside. Manual resolution and clean-up may be required.')

    summarize(zip_set, args)


def summarize(zip_set, args):
    print_section_text('SUMMARY')

    if DEBUG:
        print(indent, 'DEBUG:summarize(zip_set=' + str(zip_set) + ', args={')
        for k, v in args.items():
            print('\t\t\t\t\'' + k + '\': ' + str(v))
        print('\t\t\t}')

    if args['manifest_url']:
        if len(labels_without_years) == 0:
            print(indent, '# All manifest URLs included a year.')
        else:
            print(indent, '# Labels missing a year from its manifest URL:')
            if zip_set is False:
                for lwy in labels_without_years:
                    print(indent, indent, '- ' + lwy)
            elif type(zip_set) is dict:
                for key, value in zip_set.items():
                    print(indent, indent, '- ' + key + ':')
                    for v in value:
                        print(indent, indent, '--- ' + v)

    if args['lid'] and not args['Post']:
        print(indent, '# Logical identifiers (LIDs):')
        for lid in lids:
            print(indent, indent, '- ' + lid)

    if args['validate']:
        if full_run:
            if len(valid_labels) == len(labels):
                print(indent, '# No validate errors.')
            else:
                print(indent, '# Labels with validate errors:')
                invalid_labels = [lbl for lbl in labels if lbl not in valid_labels]
                for invalid_label in invalid_labels:
                    print(indent, indent, '- ' + invalid_label)
        else:
            print(indent, '# Validate reports not grepped for errors and left for perusal in `<ticket-dir>/output/validate-reports`')

    if args['Post']:
        if len(rsynced) == 0:
            print(indent, '# No sets were posted for the NSSDCA automator')
        else:
            print(indent, '# ' + str(len(rsynced)) + ' of ' + str(len(labels)) + ' posted for the NSSDCA automator:')
            for r in rsynced:
                print(indent, indent, '- ' + r[1] + ': ' + r[0])
            print(indent, '# if applicable, c/p the following as a comment in the issue:')
            print('-' * 50)
            print_github_comment_to_notify_submitter()
            print('-' * 50)

    print()


def print_github_comment_to_notify_submitter():
    rsynced_lids = []
    for r in rsynced:
        for lid in lids:
            if r[0] in lid:
                rsynced_lids.append(lid)
                break
    
    quantity = 'single' if len(rsynced) == 1 else 'multiple'
    lid_ish = 'LID' if quantity == 'single' else 'LIDs'
    comment_start = '- this set has' if quantity == 'single' else f'- these {len(rsynced)} sets have' if quantity == 'multiple' else '--SOMETHING IS WRONG HERE--'

    comment = '@<submitter> ' + comment_start + ' been posted for NSSDCA processing! '
    if not broken_url:
        comment += f'From tomorrow, you can check the status at https://nssdc.gsfc.nasa.gov/psi/ReportPDS4.jsp ' \
                  'using the SIP {lid_ish} below:'

    print(comment)
    print()
    print(f'SIP {lid_ish}:')
    for rl in rsynced_lids:
        print('- ' + rl)


def main(**args):
    global full_run
    for k, v in args.items():
        if k != 'Debug' and k != 'force':
            if v is True:
                full_run = False
                break

    global DEBUG
    DEBUG = args['Debug']
    if DEBUG:
        print(indent, 'DEBUG:main(): executing full run? ' + str(full_run))
        print(indent, 'DEBUG:main(): args are')
        for k, v in args.items():
            print(indent, indent, k + ': ' + str(v))

    if full_run or args['Post']:
        args['manifest_url'] = True
        if args['Post'] and args['force']:
            args['validate'] = False
        else:
            args['validate'] = True
        args['lid'] = True
        args['date'] = True
        args['permissions'] = True
        args['Post'] = True

    ticket_directory = str(args['directory'])
    cd_ticket_dir(ticket_directory)
    unpack_sets(ticket_directory)
    get_labels()
    if args['manifest_url']:
        grep_manifest_url()
    if args['validate']:
        validate_sets()
    if args['lid']:
        grep_lid()
    if args['date']:
        touch_sets()
    if args['permissions']:
        chmod_sets()
    if args['Post']:
        rsync_sets(args['force'])
    cleanup(args)


if __name__ == '__main__':
    arguments = parse_arguments()
    main(**arguments)
