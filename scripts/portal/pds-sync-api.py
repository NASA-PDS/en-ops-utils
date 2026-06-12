#!/usr/bin/env python3
# encoding: utf-8
#
# Backward-compatible entry point. After `pip install -e .` use the
# `pds-sync-api` console script instead.
#
from pds.en_ops_utils.portal.pds_sync_api import main

if __name__ == "__main__":
    main()
