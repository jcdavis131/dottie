"""Shim: ava.pipeline -> dottie.pipeline"""
from dottie.pipeline import *  # noqa
import dottie.pipeline as _m
import sys
sys.modules[__name__] = _m
