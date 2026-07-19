"""Shim: ava.llmvm -> dottie.llmvm"""
from dottie.llmvm import *  # noqa
import dottie.llmvm as _m
import sys
sys.modules[__name__] = _m
