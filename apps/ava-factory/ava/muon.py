"""Shim: ava.muon -> dottie.muon (renamed to Dottie)"""

import sys

import dottie.muon as _m
from dottie.muon import *  # noqa: F403

sys.modules[__name__] = _m
