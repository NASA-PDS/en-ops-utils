# -*- coding: utf-8 -*-
"""PDS Engineering Node operational utilities."""
import importlib.resources

__version__ = VERSION = importlib.resources.files(__name__).joinpath("VERSION.txt").read_text().strip()
