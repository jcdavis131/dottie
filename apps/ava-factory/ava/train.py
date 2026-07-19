"""Shim: ava.train -> dottie.train (renamed to Dottie)"""
from dottie.train import *  # noqa: F401,F403
import dottie.train as _m
import sys
sys.modules[__name__] = _m
