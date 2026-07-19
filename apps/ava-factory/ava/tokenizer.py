"""Shim: ava.tokenizer -> dottie.tokenizer (renamed to Dottie)"""
from dottie.tokenizer import *  # noqa: F401,F403
import dottie.tokenizer as _m
import sys
sys.modules[__name__] = _m
