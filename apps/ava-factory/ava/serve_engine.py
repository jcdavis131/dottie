"""Shim: ava.serve_engine -> dottie.serve_engine (renamed to Dottie)"""

import sys

import dottie.serve_engine as _m
from dottie.serve_engine import *  # noqa: F403

sys.modules[__name__] = _m
