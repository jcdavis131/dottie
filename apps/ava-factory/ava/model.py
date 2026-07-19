"""Shim: ava.model -> dottie.model (renamed to Dottie)"""
from dottie.model import *  # noqa: F401,F403
import dottie.model as _m
import sys
sys.modules[__name__] = _m
