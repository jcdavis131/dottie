"""Shim: ava.memory -> dottie.memory"""
from dottie.memory import *  # noqa
import dottie.memory as _m
import sys
sys.modules[__name__] = _m
