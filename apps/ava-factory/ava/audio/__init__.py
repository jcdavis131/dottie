"""Shim: ava.audio -> dottie.audio"""
from dottie.audio import *  # noqa
import dottie.audio as _m
import sys
sys.modules[__name__] = _m
