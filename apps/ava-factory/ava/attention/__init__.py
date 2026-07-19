"""Shim: ava.attention -> dottie.attention"""
from dottie.attention import *  # noqa
import dottie.attention as _m
import sys
sys.modules[__name__] = _m
