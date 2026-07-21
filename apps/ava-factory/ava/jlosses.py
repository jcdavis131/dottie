"""Shim: ava.jlosses -> dottie.jlosses (renamed to Dottie)"""

import sys

import dottie.jlosses as _m
from dottie.jlosses import *  # noqa: F403

sys.modules[__name__] = _m
