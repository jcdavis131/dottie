"""Shim: ava.datagen -> dottie.datagen"""
from dottie.datagen import *  # noqa
import dottie.datagen as _m
import sys
sys.modules[__name__] = _m
