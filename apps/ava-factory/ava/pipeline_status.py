"""Shim: ava.pipeline_status -> dottie.pipeline_status (renamed to Dottie)"""
from dottie.pipeline_status import *  # noqa: F401,F403
import dottie.pipeline_status as _m
import sys
sys.modules[__name__] = _m
