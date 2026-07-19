"""Shim: ava.serve_engine -> dottie.serve_engine (renamed to Dottie)"""
from dottie.serve_engine import *  # noqa: F401,F403
import dottie.serve_engine as _m
import sys
sys.modules[__name__] = _m
