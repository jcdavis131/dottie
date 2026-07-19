"""Shim: ava.jlosses -> dottie.jlosses (renamed to Dottie)"""
from dottie.jlosses import *  # noqa: F401,F403
import dottie.jlosses as _m
import sys
sys.modules[__name__] = _m
