"""Shim: ava.ecosystem_status -> dottie.ecosystem_status (renamed to Dottie)"""
from dottie.ecosystem_status import *  # noqa: F401,F403
import dottie.ecosystem_status as _m
import sys
sys.modules[__name__] = _m
