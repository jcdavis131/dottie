"""Shim: ava.data -> dottie.data (renamed to Dottie)"""

import sys

import dottie.data as _m
from dottie.data import *  # noqa: F403

sys.modules[__name__] = _m
