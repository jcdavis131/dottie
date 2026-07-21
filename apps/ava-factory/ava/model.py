"""Shim: ava.model -> dottie.model (renamed to Dottie)"""

import sys

import dottie.model as _m
from dottie.model import *  # noqa: F403

sys.modules[__name__] = _m
