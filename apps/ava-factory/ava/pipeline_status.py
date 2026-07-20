"""Shim: ava.pipeline_status -> dottie.pipeline_status (renamed to Dottie)"""

import sys

import dottie.pipeline_status as _m
from dottie.pipeline_status import *  # noqa: F403

sys.modules[__name__] = _m
