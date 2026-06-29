#!/usr/bin/env python
"""List Open Release PRs.

Tool to list all open pull requests created by prep_for_ldd_release.sh for a given PDS4 release version.
"""
import logging
import os
import sys
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from typing import List, Dict, Any

import yaml
from github3 import login

# Github Org containing Discipline LDDs
GITHUB_ORG = 'pds-data-dictionaries'

# Repos to skip
SKIP_REPOS = ['ldd-template', 'PDS-Data-Dictionaries.github.io', 'dd-library', 'PDS4-LDD-Issue-Repo']

# LDDs in development to ignore
DEV_LDDS = ['ldd-wave']

# LDD configuration file
LDD_CONFIG_PATH = os.path.join('..', '..', 'conf', 'ldds', 'config.yml')

# Quiet github3 logging
logger = logging.getLogger('github3')
logger.setLevel(level=logging.WARNING)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_ldd_repos(config_path: str, single_repo: str = None) -> List[str]:
    """Load LDD repository names from config file.

    :param config_path: Path to the config.yml file
    :param single_repo: Optional single repo name to check instead of all repos
    :return: List of repository names
    """
    repos = []

    if single_repo:
        return [single_repo]

    if not os.path.exists(config_path):
        logger.warning(f'Config file not found at {config_path}, will check all repos in org')
        return repos

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

    for repo_name in config.keys():
        if repo_name.startswith('ldd-') and repo_name not in DEV_LDDS:
            repos.append(repo_name)

    return repos


def get_pr_status_summary(pr) -> Dict[str, Any]:
    """Get summary of PR status including checks and reviews.

    :param pr: Pull request object
    :return: Dictionary with status information
    """
    status_info = {
        'mergeable': None,
        'mergeable_state': 'unknown',
        'checks_status': 'unknown',
        'review_status': 'none',
        'reviews': []
    }

    try:
        # Safely get mergeable state (may not always be available)
        if hasattr(pr, 'mergeable'):
            status_info['mergeable'] = pr.mergeable
        if hasattr(pr, 'mergeable_state'):
            status_info['mergeable_state'] = pr.mergeable_state

        # Get commit status (CI checks)
        if pr.head and pr.head.sha:
            # Note: This requires additional API calls, so we'll keep it simple
            # Users can click through to the PR URL for full details
            status_info['checks_status'] = 'see PR for details'

        # Get review summaries
        reviews = list(pr.reviews())
        if reviews:
            # Get the most recent review state from each reviewer
            reviewer_states = {}
            for review in reviews:
                reviewer_states[review.user.login] = review.state

            status_info['reviews'] = [
                f"{user}: {state}" for user, state in reviewer_states.items()
            ]

            # Overall review status
            if any(state == 'APPROVED' for state in reviewer_states.values()):
                status_info['review_status'] = 'approved'
            elif any(state == 'CHANGES_REQUESTED' for state in reviewer_states.values()):
                status_info['review_status'] = 'changes_requested'
            else:
                status_info['review_status'] = 'pending'
    except Exception as e:
        logger.debug(f'Error getting PR status details: {e}')

    return status_info


def list_open_prs(gh, args) -> List[Dict[str, Any]]:
    """List all open PRs for the given release version.

    :param gh: GitHub API client
    :param args: Command line arguments
    :return: List of PR information dictionaries
    """
    release_version = args.pds4_version
    expected_pr_title = f"PDS4 Information Model Release {release_version}"
    expected_branch = f"release/{release_version}"

    logger.info(f'Searching for open PRs with title: "{expected_pr_title}"')
    logger.info(f'Expected branch: {expected_branch}')
    logger.info('')

    # Get list of repos to check
    config_path = args.config or LDD_CONFIG_PATH
    repos_to_check = load_ldd_repos(config_path, args.repo)

    if not repos_to_check:
        # If no config, check all LDD repos in org
        logger.info(f'Checking all repos in {args.github_org}...')
        org = gh.organization(args.github_org)
        if not org:
            logger.error(f'Could not access org: {args.github_org}')
            return []
        repos_to_check = [
            repo.name
            for repo in org.repositories()
            if repo.name.startswith('ldd-') and repo.name not in SKIP_REPOS and repo.name not in DEV_LDDS
        ]
    else:
        logger.info(f'Checking {len(repos_to_check)} repos from config...')

    open_prs = []
    repos_with_prs = set()
    repos_checked = 0

    for repo_name in sorted(repos_to_check):
        if repo_name in SKIP_REPOS:
            continue

        repos_checked += 1

        try:
            repo = gh.repository(args.github_org, repo_name)
            if not repo:
                logger.warning(f'Could not access repo: {repo_name}')
                continue

            # Get open pull requests
            for pr in repo.pull_requests(state='open'):
                # Check if this is a release PR
                if pr.title == expected_pr_title or pr.head.ref == expected_branch:
                    repos_with_prs.add(repo_name)

                    # repo.pull_requests() returns ShortPullRequest objects; fetch the full PR
                    # to access mergeability/review information when available.
                    try:
                        pr_obj = repo.pull_request(pr.number)
                    except Exception:
                        pr_obj = pr

                    status = get_pr_status_summary(pr_obj)

                    pr_info = {
                        'repo': repo_name,
                        'pr_number': pr.number,
                        'url': pr_obj.html_url,
                        'mergeable_state': status['mergeable_state'],
                        'review_status': status['review_status'],
                        'reviews': status['reviews'],
                    }

                    open_prs.append(pr_info)
                    logger.info(f'✓ Found PR in {repo_name}: #{pr.number}')

        except Exception as e:
            logger.error(f'Error checking repo {repo_name}: {e}')
            continue

    logger.info('')
    logger.info(f'Checked {repos_checked} repos, found {len(repos_with_prs)} repos with open release PRs')
    logger.info('')

    return open_prs


def format_output(open_prs: List[Dict[str, Any]], args):
    """Format and display the list of open PRs.

    :param open_prs: List of PR information dictionaries
    :param args: Command line arguments
    """
    if not open_prs:
        print(f'No open PRs found for PDS4 release {args.pds4_version}')
        return

    print(f'Open Pull Requests for PDS4 Release {args.pds4_version}')
    print('=' * 80)
    print(f'Total: {len(open_prs)} open PR(s)\n')

    if args.format == 'detailed':
        # Detailed format with status information
        for pr in open_prs:
            print(f"Repository: {pr['repo']}")
            print(f"  PR: #{pr['pr_number']}")
            print(f"  URL: {pr['url']}")
            print(f"  Mergeable State: {pr['mergeable_state']}")
            print(f"  Review Status: {pr['review_status']}")
            if pr['reviews']:
                print(f"  Reviews:")
                for review in pr['reviews']:
                    print(f"    - {review}")
            print()

    elif args.format == 'summary':
        # Summary format - one line per PR
        print(f"{'Repository':<30} {'PR #':<8} {'Status':<20} {'URL'}")
        print('-' * 100)
        for pr in open_prs:
            status = pr['review_status']
            print(f"{pr['repo']:<30} #{pr['pr_number']:<7} {status:<20} {pr['url']}")

    elif args.format == 'simple':
        # URLs and repos for easy copy/pasting
        print('URLs:')
        print('-' * 80)
        for pr in open_prs:
            print(pr['url'])

        print()
        print('Repository Names:')
        print('-' * 80)
        for pr in open_prs:
            print(pr['repo'])


def main():
    """main"""
    parser = ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        description=__doc__
    )

    parser.add_argument(
        'pds4_version',
        help='PDS4 version to check. Format example: 1.15.0.0'
    )

    parser.add_argument(
        '--github_org',
        metavar='',
        help='GitHub org to search for LDD repos',
        default=GITHUB_ORG
    )

    parser.add_argument(
        '--token',
        metavar='',
        help='GitHub token (or set GITHUB_TOKEN env var)'
    )

    parser.add_argument(
        '--config',
        metavar='',
        help='Path to LDD config.yml file',
        default=None
    )

    parser.add_argument(
        '--repo',
        metavar='',
        help='Check only a specific repository instead of all LDD repos',
        default=None
    )

    parser.add_argument(
        '--format',
        metavar='',
        help='Output format. Accepts \'detailed\', \'summary\', or \'simple\'.',
        choices=['detailed', 'summary', 'simple'],
        default='simple'
    )

    args = parser.parse_args()

    token = args.token or os.environ.get('GITHUB_TOKEN')
    if not token:
        logger.error('GitHub token must be provided via --token or GITHUB_TOKEN environment variable')
        sys.exit(1)

    try:
        # Connect to GitHub
        gh = login(token=token)

        # Get open PRs
        open_prs = list_open_prs(gh, args)

        # Display results
        format_output(open_prs, args)

    except Exception as e:
        logger.error(f'Error: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
