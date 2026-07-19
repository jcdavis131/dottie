"""Shim: ava.decoding -> dottie.decoding"""
from dottie.decoding import *  # noqa
import dottie.decoding as _m
import sys
sys.modules[__name__] = _m
