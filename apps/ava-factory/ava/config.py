"""Shim: ava.config -> dottie.config (renamed to Dottie)"""
from dottie.config import *  # noqa: F401,F403
import dottie.config as _m
import sys
sys.modules[__name__] = _m
