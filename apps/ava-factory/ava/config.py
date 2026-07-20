"""Shim: ava.config -> dottie.config (renamed to Dottie)"""

import sys

import dottie.config as _m
from dottie.config import *  # noqa: F403

sys.modules[__name__] = _m
