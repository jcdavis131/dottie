"""Shim: ava.data -> dottie.data (renamed to Dottie)"""
from dottie.data import *  # noqa: F401,F403
import dottie.data as _m
import sys
sys.modules[__name__] = _m
