"""Shim: ava.tokenizer -> dottie.tokenizer (renamed to Dottie)"""

import sys

import dottie.tokenizer as _m
from dottie.tokenizer import *  # noqa: F403

sys.modules[__name__] = _m
