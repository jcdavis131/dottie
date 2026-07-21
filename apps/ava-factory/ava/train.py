"""Shim: ava.train -> dottie.train (renamed to Dottie)"""

import sys

import dottie.train as _m
from dottie.train import *  # noqa: F403

sys.modules[__name__] = _m
