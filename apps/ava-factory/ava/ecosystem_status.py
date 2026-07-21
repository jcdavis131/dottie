"""Shim: ava.ecosystem_status -> dottie.ecosystem_status (renamed to Dottie)"""

import sys

import dottie.ecosystem_status as _m
from dottie.ecosystem_status import *  # noqa: F403

sys.modules[__name__] = _m
