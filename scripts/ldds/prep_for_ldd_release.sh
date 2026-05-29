#!/bin/bash

# Script to update discipline LDD repos with the template Github action:
# 
# * clone template repo
# * loop through discipline LDD repos and:
#   * clone the repo
#   * copy the github action from the template repo to the LDD repo
#   * push to main
#   

usage () {
    echo "$(basename $0) <pds4_release_number> [<repo-name>]"
    echo "          * pds4_release_number - e.g. 1.15.0.0"
    echo
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

release=$1
repo=$2

if [ -z "$PDSEN_OPS_TOKEN" ]; then
  echo "Must set PDSEN_OPS_TOKEN environment variable prior to execution"
fi

BRANCH_NAME="release/$release"

dLDDs=()

# LDDs in development to ignore for prepping release
DEV_LDDS=( "ldd-wave" )

if [ -z "$repo" ]; then
    while read -r line; do
        if [[ "$line" == ldd-*: ]]; then
            for dev_ldd in "${DEV_LDDS[@]}"; do
                if [[ "$line" != "$dev_ldd": ]]; then
                    dLDDs+=("${line%?}")
                fi
            done
        fi
    done < ../../conf/ldds/config.yml
else
    dLDDs+=("$repo")
fi

BASE_CLONE_URL=git@github.com:pds-data-dictionaries
GITHUB_API_URL="https://api.github.com/repos/pds-data-dictionaries"

PR_BODY=$(cat <<EOF

## Updates
* Added new PDS4 version to pds4_versions.txt
* New schemas "should" be generated automatically by the github actions

---

## Steward Reviewer Checklist

Before approving this PR, please verify the following:

### 1. CI Build Passed
- [ ] Confirm the LDD GitHub Actions build completed successfully — look for a green check next to the latest commit, or check the Actions tab

### 2. Files Changed Tab Review
Navigate to the **Files changed** tab of this PR and verify:
- [ ] New LDD output files were generated (i.e., the build did not produce zero changes)
- [ ] New LDD files reflect the new IM version number in their filenames (e.g., PDS4_<namespace>_${release}.*)
- [ ] The IngestLDD source file (under src/) looks correct (if changed) — search the Files tab for IngestLDD to jump directly to it
- [ ] Expected output formats are present: .xsd, .sch, .xml, .json, .zip

### 3. Approve
- [ ] Once all checks pass, submit your review approval from the **Files changed** tab

### 4. Merge
- [ ] The Steward must merge this PR for it to get tagged and be included in the release.

Full review guidance: https://pds-data-dictionaries.github.io/development/ldd-how-to.html#reviewing-a-pull-request
EOF
)

PR_JSON=$(jq -n \
  --arg title "PDS4 Information Model Release $release" \
  --arg body  "$PR_BODY" \
  --arg head  "$BRANCH_NAME" \
  --arg base  "main" \
  '{title: $title, body: $body, head: $head, base: $base}')

cd /tmp || exit

echo ">> cloning template repo"
rm -fr ldd-template
git clone $BASE_CLONE_URL/ldd-template.git

for repo in "${dLDDs[@]}"; do
    rm -fr "$repo"
    echo ">> cloning $repo repo"
    git clone $BASE_CLONE_URL/${repo}.git || continue
    
    echo "copying github action"
    cp ldd-template/.github/workflows/*.yml "${repo}"/.github/workflows/

    echo "copying pull request template"
    cp ldd-template/.github/pull_request_template.md "${repo}"/.github/pull_request_template.md

    cd "${repo}" || exit

    # set admin user
    git config --local user.email "pds-ops@jpl.nasa.gov"
    git config --local user.name "PDSEN Ops"

    # delete branch if it exists
    # NOTE: errors may be thrown here if branch doesn't exist
    git branch -d "$BRANCH_NAME"
    git push origin --delete "$BRANCH_NAME"

    # create branch
    git checkout -b "$BRANCH_NAME"

    # add new PDS4 version to config file
    check=$(grep "$release" pds4_versions.txt)
    if [ -z "$check" ]; then
        echo "$release" >> pds4_versions.txt
    fi

    # add the updated
    git status
    git add -A .
    git commit --allow-empty -m "Prep for tagging PDS4 Release $release"
    git push origin "$BRANCH_NAME"

    # cleanup
    cd ..
    rm -fr "${repo}"

    # create PR
    curl -X POST -u "pds-ops:${PDSEN_OPS_TOKEN}" -d "$PR_JSON" "$GITHUB_API_URL/${repo}/pulls"

    echo
    echo
    sleep 10
done

rm -fr ldd-template

exit 0
