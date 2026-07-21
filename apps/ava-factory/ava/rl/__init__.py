"""Shim: ava.rl -> dottie.rl"""

from dottie.rl import *  # noqa
import dottie.rl as _m
import sys

sys.modules[__name__] = _m
