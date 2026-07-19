"""Shim: ava.mobile -> dottie.mobile"""
from dottie.mobile import *  # noqa
import dottie.mobile as _m
import sys
sys.modules[__name__] = _m
