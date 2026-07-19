"""Shim: ava.muon -> dottie.muon (renamed to Dottie)"""
from dottie.muon import *  # noqa: F401,F403
import dottie.muon as _m
import sys
sys.modules[__name__] = _m
